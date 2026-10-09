"""Tests for the docsync command line, with fakes for Google, the state store and PRs.

Each source page lives in a real git repository under `tmp_path`, so `git show`,
`git rev-parse` and `git merge-base` run for real. `FakeGoogle` stands in for the
`google` module: it keeps Docs as the Markdown last uploaded and exports them without
the trailing newline, as Drive does. `Proposals` stands in for `propose_edits` and
`GitHub` for what gh reports; the adapter and edit logic run unmocked.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from google.auth.exceptions import DefaultCredentialsError

from dfo_docs.docsync import cli
from dfo_docs.docsync.edits import MergeResult
from dfo_docs.docsync.git import Git, GitError, command_env
from dfo_docs.docsync.google import Comment, DriveFile, GoogleApiError
from dfo_docs.docsync.pages import HubCheckoutError, SyncPage
from dfo_docs.docsync.prs import (
    NoChangesError,
    OpenPullRequest,
    PullRequest,
    StaleBaseError,
    propose_edits,
)
from dfo_docs.docsync.state import (
    DirStateStore,
    PageState,
    StateConflictError,
    StateFormatError,
)

ROOT = "root-folder"
DRIVE = "drive-1"
SHEET = "sheet-1"
REPO = "ONEcampaign/dfo-apis"
PR_URL = "https://github.com/ONEcampaign/dfo-apis/pull/7"
PR_URL_2 = "https://github.com/ONEcampaign/dfo-apis/pull/8"

PAGE_TEXT = """\
---
description: How to call the API.
---

# Call the API

Send a request with your token.

Read the response as JSON.
"""


@dataclass
class FakeDoc:
    name: str
    markdown: str
    parent: str
    properties: dict[str, str]


@dataclass
class FakeGoogle:
    """The subset of `dfo_docs.docsync.google` the CLI calls, held in memory."""

    docs: dict[str, FakeDoc] = field(default_factory=dict)
    folders: dict[tuple[str, ...], str] = field(default_factory=dict)
    comments: dict[str, list[Comment]] = field(default_factory=dict)
    suggestions: dict[str, frozenset[str]] = field(default_factory=dict)
    sheets: list[DriveFile] = field(default_factory=list)
    sheet_properties: dict[str, dict[str, str]] = field(default_factory=dict)
    tabs: dict[str, list[str]] = field(default_factory=dict)
    rows: dict[str, dict[str, str]] = field(default_factory=dict)
    upserts: list[list[dict[str, str]]] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    trashed: list[str] = field(default_factory=list)
    revisions: dict[str, int] = field(default_factory=dict)
    export_override: dict[str, str] = field(default_factory=dict)
    """A one-shot export per Doc, returned by the next `export_markdown` call."""

    # Drive
    def get_drive_id(self, session, file_id: str) -> str:
        assert file_id == ROOT
        return DRIVE

    def ensure_folder_path(
        self, session, *, drive_id: str, parent_id: str, names: Sequence[str]
    ) -> str:
        assert (drive_id, parent_id) == (DRIVE, ROOT)
        return self.folders.setdefault(tuple(names), f"folder-{len(self.folders)}")

    def create_doc(
        self,
        session,
        *,
        name: str,
        markdown: str,
        parent_id: str,
        properties: Mapping[str, str],
    ) -> str:
        doc_id = f"doc-{len(self.docs) + len(self.trashed) + 1}"
        self.docs[doc_id] = FakeDoc(name, markdown, parent_id, dict(properties))
        return doc_id

    def replace_doc_content(self, session, *, file_id: str, markdown: str) -> None:
        self.docs[file_id].markdown = markdown
        self.replaced.append(file_id)

    def export_markdown(self, session, file_id: str) -> str:
        if file_id in self.export_override:
            return self.export_override.pop(file_id)
        return self.docs[file_id].markdown.rstrip("\n")

    def export_settled(self, session, file_id: str) -> str:
        return self.export_markdown(session, file_id)

    def trash_file(self, session, file_id: str) -> None:
        del self.docs[file_id]
        self.trashed.append(file_id)

    def list_open_comments(self, session, file_id: str) -> list[Comment]:
        return self.comments.get(file_id, [])

    def list_synced_docs(self, session, *, drive_id: str) -> dict[str, list[DriveFile]]:
        synced: dict[str, list[DriveFile]] = {}
        for doc_id, doc in self.docs.items():
            if page_id := doc.properties.get("dfo_page_id"):
                synced.setdefault(page_id, []).append(
                    DriveFile(id=doc_id, name=doc.name, properties=doc.properties)
                )
        return synced

    def find_files_with_property(
        self,
        session,
        *,
        drive_id: str,
        parent_id: str,
        mime_type: str,
        key: str,
        value: str,
    ) -> list[DriveFile]:
        return [
            sheet
            for sheet in self.sheets
            if self.sheet_properties.get(sheet.id, {}).get(key) == value
        ]

    def set_properties(
        self, session, file_id: str, properties: Mapping[str, str]
    ) -> None:
        self.sheet_properties.setdefault(file_id, {}).update(properties)

    # Docs
    def open_suggestion_ids(self, session, document_id: str) -> frozenset[str]:
        return self.suggestions.get(document_id, frozenset())

    def doc_revision_id(self, session, document_id: str) -> str:
        return str(self.revisions.get(document_id, 0))

    # Sheets
    def create_sheet(
        self,
        session,
        *,
        name: str,
        parent_id: str,
        tab: str,
        columns: Sequence[str],
        validations: Mapping[str, Sequence[str]],
        properties: Mapping[str, str],
    ) -> str:
        sheet_id = f"sheet-{len(self.sheets) + 1}"
        self.sheets.append(DriveFile(id=sheet_id, name=name, properties={}))
        self.sheet_properties[sheet_id] = dict(properties)
        self.tabs[tab] = list(columns)
        self.tabs["validation"] = list(validations["Status"])
        return sheet_id

    def add_text_tab(
        self, session, spreadsheet_id: str, *, tab: str, lines: Sequence[str]
    ) -> None:
        assert tab not in self.tabs, f"tab {tab!r} already exists"
        self.tabs[tab] = list(lines)

    def tab_titles(self, session, spreadsheet_id: str) -> list[str]:
        return [tab for tab in self.tabs if tab != "validation"]

    def read_rows(self, session, spreadsheet_id: str, *, tab: str):
        assert (spreadsheet_id, tab) == (SHEET, cli.PAGES_TAB)
        return [dict(row) for row in self.rows.values()]

    def upsert_rows(
        self,
        session,
        spreadsheet_id: str,
        *,
        tab: str,
        key_column: str,
        rows: Sequence[Mapping[str, str]],
    ) -> None:
        assert (spreadsheet_id, tab, key_column) == (SHEET, cli.PAGES_TAB, "Page id")
        self.upserts.append([dict(row) for row in rows])
        for row in rows:
            self.rows.setdefault(row["Page id"], {}).update(row)

    # Test helpers
    def edit(self, doc_id: str, old: str, new: str) -> None:
        doc = self.docs[doc_id]
        assert old in doc.markdown
        doc.markdown = doc.markdown.replace(old, new)
        self.revisions[doc_id] = self.revisions.get(doc_id, 0) + 1


@dataclass
class MemoryStore:
    """A state store whose tip is the number of saves: `save-<n>`."""

    states: dict[str, PageState] = field(default_factory=dict)
    saves: list[str] = field(default_factory=list)
    save_error: Exception | None = None

    def load(self) -> dict[str, PageState]:
        return dict(self.states)

    def save(self, states: Mapping[str, PageState], *, message: str) -> None:
        if self.save_error is not None:
            raise self.save_error
        self.states = dict(states)
        self.saves.append(message)

    def tip(self) -> str | None:
        return f"save-{len(self.saves)}" if self.saves else None


@dataclass
class GitHub:
    """What gh reports: the open docsync pull requests and each closed or merged one."""

    open: dict[str, list[OpenPullRequest]] = field(default_factory=dict)
    done: dict[str, PullRequest] = field(default_factory=dict)
    listed: list[str] = field(default_factory=list)

    def open_pull_requests(self, repo: str) -> list[OpenPullRequest]:
        self.listed.append(repo)
        return self.open.get(repo, [])

    def pull_request(self, url: str) -> PullRequest:
        return self.done[url]

    def opened(self, repo: str, url: str, branch: str, paths: Sequence[str]) -> None:
        self.open.setdefault(repo, []).append(
            OpenPullRequest(url=url, branch=branch, files=frozenset(paths))
        )

    def finish(
        self, url: str, state: str, paths: Sequence[str], merge: str | None
    ) -> None:
        for items in self.open.values():
            items[:] = [item for item in items if item.url != url]
        self.done[url] = PullRequest(
            state=state, files=frozenset(paths), merge_commit=merge
        )


@dataclass
class Proposals:
    """Records each `propose_edits` call, with `files` as text and `built_on` beside it.

    Each proposal opens pull request number 7, 8, and so on, which `GitHub` then lists
    as open with the proposed paths.
    """

    github: GitHub
    calls: list[dict] = field(default_factory=list)
    raise_no_changes: bool = False
    error: Exception | None = None

    def __call__(self, **kwargs) -> str:
        files = kwargs["files"]
        self.calls.append(
            {
                **kwargs,
                "files": {path: file.text for path, file in files.items()},
                "built_on": {path: file.built_on for path, file in files.items()},
            }
        )
        if self.error is not None:
            raise self.error
        if self.raise_no_changes:
            raise NoChangesError("nothing")
        url = f"https://github.com/{kwargs['repo']}/pull/{6 + len(self.calls)}"
        self.github.opened(kwargs["repo"], url, kwargs["branch"], list(files))
        return url


class Source:
    """A git repository holding source pages, standing in for a fetched clone."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir()
        self.git("init", "-q", "-b", "dev")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def commit(self, path: str, text: str) -> str:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        self.git("add", path)
        self.git("commit", "-q", "-m", f"write {path}")
        return self.git("rev-parse", "HEAD")

    def page(self, page_id: str, path: str, *, title: str = "Call the API") -> SyncPage:
        commit = self.git("rev-parse", "HEAD")
        return SyncPage(
            page_id=page_id,
            title=title,
            section_path=("APIs", "Guide"),
            repo=REPO,
            ref="dev",
            commit=commit,
            path=path,
            text=self.git("show", f"{commit}:{path}") + "\n",
            clone_root=self.root,
        )


@dataclass
class World:
    google: FakeGoogle
    store: MemoryStore
    proposals: Proposals
    source: Source
    github: GitHub
    ctx: cli.Context

    def merge(
        self,
        url: str = PR_URL,
        *,
        texts: Mapping[str, str] | None = None,
        paths: Sequence[str] = ("docs/call.md",),
    ) -> str:
        """Merge pull request `url` as GitHub would; return the merge commit.

        `texts` (path to text) are committed onto the source, and the commit holding
        them is the merge commit. The pull request is reported MERGED with `paths`.
        """
        for path, text in (texts or {}).items():
            self.source.commit(path, text)
        merge = self.source.git("rev-parse", "HEAD")
        self.github.finish(url, "MERGED", paths, merge)
        return merge

    def close(self, url: str = PR_URL) -> None:
        self.github.finish(url, "CLOSED", ("docs/call.md",), None)

    def push(self, pages: Sequence[SyncPage], *, adopt: bool = False) -> cli.RunLog:
        log = cli.RunLog()
        cli.push(
            self.ctx, pages=pages, scope=pages, store=self.store, log=log, adopt=adopt
        )
        return log

    def pull(
        self, pages: Sequence[SyncPage], *, dry_run_dir: Path | None = None
    ) -> cli.RunLog:
        log = cli.RunLog()
        cli.pull(
            self.ctx, pages=pages, store=self.store, log=log, dry_run_dir=dry_run_dir
        )
        return log

    def status(self, page: SyncPage) -> str:
        return self.google.rows[page.page_id]["Status"]

    def set_status(self, page: SyncPage, status: str) -> None:
        self.google.rows[page.page_id]["Status"] = status


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    fake = FakeGoogle()
    fake.sheets.append(DriveFile(id=SHEET, name="tracker", properties={}))
    fake.sheet_properties[SHEET] = {"dfo_role": "tracking-sheet"}
    monkeypatch.setattr(cli, "google", fake)
    github = GitHub()
    proposals = Proposals(github)
    monkeypatch.setattr(cli, "propose_edits", proposals)
    source = Source(tmp_path / "dfo-apis")
    source.commit("docs/call.md", PAGE_TEXT)
    ctx = cli.Context(
        session=None,
        drive_id=DRIVE,
        folder_id=ROOT,
        sheet_id=SHEET,
        pull_request=github.pull_request,
        open_pull_requests=github.open_pull_requests,
        pr_author="app/dfo-bot",
        now="2026-10-01 09:00 UTC",
    )
    return World(fake, MemoryStore(), proposals, source, github, ctx)


def _page(world: World) -> SyncPage:
    return world.source.page("dfo-apis/call", "docs/call.md")


def _pushed_page(world: World) -> tuple[SyncPage, PageState]:
    page = _page(world)
    log = world.push([page])
    assert log.failures == 0
    return page, world.store.states[page.page_id]


def _ready(world: World, page: SyncPage, *, owner: str = "Ana") -> None:
    world.google.rows[page.page_id].update(
        {"Status": "Ready for review", "Owner": owner}
    )


def _sent(world: World) -> tuple[SyncPage, PageState]:
    """Push the page, edit its Doc, mark it Ready, and pull: PR 7 opens."""
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, "your token", "your API token")
    assert world.pull([page]).failures == 0
    assert world.store.states[page.page_id].pr_url == PR_URL
    return page, state


def _doc(world: World, page: SyncPage) -> str:
    return world.store.states[page.page_id].doc_id


# push


def test_first_push_creates_doc_records_state_and_adds_sheet_row(world: World):
    page, state = _pushed_page(world)

    (doc_id, doc), *others = world.google.docs.items()
    assert others == []
    assert doc.name == "Call the API"
    assert doc.parent == world.google.folders[("APIs", "Guide")]
    assert doc.properties == {"dfo_page_id": "dfo-apis/call", "dfo_root": ROOT}
    assert state == PageState(
        page_id="dfo-apis/call",
        doc_id=doc_id,
        repo=REPO,
        ref="dev",
        path="docs/call.md",
        source_commit=page.commit,
        baseline=doc.markdown.rstrip("\n"),
    )
    assert world.store.saves == ["docsync push: 1 pages"]
    assert world.google.rows["dfo-apis/call"] == {
        "Page id": "dfo-apis/call",
        "Title": "Call the API",
        "Section": "APIs / Guide",
        "Doc": f"https://docs.google.com/document/d/{doc_id}/edit",
        "PR": "",
        "Repo": REPO,
        "File": "docs/call.md",
        "Last pushed": "2026-10-01 09:00 UTC",
        "Status": "Not started",
    }


def test_unchanged_push_writes_nothing_but_script_columns(world: World):
    page, state = _pushed_page(world)
    world.set_status(page, "Editing")
    world.google.edit(state.doc_id, "your token", "your API token")

    log = world.push([page])

    assert log.failures == 0
    assert world.google.replaced == []
    assert world.store.saves == ["docsync push: 1 pages"]
    last = world.google.upserts[-1]
    assert [set(row) for row in last] == [
        {"Page id", "Title", "Section", "Doc", "PR", "Repo", "File"}
    ]
    assert world.status(page) == "Editing"


def test_push_replaces_unedited_doc_when_source_changed(world: World):
    page, state = _pushed_page(world)
    world.source.commit("docs/call.md", PAGE_TEXT.replace("JSON", "a JSON object"))
    page = _page(world)

    log = world.push([page])

    assert log.failures == 0
    assert world.google.replaced == [state.doc_id]
    new = world.store.states[page.page_id]
    assert new.source_commit == page.commit
    assert "a JSON object" in new.baseline


def test_push_holds_doc_edited_in_docs(world: World, capsys: pytest.CaptureFixture):
    page, state = _pushed_page(world)
    world.google.edit(state.doc_id, "your token", "your API token")
    world.source.commit("docs/call.md", PAGE_TEXT.replace("JSON", "a JSON object"))
    page = _page(world)

    log = world.push([page])

    assert log.failures == 0
    assert world.google.replaced == []
    assert world.store.states[page.page_id] == state
    assert (
        "not replaced: edited in Docs; set Status to Ready for review to send"
        in capsys.readouterr().out
    )


def test_push_ignores_export_differences_normalise_removes(world: World):
    page, state = _pushed_page(world)
    world.google.export_override[state.doc_id] = state.baseline.replace(
        "JSON.", "JSON\\."
    )
    world.source.commit("docs/call.md", PAGE_TEXT.replace("JSON", "a JSON object"))
    page = _page(world)

    log = world.push([page])

    assert log.failures == 0
    assert world.google.replaced == [state.doc_id]


def test_push_holds_doc_with_open_comments(world: World, capsys: pytest.CaptureFixture):
    page, state = _pushed_page(world)
    world.google.comments[state.doc_id] = [
        Comment(id="c1", content="Is this right?", author="Ana", quoted="token")
    ]
    world.source.commit("docs/call.md", PAGE_TEXT.replace("JSON", "a JSON object"))
    page = _page(world)

    log = world.push([page])

    assert log.failures == 0
    assert world.google.replaced == []
    assert "not replaced: 1 open comments" in capsys.readouterr().out


def test_gate_failure_on_one_page_reports_and_continues(
    world: World, capsys: pytest.CaptureFixture
):
    world.source.commit("docs/other.md", "# Other\n\nOther text.\n")
    bad = _page(world)
    good = world.source.page("dfo-apis/other", "docs/other.md", title="Other")
    world.google.export_override["doc-1"] = "# Something else entirely"

    log = world.push([bad, good])

    assert log.failures == 1
    assert set(world.store.states) == {"dfo-apis/other"}
    assert set(world.google.rows) == {"dfo-apis/other"}
    out = capsys.readouterr().out
    assert "dfo-apis/call: FAILED:" in out
    assert "Doc https://docs.google.com/document/d/doc-1/edit was trashed" in out
    assert world.google.trashed == ["doc-1"]


def test_doc_without_state_is_adopted_when_it_aligns(
    world: World, capsys: pytest.CaptureFixture
):
    page, state = _pushed_page(world)
    world.store.states.clear()

    log = world.push([page], adopt=True)

    assert log.failures == 0
    assert list(world.google.docs) == [state.doc_id]
    assert world.store.states[page.page_id] == state
    assert f"adopted https://docs.google.com/document/d/{state.doc_id}/edit" in (
        capsys.readouterr().out
    )


def test_docs_under_another_root_are_ignored(world: World):
    page = _page(world)
    world.google.docs["prod-doc"] = FakeDoc(
        "Call the API",
        "x",
        "elsewhere",
        {"dfo_page_id": "dfo-apis/call", "dfo_root": "production"},
    )

    log = world.push([page])

    assert log.failures == 0
    assert world.store.states[page.page_id].doc_id != "prod-doc"


def test_state_out_of_scope_is_reported_and_kept(
    world: World, capsys: pytest.CaptureFixture
):
    page, state = _pushed_page(world)
    stray = replace(state, page_id="dfo-apis/gone")
    world.store.states["dfo-apis/gone"] = stray
    world.source.commit("docs/call.md", PAGE_TEXT.replace("JSON", "a JSON object"))
    page = _page(world)

    world.push([page])

    assert world.store.states["dfo-apis/gone"] == stray
    assert "dfo-apis/gone: state for a page no longer in scope" in (
        capsys.readouterr().out
    )


def test_trashed_doc_is_recreated(world: World, capsys: pytest.CaptureFixture):
    page, state = _pushed_page(world)
    world.google.trash_file(None, state.doc_id)

    log = world.push([page])

    assert log.failures == 0
    new = world.store.states[page.page_id]
    assert new.doc_id != state.doc_id
    assert list(world.google.docs) == [new.doc_id]
    assert world.google.rows[page.page_id]["Doc"].endswith(f"/{new.doc_id}/edit")
    assert (
        f"Doc https://docs.google.com/document/d/{state.doc_id}/edit is in the trash"
        f" or gone; created https://docs.google.com/document/d/{new.doc_id}/edit"
    ) in capsys.readouterr().out


def test_trashed_doc_in_an_open_pr_is_held(world: World, capsys: pytest.CaptureFixture):
    page, state = _sent(world)
    world.google.trash_file(None, state.doc_id)

    log = world.push([page])

    assert log.failures == 0
    assert world.google.docs == {}
    assert world.store.states[page.page_id].doc_id == state.doc_id
    assert f"not replaced: in review at {PR_URL}" in capsys.readouterr().out


def test_discard_my_edits_replaces_an_edited_doc_with_comments(
    world: World, capsys: pytest.CaptureFixture
):
    page, state = _pushed_page(world)
    world.google.edit(state.doc_id, "your token", "your API token")
    world.google.comments[state.doc_id] = [
        Comment(id="c1", content="Is this right?", author="Ana", quoted="token")
    ]
    world.set_status(page, "Discard my edits")
    world.google.rows[page.page_id]["Notes"] = "Ask Ana first."

    log = world.push([page])

    assert log.failures == 0
    assert world.google.replaced == [state.doc_id]
    assert "your token" in world.google.docs[state.doc_id].markdown
    assert world.store.states[page.page_id].applied_export is None
    row = world.google.rows[page.page_id]
    assert (row["Status"], row["Not applied"], row["Notes"]) == (
        "Editing",
        "Edits discarded on 2026-10-01 09:00 UTC",
        "Ask Ana first.",
    )
    assert "discarded the edits in" in capsys.readouterr().out


def test_discard_whose_sheet_write_failed_is_not_repeated(
    world: World, monkeypatch: pytest.MonkeyPatch
):
    page, state = _pushed_page(world)
    world.google.edit(state.doc_id, "your token", "your API token")
    world.set_status(page, "Discard my edits")
    with monkeypatch.context() as patch:
        patch.setattr(world.google, "upsert_rows", _fail_sheet_write)
        with pytest.raises(GoogleApiError):
            world.push([page])
    assert world.google.replaced == [state.doc_id]
    assert world.store.states[page.page_id].discarded_on == "2026-10-01 09:00 UTC"
    assert world.status(page) == "Discard my edits"
    world.google.edit(state.doc_id, "Read the", "Now read the")

    assert world.push([page]).failures == 0

    assert world.google.replaced == [state.doc_id]
    assert "Now read the" in world.google.docs[state.doc_id].markdown
    assert world.status(page) == "Editing"

    assert world.push([page]).failures == 0

    assert world.store.states[page.page_id].discarded_on is None
    assert world.google.replaced == [state.doc_id]


def _fail_sheet_write(*args: object, **kwargs: object) -> None:
    raise GoogleApiError(status=503, message="Backend Error", method="POST", url="")


@pytest.mark.parametrize("blocker", ["suggestion", "open PR"])
def test_discard_my_edits_holds_while_a_suggestion_or_pr_is_open(
    world: World, blocker: str
):
    if blocker == "open PR":
        page, state = _sent(world)
    else:
        page, state = _pushed_page(world)
        world.google.edit(state.doc_id, "your token", "your API token")
        world.google.suggestions[state.doc_id] = frozenset({"suggest.1"})
    world.set_status(page, "Discard my edits")

    assert world.push([page]).failures == 0

    assert world.google.replaced == []
    assert world.status(page) == "Discard my edits"


# pull


def test_pull_opens_pr_and_records_it(world: World):
    page, state = _sent(world)

    (call,) = world.proposals.calls
    assert call["repo"] == REPO
    assert call["base"] == "dev"
    assert call["branch"].startswith("docsync/edits-")
    assert call["clone_root"] == world.source.root
    assert call["dry_run_dir"] is None
    assert call["files"] == {
        "docs/call.md": PAGE_TEXT.replace("your token", "your API token")
    }
    assert call["built_on"] == {"docs/call.md": page.commit}
    doc_url = f"https://docs.google.com/document/d/{state.doc_id}/edit"
    assert f"[Google Doc]({doc_url}) · Owner: `Ana`" in call["body"]
    new = world.store.states[page.page_id]
    assert new == replace(
        state,
        pulled_export=world.google.export_markdown(None, state.doc_id),
        pr_url=PR_URL,
    )
    row = world.google.rows[page.page_id]
    assert (row["Status"], row["PR"], row["Last pulled"], row["Not applied"]) == (
        "PR open",
        PR_URL,
        "2026-10-01 09:00 UTC",
        "",
    )


def test_pull_neutralises_sheet_text_in_the_pr_body(world: World):
    page, state = _pushed_page(world)
    _ready(world, page, owner="Ana @ONEcampaign/everyone\nCloses #42\n## Approved")
    world.google.edit(state.doc_id, "your token", "your API token")

    world.pull([page])

    body = world.proposals.calls[0]["body"]
    assert "@ONEcampaign" not in body
    assert "#42" not in body
    assert "\n## Approved" not in body
    wj = "\u2060"
    assert (
        f"Owner: `Ana @{wj}ONEcampaign/everyone C{wj}loses #{wj}42 #{wj}#{wj} Approved`"
        in body
    )


def test_pull_fails_the_repo_when_its_base_moved(
    world: World, capsys: pytest.CaptureFixture
):
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, "your token", "your API token")
    world.proposals.error = StaleBaseError(base="dev", paths=["docs/call.md"])

    log = world.pull([page])

    assert log.failures == 1
    assert world.store.states[page.page_id] == state
    assert world.status(page) == "Ready for review"
    assert "dev changed docs/call.md after this run read them" in (
        capsys.readouterr().out
    )


def test_pull_skips_rows_not_ready(world: World):
    page, state = _pushed_page(world)
    world.google.edit(state.doc_id, "your token", "your API token")

    world.pull([page])

    assert world.proposals.calls == []


def test_pull_hub_pages_target_main(world: World):
    page, state = _pushed_page(world)
    hub = replace(page, page_id="hub/call", repo="ONEcampaign/dfo-docs", ref="feat")
    world.store.states["hub/call"] = replace(state, page_id="hub/call")
    world.google.rows["hub/call"] = {
        "Page id": "hub/call",
        "Status": "Ready for review",
    }
    world.google.edit(state.doc_id, "your token", "your API token")

    world.pull([hub])

    assert world.proposals.calls[0]["base"] == "main"


def test_pull_refuses_doc_with_open_suggestions(
    world: World, capsys: pytest.CaptureFixture
):
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, "your token", "your API token")
    world.google.suggestions[state.doc_id] = frozenset({"suggest.1"})

    log = world.pull([page])

    assert log.failures == 0
    assert world.proposals.calls == []
    assert world.status(page) == "Ready for review"
    assert "open suggestions" in capsys.readouterr().out


def test_pull_reports_clash_with_upstream(world: World):
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, "your token", "your API token")
    world.source.commit(
        "docs/call.md", PAGE_TEXT.replace("your token", "your bearer token")
    )
    page = _page(world)

    world.pull([page])

    (call,) = world.proposals.calls
    assert "Send a request with your API token." in call["files"]["docs/call.md"]
    assert "Flagged clash 1." in call["body"]
    assert "Send a request with your bearer token." in call["body"]


def test_pull_merges_edits_to_different_words_of_one_line(world: World):
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, "your token", "your API token")
    world.source.commit(
        "docs/call.md", PAGE_TEXT.replace("your token", "a bearer token")
    )
    page = _page(world)

    world.pull([page])

    (call,) = world.proposals.calls
    assert "Send a request with a bearer API token." in call["files"]["docs/call.md"]
    assert "Flagged clash" not in call["body"]


def test_pull_of_an_unedited_ready_doc_sets_editing_and_keeps_state(world: World):
    page, state = _pushed_page(world)
    _ready(world, page)
    saves = len(world.store.saves)

    log = world.pull([page])

    assert log.failures == 0
    assert world.proposals.calls == []
    assert world.store.states[page.page_id] == state
    assert len(world.store.saves) == saves
    row = world.google.rows[page.page_id]
    assert (row["Status"], row["Not applied"]) == ("Editing", cli.NOTHING_TO_SEND)


def test_ready_set_while_the_pr_is_open_with_no_newer_edits_ends_merged(
    world: World,
):
    page, state = _sent(world)
    _ready(world, page)
    world.merge(
        texts={"docs/call.md": PAGE_TEXT.replace("your token", "your API token")}
    )
    page = _page(world)

    assert world.pull([page]).failures == 0

    assert len(world.proposals.calls) == 1
    row = world.google.rows[page.page_id]
    assert (row["Status"], row["PR"], row["Not applied"]) == (
        "Merged",
        "",
        cli.NOTHING_TO_SEND,
    )
    settled = world.store.states[page.page_id]
    assert settled.pr_url is None
    assert settled.applied_export == world.google.export_markdown(None, state.doc_id)

    # The next day nothing changes: the page is not Ready, so pull reads nothing.
    assert world.push([page]).failures == 0
    assert world.pull([page]).failures == 0
    assert len(world.proposals.calls) == 1
    assert world.status(page) == "Merged"


def test_pull_whose_edits_are_already_upstream_records_them_applied(world: World):
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, "your token", "your API token")
    world.source.commit(
        "docs/call.md", PAGE_TEXT.replace("your token", "your API token")
    )
    page = _page(world)

    assert world.pull([page]).failures == 0

    assert world.proposals.calls == []
    new = world.store.states[page.page_id]
    assert new.applied_export == world.google.export_markdown(None, state.doc_id)
    assert new.pr_url is None
    row = world.google.rows[page.page_id]
    assert row["Status"] == "Editing"
    assert row["Not applied"] == ("Nothing to send: these edits are already in GitHub")

    assert world.push([page]).failures == 0
    assert world.google.replaced == [state.doc_id]
    assert world.store.states[page.page_id].applied_export is None


def test_pull_sends_nothing_when_the_merged_file_cannot_be_read(
    world: World, monkeypatch: pytest.MonkeyPatch
):
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, "your token", "your API token")
    unreadable = MergeResult(text="# Call the API\n\n<div>raw</div>\n", clashes=())
    monkeypatch.setattr(cli, "merge_onto_current", lambda **_: unreadable)

    log = world.pull([page])

    assert log.failures == 1
    assert world.proposals.calls == []
    new = world.store.states[page.page_id]
    assert new == state
    assert new.applied_export is None
    row = world.google.rows[page.page_id]
    assert row["Status"] == "Editing"
    assert row["Not applied"].startswith(
        "the edits would leave a file docsync cannot read: "
    )
    assert "raw HTML" in row["Not applied"]
    assert "; nothing sent | " in row["Not applied"]
    assert "The Doc has:" not in row["Not applied"]
    assert row["Not applied"].endswith(cli.HOLD_ADVICE)

    assert world.push([page]).failures == 0
    assert world.google.replaced == []
    assert "your API token" in world.google.docs[state.doc_id].markdown


NOTE_PAGE = PAGE_TEXT.replace(
    "Read the response", "<!-- TODO: add the rate limit. -->\n\nRead the response"
)


def test_an_applied_report_is_not_repeated_in_the_next_pr_but_a_refusal_is(
    world: World,
):
    world.source.commit("docs/call.md", NOTE_PAGE)
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, "**Author note:** TODO", "TODO")
    world.google.edit(state.doc_id, "# Call the API", "## Call the API")
    assert world.pull([page]).failures == 0
    (first,) = world.proposals.calls
    assert "an Author note became page text" in first["body"]
    assert "heading level 1 became 2" in first["body"]

    world.merge(texts={"docs/call.md": first["files"]["docs/call.md"]})
    page = _page(world)
    world.google.edit(state.doc_id, "Read the response", "Read the reply")
    _ready(world, page)
    assert world.pull([page]).failures == 0

    first, second = world.proposals.calls
    assert "Read the reply" in second["files"]["docs/call.md"]
    assert "an Author note became page text" not in second["body"]
    assert "heading level 1 became 2" in second["body"]


TWO_NOTES_PAGE = PAGE_TEXT.replace(
    "Read the response",
    "<!-- TODO: one. -->\n\n<!-- TODO: two. -->\n\nRead the response",
)


def test_a_second_note_unlabelled_after_the_first_merged_is_flagged_again(
    world: World,
):
    world.source.commit("docs/call.md", TWO_NOTES_PAGE)
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, "**Author note:** TODO: one.", "TODO: one.")
    assert world.pull([page]).failures == 0
    (first,) = world.proposals.calls
    assert first["body"].count("an Author note became page text") == 1

    world.merge(texts={"docs/call.md": first["files"]["docs/call.md"]})
    page = _page(world)
    world.google.edit(state.doc_id, "**Author note:** TODO: two.", "TODO: two.")
    _ready(world, page)
    assert world.pull([page]).failures == 0

    _, second = world.proposals.calls
    assert second["body"].count("an Author note became page text") == 1
    assert "\nTODO: two." in second["files"]["docs/call.md"]
    assert "<!-- TODO: two. -->" not in second["files"]["docs/call.md"]


def test_a_note_flag_is_not_hidden_by_the_flag_of_another_note_already_carried(
    world: World,
):
    world.source.commit("docs/call.md", TWO_NOTES_PAGE)
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, "**Author note:** TODO: one.", "TODO: one.")
    assert world.pull([page]).failures == 0
    (first,) = world.proposals.calls
    world.merge(texts={"docs/call.md": first["files"]["docs/call.md"]})
    page = _page(world)

    # The editor puts note one's label back and unlabels note two instead.
    world.google.edit(state.doc_id, "TODO: one.", "**Author note:** TODO: one.")
    world.google.edit(state.doc_id, "**Author note:** TODO: two.", "TODO: two.")
    _ready(world, page)
    assert world.pull([page]).failures == 0

    _, second = world.proposals.calls
    assert second["body"].count("an Author note became page text") == 1


JOINED_NOTE = (
    "your token.\n\n\n**Author note:**",
    "your token. **Author note:**",
)
JOINED_TEXT = (
    "Send a request with your token. **Author note:** TODO: add the rate limit."
)
JOIN_REFUSAL = (
    "the Author note label is not at the start of a paragraph;"
    " this part of the page is not changed"
)


def test_a_refused_edit_holds_the_doc_and_the_not_applied_column_quotes_it(
    world: World, capsys: pytest.CaptureFixture
):
    world.source.commit("docs/call.md", NOTE_PAGE)
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, *JOINED_NOTE)

    assert world.pull([page]).failures == 0

    assert world.proposals.calls == []
    assert world.store.states[page.page_id] == state
    row = world.google.rows[page.page_id]
    assert row["Status"] == "Editing"
    assert row["Not applied"] == (
        f"{JOIN_REFUSAL}\nThe Doc has:\n{JOINED_TEXT} | {cli.HOLD_ADVICE}"
    )
    assert 'set Status to "Discard my edits"' in row["Not applied"]

    # The Doc keeps the editor's text, with the source unchanged or moved on.
    assert world.push([page]).failures == 0
    world.source.commit("docs/call.md", NOTE_PAGE.replace("JSON", "XML"))
    assert world.push([_page(world)]).failures == 0
    assert world.google.replaced == []
    assert JOINED_TEXT in world.google.docs[state.doc_id].markdown
    assert "edited in Docs" in capsys.readouterr().out


CALLOUT_PAGE = PAGE_TEXT.replace("Send a request", "!!! note\n    Send a request")


def test_a_refused_region_keeps_the_text_an_earlier_pr_merged(world: World):
    world.source.commit("docs/call.md", CALLOUT_PAGE)
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, "Read the response", "Read the reply")
    assert world.pull([page]).failures == 0
    (first,) = world.proposals.calls
    assert "Read the reply" in first["files"]["docs/call.md"]
    world.merge(texts={"docs/call.md": first["files"]["docs/call.md"]})

    # No push replaces the Doc, so the page keeps its first source and baseline.
    # Removing the callout's label puts the merged paragraph beside it in a
    # refused region, which must not read as an edit back to the pushed text.
    page = _page(world)
    world.google.edit(state.doc_id, "> **Note:** Send", "> Send")
    _ready(world, page)
    assert world.pull([page]).failures == 0

    assert len(world.proposals.calls) == 1
    row = world.google.rows[page.page_id]
    assert row["Status"] == "Editing"
    assert "the Note label was removed or changed" in row["Not applied"]


def test_a_refusal_quote_is_cut_to_fit_the_not_applied_cell(world: World):
    long_note = "TODO: " + "word " * 12_000 + "end."
    world.source.commit(
        "docs/call.md", NOTE_PAGE.replace("TODO: add the rate limit.", long_note)
    )
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, *JOINED_NOTE)

    assert world.pull([page]).failures == 0

    cell = world.google.rows[page.page_id]["Not applied"]
    assert len(cell) <= cli.NOT_APPLIED_LIMIT
    assert cell.startswith(f"{JOIN_REFUSAL}\nThe Doc has:\nSend a request with")
    assert "word word word" in cell
    assert "end." not in cell
    shortened = (
        "\n(Shortened here. The full text was in the Doc when this pull ran.) | "
    )
    assert shortened + cli.HOLD_ADVICE in cell
    assert world.google.docs[state.doc_id].markdown.count("end.") == 1


def test_a_refused_edit_does_not_stop_the_pr_for_the_page_s_other_edits(
    world: World,
):
    world.source.commit("docs/call.md", NOTE_PAGE + "\nCheck the status code.\n")
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, *JOINED_NOTE)
    world.google.edit(state.doc_id, "Check the status", "Check the HTTP status")

    assert world.pull([page]).failures == 0

    (call,) = world.proposals.calls
    assert "Check the HTTP status code." in call["files"]["docs/call.md"]
    assert "<!-- TODO: add the rate limit. -->" in call["files"]["docs/call.md"]
    assert f"**Not applied.** `{JOIN_REFUSAL}`" in call["body"]
    assert f"The Doc has:\n\n```text\n{JOINED_TEXT}" in call["body"]
    row = world.google.rows[page.page_id]
    assert (row["Status"], row["Not applied"]) == ("PR open", "")
    assert world.store.states[page.page_id].pr_url == PR_URL


def test_pull_refuses_a_page_an_open_pr_carries_that_state_does_not_name(
    world: World, capsys: pytest.CaptureFixture
):
    page, state = _sent(world)
    # The save after `gh pr create` failed, so the state still lacks the PR.
    world.store.states[page.page_id] = state
    world.set_status(page, "Ready for review")

    log = world.pull([page])

    assert log.failures == 1
    assert len(world.proposals.calls) == 1
    assert world.store.states[page.page_id] == state
    assert (
        f"dfo-apis/call: FAILED: docs/call.md is changed in open PR {PR_URL}; merge"
        " or close that PR, or revert the file on its branch, before sending this"
        " page"
    ) in capsys.readouterr().out


def test_a_reviewer_commit_touching_another_page_fails_it_only_when_ready(
    world: World, capsys: pytest.CaptureFixture
):
    world.source.commit("docs/other.md", "# Other\n\nOther text.\n")
    call = world.source.page("dfo-apis/call", "docs/call.md")
    other = world.source.page("dfo-apis/other", "docs/other.md", title="Other")
    world.push([call, other])
    _ready(world, other)
    world.google.edit(_doc(world, other), "Other text", "Other words")
    assert world.pull([call, other]).failures == 0
    (pr,) = world.github.open[REPO]
    # A reviewer commits a fix to docs/call.md on the other page's PR branch.
    world.github.open[REPO] = [replace(pr, files=pr.files | {"docs/call.md"})]
    world.google.edit(_doc(world, call), "your token", "your API token")
    capsys.readouterr()

    assert world.pull([call, other]).failures == 0

    _ready(world, call)
    log = world.pull([call, other])

    assert log.failures == 1
    assert len(world.proposals.calls) == 1
    out = capsys.readouterr().out
    assert f"dfo-apis/call: FAILED: docs/call.md is changed in open PR {pr.url}" in out
    assert "restore state" not in out
    assert f"dfo-apis/other: not pulled: in review at {pr.url}" in out


def test_a_reopened_pr_fails_its_ready_page_with_the_remedy(
    world: World, capsys: pytest.CaptureFixture
):
    page, _ = _sent(world)
    world.close()
    assert world.push([page]).failures == 0
    world.github.opened(REPO, PR_URL, "docsync/edits-x", ["docs/call.md"])
    world.set_status(page, "Ready for review")
    capsys.readouterr()

    assert world.pull([page]).failures == 1

    assert (
        f"docs/call.md is changed in open PR {PR_URL}; merge or close that PR"
        in capsys.readouterr().out
    )


def test_pull_opens_one_pr_per_repo_for_every_ready_page(world: World):
    world.source.commit("docs/a.md", "# Page A\n\nAlpha paragraph.\n")
    world.source.commit("docs/b.md", "# Page B\n\nBeta paragraph.\n")
    a = world.source.page("dfo-apis/a", "docs/a.md", title="A")
    b = world.source.page("dfo-apis/b", "docs/b.md", title="B")
    assert world.push([a, b]).failures == 0
    world.google.edit(_doc(world, a), "Alpha paragraph.", "Alpha paragraph, edited.")
    world.google.edit(_doc(world, b), "Beta paragraph.", "Beta paragraph, edited.")
    for page in (a, b):
        world.set_status(page, "Ready for review")

    assert world.pull([a, b]).failures == 0

    (call,) = world.proposals.calls
    assert set(call["files"]) == {"docs/a.md", "docs/b.md"}
    assert {world.store.states[p.page_id].pr_url for p in (a, b)} == {PR_URL}


def test_dry_run_writes_files_and_no_state_or_sheet(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(cli, "propose_edits", propose_edits)
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, "your token", "your API token")
    upserts = len(world.google.upserts)
    out = tmp_path / "dry"

    log = world.pull([page], dry_run_dir=out)

    assert log.failures == 0
    written = out / "ONEcampaign__dfo-apis" / "files" / "docs" / "call.md"
    assert written.read_text() == PAGE_TEXT.replace("your token", "your API token")
    assert "Owner: `Ana`" in (out / "ONEcampaign__dfo-apis" / "pr.md").read_text()
    assert world.store.states[page.page_id] == state
    assert world.store.saves == ["docsync push: 1 pages"]
    assert len(world.google.upserts) == upserts
    assert world.source.git("status", "--porcelain") == ""


def test_dry_run_settles_in_memory_and_saves_nothing(world: World, tmp_path: Path):
    page, _ = _sent(world)
    world.close()
    before = dict(world.store.states)
    upserts = len(world.google.upserts)

    assert world.pull([page], dry_run_dir=tmp_path / "dry").failures == 0

    assert world.store.states == before
    assert len(world.google.upserts) == upserts
    assert world.status(page) == "PR open"


# Edits pull cannot apply

FENCE_PAGE = "# Page\n\nRun this:\n\n```bash\necho hello\n```\n\nThen go on.\n"


def test_reports_only_pull_sets_editing_and_push_refreshes_the_doc(world: World):
    world.source.commit("docs/p.md", FENCE_PAGE)
    page = world.source.page("dfo-apis/p", "docs/p.md", title="P")
    world.push([page])
    doc_id = _doc(world, page)
    world.google.edit(doc_id, "echo hello", "echo goodbye")
    _ready(world, page)
    world.google.rows[page.page_id]["Notes"] = "Ask Ana first."

    assert world.pull([page]).failures == 0

    assert world.proposals.calls == []
    state = world.store.states[page.page_id]
    assert state.pr_url is None
    assert state.applied_export is not None
    assert "echo goodbye" in state.applied_export
    row = world.google.rows[page.page_id]
    assert "code edits are not applied" in row["Not applied"]
    assert row["Status"] == "Editing"

    # The source has not moved; push still shows the Doc what the source holds.
    assert world.push([page]).failures == 0

    assert world.google.replaced == [doc_id]
    new = world.store.states[page.page_id]
    assert (new.applied_export, new.source_commit) == (None, page.commit)
    assert "echo hello" in world.google.docs[doc_id].markdown
    assert "code edits are not applied" in row["Not applied"]
    assert row["Notes"] == "Ask Ana first."
    assert all(
        "Notes" not in written for rows in world.google.upserts for written in rows
    )

    assert world.push([page]).failures == 0
    assert world.pull([page]).failures == 0
    assert world.google.replaced == [doc_id]


# The pull request lifecycle

REVIEWED = PAGE_TEXT.replace("your token", "your API token").replace(
    "Read the response as JSON.", "Read the response body as JSON."
)


def test_open_pr_is_never_rewritten_and_holds_the_page(
    world: World, capsys: pytest.CaptureFixture
):
    page, state = _sent(world)
    world.google.edit(state.doc_id, "Read the response", "Then read the response")
    world.source.commit("docs/other.md", "unrelated\n")
    page = _page(world)

    assert world.pull([page]).failures == 0
    assert world.push([page]).failures == 0

    assert len(world.proposals.calls) == 1
    assert world.google.replaced == []
    assert world.store.states[page.page_id].pr_url == PR_URL
    out = capsys.readouterr().out
    assert f"not pulled: in review at {PR_URL}" in out
    assert f"not replaced: in review at {PR_URL}" in out


def test_merge_waits_until_the_ref_holds_it(
    world: World, capsys: pytest.CaptureFixture
):
    page, _ = _sent(world)
    merge = world.merge(texts={"docs/call.md": REVIEWED})
    pulled = world.store.states[page.page_id]

    # `page` was read before the merge landed in dev.
    assert world.pull([page]).failures == 0
    assert world.push([page]).failures == 0

    assert world.store.states[page.page_id] == pulled
    assert world.google.replaced == []
    assert world.status(page) == "PR open"
    assert (
        capsys.readouterr().out.count(
            f"{PR_URL} merged; waiting for dev to include {merge[:12]}"
        )
        == 2
    )


@pytest.mark.parametrize("merge_known", [True, False])
def test_discard_releases_a_merge_the_ref_never_holds(
    world: World, capsys: pytest.CaptureFixture, merge_known: bool
):
    page, state = _sent(world)
    if merge_known:
        # The PR was retargeted and merged into another branch of the clone.
        world.source.git("checkout", "-q", "-b", "other")
        merge = world.source.commit(
            "docs/call.md", PAGE_TEXT.replace("your token", "your API token")
        )
        world.source.git("checkout", "-q", "dev")
    else:
        merge = "0123456789" * 4
    world.github.finish(PR_URL, "MERGED", ["docs/call.md"], merge)
    world.set_status(page, "Discard my edits")
    page = _page(world)

    assert world.push([page]).failures == 0

    new = world.store.states[page.page_id]
    assert (new.pr_url, new.pulled_export, new.applied_export) == (None, None, None)
    assert world.google.replaced == [state.doc_id]
    assert "your token" in world.google.docs[state.doc_id].markdown
    row = world.google.rows[page.page_id]
    assert (row["Status"], row["PR"], row["Not applied"]) == (
        "Editing",
        "",
        f"PR {PR_URL} merged into a branch this page is not read from; edits"
        " discarded | Edits discarded on 2026-10-01 09:00 UTC",
    )
    assert "waiting for" not in capsys.readouterr().out


def test_merge_the_clone_cannot_resolve_fails_the_page(world: World):
    page, _ = _sent(world)
    world.github.finish(PR_URL, "MERGED", ("docs/call.md",), "0123456789" * 4)

    assert world.push([page]).failures == 1
    assert world.pull([page]).failures == 1
    assert world.store.states[page.page_id].pr_url == PR_URL


def test_merged_pr_with_a_reviewer_commit_settles_and_push_refreshes_the_doc(
    world: World,
):
    page, state = _sent(world)
    world.merge(texts={"docs/call.md": REVIEWED})
    page = _page(world)

    assert world.push([page]).failures == 0

    assert world.status(page) == "Merged"
    assert world.google.replaced == [state.doc_id]
    assert "response body" in world.google.docs[state.doc_id].markdown
    new = world.store.states[page.page_id]
    assert (new.pr_url, new.pulled_export, new.applied_export) == (None, None, None)
    assert new.source_commit == page.commit
    row = world.google.rows[page.page_id]
    assert (row["PR"], row["Not applied"]) == ("", "")

    world.set_status(page, "Ready for review")
    assert world.pull([page]).failures == 0
    assert len(world.proposals.calls) == 1


def test_later_edits_go_in_a_second_pr_built_on_the_merged_text(
    world: World, capsys: pytest.CaptureFixture
):
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, "your token", "your API tokn")
    assert world.pull([page]).failures == 0
    # The editor keeps editing; a reviewer fixes the typo on the PR and merges it.
    world.google.edit(state.doc_id, "# Call the API", "# Call the DFO API")
    merge = world.merge(
        texts={"docs/call.md": PAGE_TEXT.replace("your token", "your API token")}
    )

    # The page was read before dev held the merge, so both commands wait.
    assert world.pull([page]).failures == 0
    assert world.push([page]).failures == 0
    assert world.status(page) == "PR open"
    assert f"{PR_URL} merged; waiting for dev to include {merge[:12]}" in (
        capsys.readouterr().out
    )

    page = _page(world)
    assert world.pull([page]).failures == 0
    assert world.push([page]).failures == 0

    row = world.google.rows[page.page_id]
    assert (row["Status"], row["PR"]) == ("Editing", "")
    assert row["Not applied"] == (
        f"PR {PR_URL} merged; later edits in this Doc go in the next PR"
    )
    assert world.google.replaced == []
    assert len(world.proposals.calls) == 1
    assert (
        "not replaced: edited in Docs; set Status to Ready for review to send"
        in capsys.readouterr().out
    )

    world.set_status(page, "Ready for review")
    assert world.pull([page]).failures == 0

    second = world.proposals.calls[-1]["files"]["docs/call.md"]
    assert second == PAGE_TEXT.replace("your token", "your API token").replace(
        "# Call the API", "# Call the DFO API"
    )
    assert world.store.states[page.page_id].pr_url == PR_URL_2
    assert (world.status(page), world.google.rows[page.page_id]["Not applied"]) == (
        "PR open",
        "",
    )

    world.merge(PR_URL_2, texts={"docs/call.md": second})
    page = _page(world)
    assert world.push([page]).failures == 0

    assert world.status(page) == "Merged"
    assert world.google.replaced == [state.doc_id]
    assert "# Call the DFO API" in world.google.docs[state.doc_id].markdown
    assert "your API token" in world.google.docs[state.doc_id].markdown


def test_ready_set_while_the_pr_is_open_sends_after_the_merge(world: World):
    page, state = _sent(world)
    world.google.edit(state.doc_id, "Read the response", "Then read the response")
    world.set_status(page, "Ready for review")

    assert world.pull([page]).failures == 0
    assert len(world.proposals.calls) == 1
    assert world.status(page) == "Ready for review"

    world.merge(
        texts={"docs/call.md": PAGE_TEXT.replace("your token", "your API token")}
    )
    page = _page(world)
    assert world.pull([page]).failures == 0

    assert len(world.proposals.calls) == 2
    assert world.proposals.calls[-1]["files"]["docs/call.md"] == PAGE_TEXT.replace(
        "your token", "your API token"
    ).replace("Read the response", "Then read the response")
    assert world.store.states[page.page_id].pr_url == PR_URL_2
    assert world.status(page) == "PR open"


def test_closed_pr_returns_the_page_to_editing(
    world: World, capsys: pytest.CaptureFixture
):
    page, state = _sent(world)
    world.close()

    assert world.pull([page]).failures == 0

    assert len(world.proposals.calls) == 1
    new = world.store.states[page.page_id]
    assert new == state
    row = world.google.rows[page.page_id]
    assert (row["Status"], row["PR"], row["Not applied"]) == (
        "Editing",
        "",
        f"PR {PR_URL} closed without merging this page",
    )

    world.source.commit("docs/other.md", "unrelated\n")
    world.source.commit("docs/call.md", PAGE_TEXT + "\nUpstream paragraph.\n")
    page = _page(world)
    assert world.push([page]).failures == 0
    assert world.google.replaced == []
    assert (
        "not replaced: edited in Docs; set Status to Ready for review to send"
        in capsys.readouterr().out
    )

    world.set_status(page, "Ready for review")
    assert world.pull([page]).failures == 0
    assert len(world.proposals.calls) == 2
    assert world.store.states[page.page_id].pr_url == PR_URL_2


def test_closed_pr_returns_a_ready_page_to_editing_without_resending(world: World):
    page, _ = _sent(world)
    _ready(world, page)
    world.close()

    assert world.pull([page]).failures == 0

    assert len(world.proposals.calls) == 1
    row = world.google.rows[page.page_id]
    assert (row["Status"], row["PR"], row["Not applied"]) == (
        "Editing",
        "",
        f"PR {PR_URL} closed without merging this page",
    )


def test_closed_pr_keeps_discard_my_edits_and_push_discards(world: World):
    page, state = _sent(world)
    world.set_status(page, "Discard my edits")
    world.close()

    assert world.pull([page]).failures == 0
    assert world.status(page) == "Discard my edits"
    assert world.push([page]).failures == 0

    assert world.google.replaced == [state.doc_id]
    assert "your token" in world.google.docs[state.doc_id].markdown
    row = world.google.rows[page.page_id]
    assert (row["Status"], row["Not applied"]) == (
        "Editing",
        "Edits discarded on 2026-10-01 09:00 UTC",
    )


def test_merged_pr_without_the_page_returns_it_to_editing(world: World):
    page, state = _sent(world)
    world.merge(texts={"docs/other.md": "unrelated\n"}, paths=("docs/other.md",))
    page = _page(world)

    assert world.push([page]).failures == 0

    assert world.store.states[page.page_id] == state
    assert world.google.replaced == []
    row = world.google.rows[page.page_id]
    assert (row["Status"], row["Not applied"]) == (
        "Editing",
        f"PR {PR_URL} closed without merging this page",
    )


def test_push_holds_a_doc_whose_merged_edit_the_editor_undid(world: World):
    page, state = _sent(world)
    world.google.edit(state.doc_id, "your API token", "your token")
    world.merge(
        texts={"docs/call.md": PAGE_TEXT.replace("your token", "your API token")}
    )
    page = _page(world)

    assert world.push([page]).failures == 0

    assert world.google.replaced == []
    assert world.status(page) == "Editing"
    assert world.store.states[page.page_id].applied_export is not None

    world.set_status(page, "Ready for review")
    assert world.pull([page]).failures == 0
    assert world.proposals.calls[-1]["files"]["docs/call.md"] == PAGE_TEXT


# init, sheet lookup, credentials, page selection


def test_init_creates_tagged_sheet_once(world: World):
    world.google.sheets.clear()

    sheet_id = cli.init(None, drive_id=DRIVE, folder_id=ROOT)
    again = cli.init(None, drive_id=DRIVE, folder_id=ROOT)

    assert sheet_id == again
    assert len(world.google.sheets) == 1
    assert world.google.sheet_properties[sheet_id] == {"dfo_role": "tracking-sheet"}
    assert world.google.tabs["Pages"] == list(cli.COLUMNS)
    assert world.google.tabs["validation"] == [
        "Not started",
        "Editing",
        "Ready for review",
        "PR open",
        "Merged",
        "Discard my edits",
    ]
    assert world.google.tabs["How to edit"]


def test_init_ignores_untagged_sheet_from_an_interrupted_run(world: World):
    world.google.sheets.clear()
    world.google.sheets.append(DriveFile(id="half", name="tracker", properties={}))

    sheet_id = cli.init(None, drive_id=DRIVE, folder_id=ROOT)

    assert sheet_id != "half"


def test_find_sheet_refuses_missing_and_duplicate(world: World):
    world.google.sheets.clear()
    with pytest.raises(cli.MissingSheetError, match="dfo-docsync init"):
        cli.find_sheet(None, drive_id=DRIVE, folder_id=ROOT)

    for sheet_id in ("a", "b"):
        world.google.sheets.append(DriveFile(id=sheet_id, name="t", properties={}))
        world.google.sheet_properties[sheet_id] = {"dfo_role": "tracking-sheet"}
    with pytest.raises(cli.DuplicateSheetError):
        cli.find_sheet(None, drive_id=DRIVE, folder_id=ROOT)


def test_missing_credentials_is_a_named_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(cli.ACCESS_TOKEN_ENV, raising=False)

    class NoAdc:
        def default_session(self):
            raise DefaultCredentialsError("no ADC")

    monkeypatch.setattr(cli, "google", NoAdc())
    with pytest.raises(cli.MissingCredentialsError, match=cli.ACCESS_TOKEN_ENV):
        cli.open_session()


def test_access_token_wraps_as_user_credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(cli.ACCESS_TOKEN_ENV, "ya29.token")

    session = cli.open_session()

    assert session.credentials.token == "ya29.token"


def test_main_exits_2_on_missing_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    config = tmp_path / "docsync.yaml"
    config.write_text("sources: [hub]\ndrive_folder_id: nope\npr_author: app/dfo-bot\n")
    monkeypatch.setenv(cli.ACCESS_TOKEN_ENV, "ya29.token")

    class NoFolder:
        def get_drive_id(self, session, file_id):
            raise cli.GoogleApiError(
                status=404, message="File not found", method="GET", url="u"
            )

    monkeypatch.setattr(cli, "google", NoFolder())

    assert cli.main(["push", "--config", str(config)]) == 2
    assert "MissingFolderError" in capsys.readouterr().err


def test_select_pages_refuses_unknown_page(world: World):
    page = _page(world)
    assert cli.select_pages([page], []) == [page]
    assert cli.select_pages([page], ["dfo-apis/call"]) == [page]
    with pytest.raises(cli.UnknownPageError, match="dfo-apis/nope"):
        cli.select_pages([page], ["dfo-apis/nope"])


# Push guards

STRUCTURE_PAGE = "# Page\n\n## Section\n\nFirst paragraph.\n\nSecond paragraph.\n"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("## Section", "### Section"),
        ("Second paragraph.", "- Second paragraph."),
        ("Second paragraph.", "> Second paragraph."),
    ],
)
def test_push_holds_doc_with_structural_edit(
    world: World, capsys: pytest.CaptureFixture, old: str, new: str
):
    world.source.commit("docs/p.md", STRUCTURE_PAGE)
    page = world.source.page("dfo-apis/p", "docs/p.md", title="P")
    world.push([page])
    world.google.edit(_doc(world, page), old, new)
    world.source.commit("docs/p.md", STRUCTURE_PAGE.replace("First", "Upstream"))
    page = world.source.page("dfo-apis/p", "docs/p.md", title="P")

    log = world.push([page])

    assert log.failures == 0
    assert world.google.replaced == []
    assert (
        "not replaced: edited in Docs; set Status to Ready for review to send"
    ) in capsys.readouterr().out


def test_push_holds_doc_with_open_suggestions(
    world: World, capsys: pytest.CaptureFixture
):
    page, state = _pushed_page(world)
    world.google.suggestions[state.doc_id] = frozenset({"suggest.abc"})
    world.source.commit("docs/call.md", PAGE_TEXT.replace("JSON", "a JSON object"))
    page = _page(world)

    log = world.push([page])

    assert log.failures == 0
    assert world.google.replaced == []
    assert "not replaced: 1 open suggestions" in capsys.readouterr().out


def test_push_holds_doc_edited_while_the_guards_ran(
    world: World, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    page, state = _pushed_page(world)
    world.source.commit("docs/call.md", PAGE_TEXT.replace("JSON", "a JSON object"))
    page = _page(world)
    revisions = iter(["r1", "r2"])
    monkeypatch.setattr(
        world.google, "doc_revision_id", lambda session, doc_id: next(revisions)
    )

    log = world.push([page])

    assert log.failures == 0
    assert world.google.replaced == []
    assert world.store.states[page.page_id] == state
    assert "edited in Docs during this push" in capsys.readouterr().out


# State saving


def test_failed_state_save_writes_the_changed_states_to_a_file(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    world.store.save_error = StateConflictError("docsync-state moved; rerun")
    page = _page(world)

    with pytest.raises(cli.UnsavedStateError, match="docsync-state moved") as caught:
        world.push([page])

    (written,) = tmp_path.glob("docsync-unsaved-states-*.json")
    assert str(written) in str(caught.value)
    saved = json.loads(written.read_text())
    assert saved["loaded_tip"] is None
    assert saved["states"]["dfo-apis/call"]["doc_id"] == "doc-1"
    assert saved["states"]["dfo-apis/call"]["source_commit"] == page.commit


def test_state_is_saved_when_a_later_page_crashes(
    world: World, monkeypatch: pytest.MonkeyPatch
):
    world.source.commit("docs/other.md", "# Other\n\nOther text.\n")
    first = world.source.page("dfo-apis/call", "docs/call.md")
    second = world.source.page("dfo-apis/other", "docs/other.md", title="Other")
    create = world.google.create_doc

    def crash_on_second(session, **kwargs):
        if kwargs["name"] == "Other":
            raise RuntimeError("job killed")
        return create(session, **kwargs)

    monkeypatch.setattr(world.google, "create_doc", crash_on_second)

    with pytest.raises(RuntimeError, match="job killed"):
        world.push([first, second])

    assert set(world.store.states) == {"dfo-apis/call"}
    assert set(world.google.rows) == {"dfo-apis/call"}


def test_pull_writes_settled_rows_when_a_later_page_crashes(
    world: World, monkeypatch: pytest.MonkeyPatch
):
    world.source.commit("docs/other.md", "# Other\n\nOther text.\n")
    first = world.source.page("dfo-apis/call", "docs/call.md")
    second = world.source.page("dfo-apis/other", "docs/other.md", title="Other")
    assert world.push([first, second]).failures == 0
    _ready(world, first)
    world.google.edit(_doc(world, first), "your token", "your API token")
    assert world.pull([first]).failures == 0
    world.merge(
        texts={"docs/call.md": PAGE_TEXT.replace("your token", "your API token")}
    )
    first = _page(world)
    _ready(world, second)
    export = world.google.export_markdown

    def crash_on_second(session, file_id):
        if file_id == _doc(world, second):
            raise RuntimeError("job killed")
        return export(session, file_id)

    monkeypatch.setattr(world.google, "export_markdown", crash_on_second)

    with pytest.raises(RuntimeError, match="job killed"):
        world.pull([first, second])

    assert world.store.states[first.page_id].pr_url is None
    assert world.status(first) == "Merged"
    assert world.google.rows[first.page_id]["PR"] == ""


@pytest.mark.parametrize(
    "error",
    [
        GitError(["git", "push"], "rejected"),
        StateConflictError("docsync-state moved"),
        cli.GoogleApiError(status=500, message="boom", method="GET", url="u"),
        HubCheckoutError("HEAD is not origin/main"),
    ],
)
def test_main_exits_2_on_named_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, error: Exception
):
    def fail(args):
        raise error

    monkeypatch.setattr(cli, "_run", fail)

    assert cli.main(["push"]) == 2
    assert type(error).__name__ in capsys.readouterr().err


# Docs without state


def test_push_with_empty_state_and_docs_under_the_folder_is_refused(world: World):
    page, state = _pushed_page(world)
    world.store.states.clear()
    saves = len(world.store.saves)

    with pytest.raises(cli.StatelessDocsError, match="--adopt"):
        world.push([page])

    assert list(world.google.docs) == [state.doc_id]
    assert world.google.trashed == []
    assert len(world.store.saves) == saves


def test_main_exits_2_when_state_is_empty_and_docs_exist(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    def refuse(args):
        raise cli.StatelessDocsError("the state store holds no page states")

    monkeypatch.setattr(cli, "_run", refuse)

    assert cli.main(["push"]) == 2
    assert "StatelessDocsError" in capsys.readouterr().err


def test_push_parser_takes_adopt():
    assert cli._parser().parse_args(["push", "--adopt"]).adopt is True
    assert cli._parser().parse_args(["push"]).adopt is False


def test_docs_without_state_adopt_the_first_and_trash_aligned_duplicates(
    world: World, capsys: pytest.CaptureFixture
):
    page, state = _pushed_page(world)
    world.store.states.clear()
    world.google.docs["doc-dup"] = replace(world.google.docs[state.doc_id])

    log = world.push([page], adopt=True)

    assert log.failures == 0
    assert world.store.states[page.page_id].doc_id == state.doc_id
    assert world.google.trashed == ["doc-dup"]
    assert "trashed https://docs.google.com/document/d/doc-dup/edit" in (
        capsys.readouterr().out
    )


def test_duplicate_without_state_with_open_comments_is_kept(world: World):
    page, state = _pushed_page(world)
    world.store.states.clear()
    world.google.docs["doc-dup"] = replace(world.google.docs[state.doc_id])
    world.google.comments["doc-dup"] = [
        Comment(id="c1", content="Is this right?", author="Ana", quoted="token")
    ]

    log = world.push([page], adopt=True)

    assert log.failures == 1
    assert world.google.trashed == []
    assert world.store.states[page.page_id].doc_id == state.doc_id


def test_edited_doc_without_state_is_kept_and_fails_the_page(
    world: World, capsys: pytest.CaptureFixture
):
    page, state = _pushed_page(world)
    world.store.states.clear()
    world.google.edit(state.doc_id, "your token", "your API token")

    log = world.push([page], adopt=True)

    assert log.failures == 1
    assert world.google.trashed == []
    assert list(world.google.docs) == [state.doc_id]
    assert "your API token" in world.google.docs[state.doc_id].markdown
    assert page.page_id not in world.store.states
    assert (
        f"Doc https://docs.google.com/document/d/{state.doc_id}/edit carries this page"
        " id with no state and differs from the source; restore its state or trash"
        " it by hand"
    ) in capsys.readouterr().out


# restore


def test_restore_round_trips_the_states_a_failed_save_wrote(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
):
    monkeypatch.chdir(tmp_path)
    page, state = _pushed_page(world)
    world.source.commit("docs/call.md", PAGE_TEXT.replace("JSON", "a JSON object"))
    page = _page(world)
    world.store.save_error = StateConflictError("docsync-state moved")
    with pytest.raises(cli.UnsavedStateError):
        world.push([page])
    (written,) = tmp_path.glob("docsync-unsaved-states-*.json")
    world.store.save_error = None
    assert world.store.states[page.page_id] == state

    cli.restore(written, store=world.store)

    restored = world.store.states[page.page_id]
    assert restored.source_commit == page.commit
    assert "a JSON object" in restored.baseline
    assert world.store.saves[-1] == f"docsync restore: 1 pages from {written.name}"
    assert "dfo-apis/call: restored (replaced its stored state)" in (
        capsys.readouterr().out
    )
    assert world.push([page]).failures == 0
    assert world.google.replaced == [state.doc_id]


def _unsaved_after_a_later_save(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[SyncPage, Path]:
    """A pull whose save failed after settling a merge, then a push that saved."""
    monkeypatch.chdir(tmp_path)
    page, _ = _sent(world)
    world.merge(texts={"docs/call.md": REVIEWED})
    page = _page(world)
    world.store.save_error = StateConflictError("docsync-state moved")
    with pytest.raises(cli.UnsavedStateError):
        world.pull([page])
    world.store.save_error = None
    (written,) = tmp_path.glob("docsync-unsaved-states-*.json")
    assert world.push([page]).failures == 0
    return page, written


def test_restore_refuses_when_state_moved_since_the_failed_run(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _, written = _unsaved_after_a_later_save(world, tmp_path, monkeypatch)
    stored = dict(world.store.states)
    saves = len(world.store.saves)

    with pytest.raises(cli.StateMovedError) as caught:
        cli.restore(written, store=world.store)

    loaded = json.loads(written.read_text())["loaded_tip"]
    assert str(caught.value) == (
        f"state moved since the failed run ({loaded} → {world.store.tip()});"
        " restore page by page with --page, or overwrite with --force"
    )
    assert world.store.states == stored
    assert len(world.store.saves) == saves


@pytest.mark.parametrize("how", ["page", "force"])
def test_restore_by_page_or_force_overwrites_a_moved_state(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str
):
    page, written = _unsaved_after_a_later_save(world, tmp_path, monkeypatch)
    file_state = json.loads(written.read_text())["states"][page.page_id]

    if how == "page":
        cli.restore(written, store=world.store, pages=[page.page_id])
    else:
        cli.restore(written, store=world.store, force=True)

    assert vars(world.store.states[page.page_id]) == file_state


def test_restore_refuses_a_page_the_file_does_not_hold(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _, written = _unsaved_after_a_later_save(world, tmp_path, monkeypatch)

    with pytest.raises(cli.UnknownPageError, match="dfo-apis/nope"):
        cli.restore(written, store=world.store, pages=["dfo-apis/nope"])


def test_restore_parser_takes_page_and_force():
    args = cli._parser().parse_args(
        ["restore", "f.json", "--page", "a/b", "--page", "c/d", "--force"]
    )
    assert (args.pages, args.force) == (["a/b", "c/d"], True)
    args = cli._parser().parse_args(["restore", "f.json"])
    assert (args.pages, args.force) == ([], False)


def test_restore_command_writes_a_state_dir(tmp_path: Path, monkeypatch):
    state = PageState(
        page_id="dfo-apis/call",
        doc_id="doc-1",
        repo=REPO,
        ref="dev",
        path="docs/call.md",
        source_commit="a" * 40,
        baseline="# Call the API",
    )
    file = tmp_path / "docsync-unsaved-states-1.json"
    file.write_text(
        json.dumps({"loaded_tip": None, "states": {state.page_id: vars(state)}})
    )
    monkeypatch.chdir(tmp_path)

    assert cli.main(["restore", str(file), "--state-dir", str(tmp_path / "s")]) == 0

    assert DirStateStore(tmp_path / "s").load() == {state.page_id: state}


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        "{not json",
        json.dumps({"dfo-apis/call": {"page_id": "dfo-apis/call"}}),
        json.dumps({"loaded_tip": None, "states": {"dfo-apis/call": {"page_id": "x"}}}),
        json.dumps({"loaded_tip": None, "states": {"../x": {"page_id": "../x"}}}),
    ],
)
def test_restore_refuses_a_malformed_file_and_saves_nothing(
    world: World, tmp_path: Path, payload: str
):
    page, state = _pushed_page(world)
    file = tmp_path / "unsaved.json"
    file.write_text(payload)
    saves = list(world.store.saves)

    with pytest.raises(StateFormatError):
        cli.restore(file, store=world.store)

    assert world.store.saves == saves
    assert world.store.states == {page.page_id: state}


# Hub checkout, page selection, Sheet layout


def test_hub_pages_need_head_at_origin_main(tmp_path: Path):
    origin = Source(tmp_path / "origin")
    origin.git("checkout", "-q", "-b", "main")
    origin.commit("content/hub/index.md", "# Home\n")
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(origin.root), str(clone)],
        check=True,
        capture_output=True,
    )
    git = Git(root=clone, env=command_env(None))

    cli.require_hub_at_main(git)

    git.run(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@x",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "local",
    )
    with pytest.raises(HubCheckoutError, match="is not origin/main"):
        cli.require_hub_at_main(git)


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            [
                {"Page id": "dfo-apis/call", "Status": "Editing"},
                {"Page id": "dfo-apis/call", "Status": "Ready for review"},
            ],
            "more than once",
        ),
        (
            [{"Page id": "dfo-apis/call", "State": "Ready for review"}],
            "no Status column",
        ),
        (
            [{"Page": "dfo-apis/call", "Status": "Ready for review"}],
            "no Page id column",
        ),
    ],
)
def test_pull_refuses_an_ambiguous_sheet(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, str]],
    message: str,
):
    page, state = _pushed_page(world)
    world.google.edit(state.doc_id, "your token", "your API token")
    monkeypatch.setattr(
        world.google, "read_rows", lambda session, sheet_id, *, tab: rows
    )

    with pytest.raises(cli.SheetLayoutError, match=message):
        world.pull([page])

    assert world.proposals.calls == []


def test_init_adds_the_how_to_tab_an_interrupted_run_left_out(world: World):
    world.google.tabs["Pages"] = list(cli.COLUMNS)

    sheet_id = cli.init(None, drive_id=DRIVE, folder_id=ROOT)

    assert sheet_id == SHEET
    assert world.google.tabs["How to edit"]


# Commands end to end: `main` parses real arguments and runs the command

PUSH_PAGE_ID = "dfo-apis/call"


@dataclass
class Wired:
    """`main` with its edges faked: credentials, page loading, gh, and the state branch.

    `args` is the `--config` and `--folder` every command but `restore` takes, and
    `branch_stores` holds the keyword arguments of each `BranchStateStore` built.
    """

    args: list[str]
    branch_stores: list[dict]


@pytest.fixture
def wired(world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Wired:
    config = tmp_path / "docsync.yaml"
    config.write_text(
        "sources: [dfo-apis]\ndrive_folder_id: unused\npr_author: app/dfo-bot\n"
    )
    monkeypatch.setenv(cli.TOKEN_ENV, "bot-token")
    monkeypatch.setattr(cli, "open_session", lambda: None)
    monkeypatch.setattr(
        cli, "load_sync_pages", lambda config, *, repo_root, workdir: (_page(world),)
    )

    def view_pull_request(url: str, *, token: str | None) -> PullRequest:
        assert token == "bot-token"
        return world.github.pull_request(url)

    def list_open_pull_requests(
        repo: str, *, author: str, token: str | None
    ) -> list[OpenPullRequest]:
        assert token == "bot-token"
        return world.github.open_pull_requests(repo)

    monkeypatch.setattr(cli, "view_pull_request", view_pull_request)
    monkeypatch.setattr(cli, "list_open_pull_requests", list_open_pull_requests)
    branch_stores: list[dict] = []

    def branch_store(**kwargs) -> MemoryStore:
        branch_stores.append(kwargs)
        return world.store

    monkeypatch.setattr(cli, "BranchStateStore", branch_store)
    return Wired(["--config", str(config), "--folder", ROOT], branch_stores)


def test_init_command_needs_no_state_options(world: World, wired: Wired):
    world.google.sheets.clear()

    assert cli.main(["init", *wired.args]) == 0

    (sheet,) = world.google.sheets
    assert world.google.sheet_properties[sheet.id] == {"dfo_role": "tracking-sheet"}
    assert wired.branch_stores == []


def test_push_command_saves_to_the_state_branch(world: World, wired: Wired):
    assert cli.main(["push", *wired.args, "--page", PUSH_PAGE_ID]) == 0

    assert set(world.store.states) == {PUSH_PAGE_ID}
    assert world.status(_page(world)) == "Not started"
    (kwargs,) = wired.branch_stores
    assert kwargs["token"] == "bot-token"


def test_push_command_saves_to_a_state_dir(world: World, wired: Wired, tmp_path: Path):
    state_dir = tmp_path / "state"

    assert cli.main(["push", *wired.args, "--state-dir", str(state_dir)]) == 0

    assert set(DirStateStore(state_dir).load()) == {PUSH_PAGE_ID}
    assert world.store.states == {}
    assert wired.branch_stores == []


def test_push_command_adopts_docs_when_asked(world: World, wired: Wired):
    page, _ = _pushed_page(world)
    world.store.states.clear()

    assert cli.main(["push", *wired.args]) == 2
    assert cli.main(["push", *wired.args, "--adopt"]) == 0

    assert set(world.store.states) == {page.page_id}


def test_pull_command_opens_the_pr(world: World, wired: Wired):
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, "your token", "your API token")

    assert cli.main(["pull", *wired.args, "--pr-author", "app/other"]) == 0

    (call,) = world.proposals.calls
    assert call["author"] == "app/other"
    assert world.store.states[page.page_id].pr_url == PR_URL
    assert world.status(page) == "PR open"
    assert wired.branch_stores[0]["token"] == "bot-token"


def test_pull_command_dry_run_writes_files_only(
    world: World, wired: Wired, tmp_path: Path
):
    page, state = _pushed_page(world)
    _ready(world, page)
    world.google.edit(state.doc_id, "your token", "your API token")
    saves = len(world.store.saves)

    assert cli.main(["pull", *wired.args, "--dry-run", str(tmp_path / "dry")]) == 0

    (call,) = world.proposals.calls
    assert call["dry_run_dir"] == tmp_path / "dry" / "ONEcampaign__dfo-apis"
    assert len(world.store.saves) == saves
    assert world.status(page) == "Ready for review"


def test_restore_command_writes_the_state_branch(
    world: World, wired: Wired, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    page, state = _pushed_page(world)
    file = tmp_path / "docsync-unsaved-states-1.json"
    file.write_text(
        json.dumps(
            {
                "loaded_tip": world.store.tip(),
                "states": {page.page_id: vars(replace(state, doc_id="doc-9"))},
            }
        )
    )
    monkeypatch.chdir(tmp_path)

    assert cli.main(["restore", str(file)]) == 0

    assert world.store.states[page.page_id].doc_id == "doc-9"
    (kwargs,) = wired.branch_stores
    assert kwargs["token"] == "bot-token"
