"""`dfo-docsync`: publish the DFO docs pages as Google Docs and pull edits back as PRs.

`init` creates the tracking Sheet in the "DFO docs" folder. `push` creates or replaces
each in-scope page's Doc and records the export Google returns as the page's baseline.
`pull` sends the edits of every Doc whose Sheet Status is "Ready for review" as one new
pull request per source repository. `restore` loads the page states a run that could not
save them wrote to a local file, and refuses when the store moved since that run loaded
it.

docsync opens each pull request once and never pushes to its branch or edits it again,
so reviewers may commit to it. A page is in at most one open pull request: pull skips a
page while its pull request is open, and fails a Ready page whose file an open docsync
pull request its state does not name changes. Both commands first settle each page's
pull request. Once it has merged into the branch the page is read from, the Doc's edits
up to that pull count as applied. Once it is closed, or merged without the page, the
page leaves it with its edits still in the Doc and returns to Editing.

Push replaces a Doc only when nobody has edited it since docsync last wrote it or
applied its edits: its export must hold the same blocks as the export last applied, or
as the baseline when none is. It never replaces a Doc with open suggestions, which a
replace would discard, and refuses when the Doc's revision changed while the guards
ran. It holds a Doc with open comments, which a replace would detach, unless the
page's Status is "Discard my edits". A page whose Doc is in the trash or deleted gets a
new Doc when it is in no open pull request. Push refuses to start when the state store
is empty but Docs exist under the folder, unless `--adopt` is given, and it never
trashes a Doc that differs from its source. Pull never reads a Doc with open
suggestions.

A page that fails is reported and the run moves on; the exit code is 1 when any page
failed. A page held back by a guard (edited in Docs, open comments, open suggestions,
an open pull request) is reported and is not a failure. A missing credential, folder,
Sheet, or state branch, a git or Google failure outside a page, and a state save that
fails stop the run with a named error and exit code 2.
"""

from __future__ import annotations

import argparse
import dataclasses
import functools
import json
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from importlib import resources
from pathlib import Path

import requests
from google.auth.exceptions import DefaultCredentialsError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

from dfo_docs.docsync import google
from dfo_docs.docsync.adapter import (
    BaselineMismatchError,
    BlockError,
    align_baseline,
    export_content_key,
    to_doc_markdown,
)
from dfo_docs.docsync.edits import (
    Report,
    ReportKind,
    apply_edits,
    merge_onto_current,
)
from dfo_docs.docsync.git import TOKEN_ENV, Git, GitError, command_env
from dfo_docs.docsync.google import (
    PAGE_ID_PROPERTY,
    SHEET_MIME,
    DriveFile,
    GoogleApiError,
    GoogleStateError,
)
from dfo_docs.docsync.pages import (
    CONFIG_FILE,
    HUB,
    DocsyncConfigError,
    HubCheckoutError,
    SyncPage,
    load_config,
    load_sync_pages,
)
from dfo_docs.docsync.prs import (
    EditedFile,
    GhError,
    NoChangesError,
    OpenPullRequest,
    PageEntry,
    PrError,
    PullRequest,
    Refusal,
    edits_branch,
    list_open_pull_requests,
    propose_edits,
    render_pr_body,
    render_within,
    shorten_quote,
    view_pull_request,
)
from dfo_docs.docsync.state import (
    BranchStateStore,
    DirStateStore,
    PageState,
    StateError,
    StateFormatError,
    StateStore,
    state_from_json,
)
from dfo_docs.fetch import FetchError

# A Google OAuth access token with the drive scope, for local runs (`gcloud auth
# print-access-token` after `gcloud auth login --enable-gdrive-access`). When unset,
# Application Default Credentials are used, as in CI.
ACCESS_TOKEN_ENV = "DOCSYNC_ACCESS_TOKEN"

SHEET_NAME = "DFO docs tracker"
PAGES_TAB = "Pages"
HOW_TO_TAB = "How to edit"
ROLE_PROPERTY = "dfo_role"
SHEET_ROLE = "tracking-sheet"
# The Drive property on each Doc naming the "DFO docs" folder it was pushed under, so a
# scratch run under another folder never mistakes production Docs for its own.
#
# The page id and root markers are public Drive `properties`. `appProperties` would hide
# them from other editors, but they are private to the Google Cloud project of the OAuth
# client that wrote them, and CI's service account and a local `gcloud` login belong to
# different projects, so each would see only the Docs it created. Any editor can set or
# copy a public property. A forged marker can only fail a page (two Docs carry its id)
# or let `--adopt` keep one duplicate of a Doc that matches its source.
ROOT_PROPERTY = "dfo_root"

PR_TITLE = "Apply edits from Google Docs"
HUB_BASE = "main"
HUB_REMOTE = "origin"
DOC_URL = "https://docs.google.com/document/d/{doc_id}/edit"

# What the Not applied column says for a Ready page whose edits change nothing and
# raise no report.
NOTHING_TO_SEND = "Nothing to send: these edits are already in GitHub"

# What the Not applied column ends with when a pull held a page's Doc as it is.
HOLD_ADVICE = (
    "Your text stays in the Doc. Undo or rework this edit, then set Status to"
    ' "Ready for review" again, or set Status to "Discard my edits" to replace the'
    " Doc with the page from GitHub."
)

# The most characters the Not applied cell holds. A Sheet cell takes 50,000.
NOT_APPLIED_LIMIT = 45_000

# The report kinds that name an edit that was applied. A pull request that carried one
# does not repeat it in the next.
_MERGED_KINDS = frozenset({ReportKind.HEADING_ANCHOR, ReportKind.NOTE_LABEL})

# Where a run that could not save state writes the page states it changed, in the
# working directory. It is a JSON object holding `loaded_tip`, the store's tip the run
# loaded, and `states`, the `PageState` fields keyed by page id.
UNSAVED_STATES_FILE = "docsync-unsaved-states-{stamp}.json"


class Status(StrEnum):
    """The values of the Sheet's Status column."""

    NOT_STARTED = "Not started"
    EDITING = "Editing"
    READY = "Ready for review"
    PR_OPEN = "PR open"
    MERGED = "Merged"
    DISCARD = "Discard my edits"


KEY_COLUMN = "Page id"
STATUS_COLUMN = "Status"
NOT_APPLIED_COLUMN = "Not applied"

# The Pages tab header. Owner, Reviewer, Status and Notes belong to editors, and the
# script writes Status only for the transitions it causes. Not applied says what
# happened to edits that did not reach the source: those a pull could not apply, a pull
# request closed without them, later edits after a merge, or a discard. Pull, settle and
# a discard write it. A plain push leaves it as it is.
COLUMNS = (
    KEY_COLUMN,
    "Title",
    "Section",
    "Owner",
    "Reviewer",
    STATUS_COLUMN,
    "Doc",
    "PR",
    "Repo",
    "File",
    "Last pushed",
    "Last pulled",
    NOT_APPLIED_COLUMN,
    "Notes",
)


class DocsyncError(RuntimeError):
    """docsync cannot run: something it needs is missing or ambiguous."""


class MissingCredentialsError(DocsyncError):
    """No Google credentials are available."""


class MissingFolderError(DocsyncError):
    """The "DFO docs" folder does not exist or the credentials cannot see it."""


class MissingSheetError(DocsyncError):
    """The "DFO docs" folder holds no tracking Sheet."""


class DuplicateSheetError(DocsyncError):
    """The "DFO docs" folder holds more than one tracking Sheet."""


class SheetLayoutError(DocsyncError):
    """The Pages tab lacks a column docsync reads, or lists a page twice."""


class UnknownPageError(DocsyncError):
    """`--page` names a page that is not in scope."""


class UnsavedStateError(DocsyncError):
    """The run changed page states and could not save them. They are in a local file."""


class StateMovedError(DocsyncError):
    """The state store moved since the failed run that wrote an unsaved-states file."""


class StatelessDocsError(DocsyncError):
    """The state store holds no page states, but Docs exist under the folder.

    The state was lost, or the run points an empty store at another run's folder. Push
    refuses unless `--adopt` is given.
    """


# Errors that fail one page or one repository and let the run carry on.
_PAGE_ERRORS = (
    GoogleApiError,
    GoogleStateError,
    BaselineMismatchError,
    BlockError,
    PrError,
)


@dataclass
class RunLog:
    """Prints one line per page outcome and counts the failures."""

    failures: int = 0

    def info(self, subject: str, message: str) -> None:
        """Report something done, or held back by a guard."""
        print(f"{subject}: {message}")

    def fail(self, subject: str, message: str) -> None:
        """Report a failure. The run exits non-zero at the end."""
        self.failures += 1
        print(f"{subject}: FAILED: {message}")


@dataclass(frozen=True)
class Context:
    """What every command needs: the session, where the Docs live, the Sheet, the clock.

    `pull_request` looks up a pull request by URL, and `open_pull_requests` lists the
    open docsync pull requests of a repository. `pr_author` is the gh `--author` of
    those pull requests.
    """

    session: requests.Session
    drive_id: str
    folder_id: str
    sheet_id: str
    pull_request: Callable[[str], PullRequest]
    open_pull_requests: Callable[[str], Sequence[OpenPullRequest]]
    pr_author: str
    now: str


# Entry point


def main(argv: Sequence[str] | None = None) -> int:
    """Run one docsync command. Returns 0, 1 when a page failed, 2 when the run could not start."""
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except (
        DocsyncError,
        DocsyncConfigError,
        HubCheckoutError,
        StateError,
        GitError,
        GhError,
        GoogleApiError,
        GoogleStateError,
        FetchError,
    ) as exc:
        print(f"dfo-docsync: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dfo-docsync", description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, default=Path(CONFIG_FILE))
    common.add_argument(
        "--folder", help="the DFO docs folder id; overrides drive_folder_id"
    )
    stored = argparse.ArgumentParser(add_help=False)
    stored.add_argument(
        "--state-dir",
        type=Path,
        help="keep state in this directory instead of the docsync-state branch",
    )
    paged = argparse.ArgumentParser(add_help=False, parents=[common, stored])
    paged.add_argument(
        "--page",
        action="append",
        default=[],
        dest="pages",
        help="only this page id (repeatable)",
    )
    paged.add_argument(
        "--pr-author",
        help="list open docsync PRs by this gh --author; overrides pr_author",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", parents=[common], help="create the tracking Sheet")
    push_command = commands.add_parser(
        "push", parents=[paged], help="publish pages as Docs"
    )
    push_command.add_argument(
        "--adopt",
        action="store_true",
        help="run with an empty state store although Docs exist under the folder",
    )
    pull_command = commands.add_parser(
        "pull", parents=[paged], help="open PRs from Doc edits"
    )
    pull_command.add_argument(
        "--dry-run",
        type=Path,
        metavar="DIR",
        help="write the edited files and PR bodies under DIR; no git, state or Sheet writes",
    )
    restore_command = commands.add_parser(
        "restore", parents=[stored], help="load the page states a failed save wrote"
    )
    restore_command.add_argument(
        "file", type=Path, help="a docsync-unsaved-states-*.json file"
    )
    restore_command.add_argument(
        "--page",
        action="append",
        default=[],
        dest="pages",
        help="restore only this page id from the file, even if the state moved"
        " (repeatable)",
    )
    restore_command.add_argument(
        "--force",
        action="store_true",
        help="restore every page in the file although the state moved since",
    )
    return parser


def _run(args: argparse.Namespace) -> int:
    repo_root = Path.cwd()
    github_token = os.environ.get(TOKEN_ENV) or None
    if args.command == "restore":
        store = _store(args, repo_root=repo_root, token=github_token)
        restore(args.file, store=store, pages=args.pages, force=args.force)
        return 0

    config = load_config(args.config)
    folder_id = args.folder or config.drive_folder_id
    session = open_session()
    drive_id = _drive_id(session, folder_id)

    if args.command == "init":
        init(session, drive_id=drive_id, folder_id=folder_id)
        return 0

    sheet_id = find_sheet(session, drive_id=drive_id, folder_id=folder_id)
    if HUB in config.sources:
        require_hub_at_main(Git(root=repo_root, env=command_env(github_token)))
    pr_author = args.pr_author or config.pr_author
    ctx = Context(
        session=session,
        drive_id=drive_id,
        folder_id=folder_id,
        sheet_id=sheet_id,
        pull_request=functools.cache(
            functools.partial(view_pull_request, token=github_token)
        ),
        open_pull_requests=functools.cache(
            functools.partial(
                list_open_pull_requests, author=pr_author, token=github_token
            )
        ),
        pr_author=pr_author,
        now=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    )
    log = RunLog()
    with tempfile.TemporaryDirectory(prefix="dfo_docsync-") as workdir:
        pages = load_sync_pages(config, repo_root=repo_root, workdir=Path(workdir))
        selected = select_pages(pages, args.pages)
        store = _store(args, repo_root=repo_root, token=github_token)
        if args.command == "push":
            push(
                ctx,
                pages=selected,
                scope=pages,
                store=store,
                log=log,
                adopt=args.adopt,
            )
        else:
            pull(ctx, pages=selected, store=store, log=log, dry_run_dir=args.dry_run)
    return 1 if log.failures else 0


def _store(
    args: argparse.Namespace, *, repo_root: Path, token: str | None
) -> StateStore:
    """The state store `--state-dir` names, else the `docsync-state` branch.

    Only the commands that take `--state-dir` (restore, push, pull) call this.
    """
    if args.state_dir:
        return DirStateStore(args.state_dir)
    return BranchStateStore(repo_root=repo_root, token=token)


def open_session() -> requests.Session:
    """An authorised session from `DOCSYNC_ACCESS_TOKEN`, else from ADC.

    Raises:
        MissingCredentialsError: neither is available.
    """
    if token := os.environ.get(ACCESS_TOKEN_ENV):
        return AuthorizedSession(Credentials(token=token))
    try:
        return google.default_session()
    except DefaultCredentialsError as exc:
        raise MissingCredentialsError(
            f"set {ACCESS_TOKEN_ENV} or configure Application Default Credentials"
            f" with the drive, documents.readonly and spreadsheets scopes: {exc}"
        ) from exc


def require_hub_at_main(git: Git) -> None:
    """Refuse unless the dfo-docs checkout's `HEAD` is the remote's `main`.

    Hub pages are read at `HEAD` and their edits proposed against `main`, so any other
    commit would publish unmerged text or carry unrelated changes into the pull request.

    Raises:
        HubCheckoutError: `HEAD` differs from the freshly fetched `origin/main`.
        GitError: the fetch failed.
    """
    git.run("fetch", "-q", HUB_REMOTE, f"refs/heads/{HUB_BASE}")
    main = git.run("rev-parse", "--verify", "FETCH_HEAD^{commit}").strip()
    head = git.run("rev-parse", "--verify", "HEAD^{commit}").strip()
    if head != main:
        raise HubCheckoutError(
            f"{git.root}: HEAD {head[:12]} is not {HUB_REMOTE}/{HUB_BASE}"
            f" {main[:12]}; check out {HUB_BASE} and pull before syncing hub pages"
        )


def select_pages(pages: Sequence[SyncPage], page_ids: Sequence[str]) -> list[SyncPage]:
    """The pages `--page` names, in nav order; every page when it names none.

    Raises:
        UnknownPageError: a named page is not in scope.
    """
    if not page_ids:
        return list(pages)
    known = {page.page_id for page in pages}
    unknown = sorted(set(page_ids) - known)
    if unknown:
        raise UnknownPageError(f"pages not in scope: {', '.join(unknown)}")
    return [page for page in pages if page.page_id in page_ids]


def _drive_id(session: requests.Session, folder_id: str) -> str:
    try:
        return google.get_drive_id(session, folder_id)
    except GoogleApiError as exc:
        if exc.status == 404:
            raise MissingFolderError(
                f"folder {folder_id} does not exist or is not shared with these"
                " credentials"
            ) from exc
        raise


# init


def init(session: requests.Session, *, drive_id: str, folder_id: str) -> str:
    """Create the tracking Sheet in `folder_id` unless it exists; return its id.

    The Sheet gets the Pages tab with Status validation and the How to edit tab. Its
    `dfo_role` property is set by the create request itself, so the Sheet is never
    untagged and a retried create returns it. An init that stopped before adding the
    How to edit tab adds it on the next run.

    Raises:
        DuplicateSheetError: the folder already holds more than one tracking Sheet.
    """
    existing = _tracking_sheets(session, drive_id=drive_id, folder_id=folder_id)
    if existing:
        sheet_id = existing[0].id
        print(f"tracking Sheet exists: {sheet_id}")
    else:
        sheet_id = google.create_sheet(
            session,
            name=SHEET_NAME,
            parent_id=folder_id,
            tab=PAGES_TAB,
            columns=COLUMNS,
            validations={STATUS_COLUMN: [status.value for status in Status]},
            properties={ROLE_PROPERTY: SHEET_ROLE},
        )
        print(f"created tracking Sheet {sheet_id}")
    if HOW_TO_TAB not in google.tab_titles(session, sheet_id):
        guide = (
            resources.files("dfo_docs.docsync").joinpath("how_to_edit.md").read_text()
        )
        google.add_text_tab(session, sheet_id, tab=HOW_TO_TAB, lines=guide.splitlines())
    return sheet_id


def find_sheet(session: requests.Session, *, drive_id: str, folder_id: str) -> str:
    """The id of the tracking Sheet in `folder_id`.

    Raises:
        MissingSheetError: there is none. `dfo-docsync init` creates it.
        DuplicateSheetError: there is more than one.
    """
    sheets = _tracking_sheets(session, drive_id=drive_id, folder_id=folder_id)
    if not sheets:
        raise MissingSheetError(
            f"folder {folder_id} has no tracking Sheet; run `dfo-docsync init`"
        )
    return sheets[0].id


def _tracking_sheets(
    session: requests.Session, *, drive_id: str, folder_id: str
) -> list[DriveFile]:
    sheets = google.find_files_with_property(
        session,
        drive_id=drive_id,
        parent_id=folder_id,
        mime_type=SHEET_MIME,
        key=ROLE_PROPERTY,
        value=SHEET_ROLE,
    )
    if len(sheets) > 1:
        ids = ", ".join(sheet.id for sheet in sheets)
        raise DuplicateSheetError(f"folder {folder_id} holds tracking Sheets {ids}")
    return sheets


# push


@dataclass(frozen=True)
class _Result:
    """A page's state after a command, and the Sheet fields the command writes for it."""

    state: PageState
    row: Mapping[str, str] = dataclasses.field(default_factory=dict)


def push(
    ctx: Context,
    *,
    pages: Sequence[SyncPage],
    scope: Sequence[SyncPage],
    store: StateStore,
    log: RunLog,
    adopt: bool = False,
) -> None:
    """Settle, then create or replace the Doc of each page in `pages`; save state and the Sheet.

    `scope` is every in-scope page. State and Docs for pages outside it are reported
    and left in place. State and Sheet rows are saved even when the loop stops part
    way, so every Doc already created or replaced keeps its record and its row.

    Raises:
        StatelessDocsError: the store holds no states, Docs exist under the folder, and
            `adopt` is False.
        UnsavedStateError: the state save failed; the changed states are in a file.
    """
    states = store.load()
    docs = _docs_under_root(ctx)
    if not states and docs and not adopt:
        raise StatelessDocsError(
            f"the state store holds no page states, but {len(docs)} pages have Docs"
            f" under folder {ctx.folder_id}. Restore the state, check --folder and"
            " --state-dir, or rerun push with --adopt to adopt the Docs that match"
            " their source"
        )
    rows = _rows_by_page(ctx)
    _report_strays(states, docs, scope=scope, log=log)

    folders: dict[tuple[str, ...], str] = {}
    changed: dict[str, PageState] = {}
    sheet_rows: list[dict[str, str]] = []
    try:
        for page in pages:
            state = states.get(page.page_id)
            row = rows.get(page.page_id)
            try:
                result = _push_page(
                    ctx,
                    page,
                    state=state,
                    status=(row or {}).get(STATUS_COLUMN),
                    docs=docs.get(page.page_id, []),
                    folders=folders,
                    log=log,
                )
            except _PAGE_ERRORS as exc:
                log.fail(page.page_id, str(exc))
                result = None
            if result is not None:
                if result.state != state:
                    changed[page.page_id] = result.state
                state = result.state
            if state is None:
                continue

            fields = {**_script_row(page, state), **(result.row if result else {})}
            if row is None:
                fields[STATUS_COLUMN] = Status.NOT_STARTED
            sheet_rows.append(fields)
    finally:
        _save(store, states, changed, message=f"docsync push: {len(changed)} pages")
        _write_rows(ctx, sheet_rows)


def _push_page(
    ctx: Context,
    page: SyncPage,
    *,
    state: PageState | None,
    status: str | None,
    docs: Sequence[DriveFile],
    folders: dict[tuple[str, ...], str],
    log: RunLog,
) -> _Result | None:
    """Settle, then create, adopt, recreate or replace one page's Doc.

    A Status that still reads Discard my edits after a discard (the run's Sheet write
    failed) only becomes Editing, so edits typed since are kept. Returns None when the
    page has no state and gets none.
    """
    markdown = to_doc_markdown(page.text)
    if state is None:
        if docs:
            return _adopt(ctx, page, docs=docs, log=log)
        return _create(ctx, page, markdown=markdown, folders=folders, log=log)

    if state.discarded_on is not None:
        if status == Status.DISCARD:
            log.info(
                page.page_id,
                f"not replaced: its edits were discarded on {state.discarded_on}",
            )
            return _Result(state=state, row={STATUS_COLUMN: Status.EDITING})
        state = dataclasses.replace(state, discarded_on=None)

    doc_ids = [doc.id for doc in docs]
    settled = _settle(
        ctx,
        page,
        state,
        status=status,
        doc_gone=state.doc_id not in doc_ids,
        discarding=status == Status.DISCARD,
    )
    if settled.held is not None:
        log.info(page.page_id, f"not replaced: {settled.held}")
        return settled.result
    changed = _write_doc(
        ctx,
        page,
        state=settled.result.state,
        status=settled.result.row.get(STATUS_COLUMN, status),
        docs=docs,
        markdown=markdown,
        folders=folders,
        log=log,
    )
    if changed is None:
        return settled.result
    row = {**settled.result.row, **changed.row}
    if notes := [
        note
        for note in (
            settled.result.row.get(NOT_APPLIED_COLUMN),
            changed.row.get(NOT_APPLIED_COLUMN),
        )
        if note
    ]:
        row[NOT_APPLIED_COLUMN] = " | ".join(notes)
    return _Result(state=changed.state, row=row)


def _write_doc(
    ctx: Context,
    page: SyncPage,
    *,
    state: PageState,
    status: str | None,
    docs: Sequence[DriveFile],
    markdown: str,
    folders: dict[tuple[str, ...], str],
    log: RunLog,
) -> _Result | None:
    """Recreate a gone Doc or replace the page's Doc; None when it stays as it is."""
    if not docs:
        return _create(
            ctx, page, markdown=markdown, folders=folders, log=log, gone=state.doc_id
        )
    if [doc.id for doc in docs] != [state.doc_id]:
        log.fail(
            page.page_id,
            f"state names Doc {state.doc_id}, but Docs {_ids(docs)} carry this page id",
        )
        return None
    return _update(
        ctx,
        page,
        state=state,
        markdown=markdown,
        discard=status == Status.DISCARD,
        log=log,
    )


def _update(
    ctx: Context,
    page: SyncPage,
    *,
    state: PageState,
    markdown: str,
    discard: bool,
    log: RunLog,
) -> _Result | None:
    """Replace the page's Doc when the guards allow it, else return None.

    An unedited Doc is replaced when its source moved on, or when its edits are
    applied (`applied_export` is set), so it shows what the source holds. With
    `discard`, the Doc is replaced from the current source whatever its edits and
    comments, and the page returns to Editing.
    """
    if not discard and state.applied_export is None and _same_source(page, state):
        return None

    revision = google.doc_revision_id(ctx.session, state.doc_id)
    if reason := _hold_reason(ctx, state, discard=discard):
        log.info(page.page_id, f"not replaced: {reason}")
        return None
    if google.doc_revision_id(ctx.session, state.doc_id) != revision:
        log.info(page.page_id, "not replaced: edited in Docs during this push")
        return None

    google.replace_doc_content(ctx.session, file_id=state.doc_id, markdown=markdown)
    baseline = google.export_settled(ctx.session, state.doc_id)
    try:
        align_baseline(page=page.page_id, source=page.text, baseline=baseline)
    except BaselineMismatchError as exc:
        log.fail(page.page_id, str(exc))
        # The Doc holds the new content. Recording its export with the old commit
        # lets the next push see an unedited Doc, and pull refuses the page loudly
        # because the baseline does not align with that commit.
        return _Result(
            state=dataclasses.replace(state, baseline=baseline, applied_export=None)
        )

    row = {"Last pushed": ctx.now}
    if discard:
        log.info(page.page_id, f"discarded the edits in {_doc_url(state.doc_id)}")
        row |= {
            STATUS_COLUMN: Status.EDITING,
            NOT_APPLIED_COLUMN: f"Edits discarded on {ctx.now}",
        }
    else:
        log.info(page.page_id, f"replaced {_doc_url(state.doc_id)}")
    replaced = _new_state(page, state.doc_id, baseline=baseline)
    if discard:
        replaced = dataclasses.replace(replaced, discarded_on=ctx.now)
    return _Result(state=replaced, row=row)


def _hold_reason(ctx: Context, state: PageState, *, discard: bool) -> str | None:
    """Why the push guards keep the Doc as it is, or None when it may be replaced.

    The Doc may be replaced when it has no open suggestions, which a replace would
    discard; when its export holds the same blocks as `applied_export`, or as the
    baseline when no edit is applied; and when it has no open comments, which a replace
    would detach. With `discard`, only the suggestions guard applies.
    """
    if suggestions := google.open_suggestion_ids(ctx.session, state.doc_id):
        return f"{len(suggestions)} open suggestions; accept or reject them first"
    if discard:
        return None
    export = google.export_settled(ctx.session, state.doc_id)
    if not _same_content(export, _reference(state)):
        return "edited in Docs; set Status to Ready for review to send"
    if comments := google.list_open_comments(ctx.session, state.doc_id):
        return f"{len(comments)} open comments; resolve them first"
    return None


def _reference(state: PageState) -> str:
    """The export an unedited Doc holds: the last applied one, else the baseline."""
    return state.applied_export or state.baseline


def _adopt(
    ctx: Context, page: SyncPage, *, docs: Sequence[DriveFile], log: RunLog
) -> _Result | None:
    """Adopt a Doc that carries this page's id under this root but has no state.

    A push that stopped between creating a Doc and saving state leaves one, and a
    retried create can leave two. Every Doc's settled export must align with the
    source. One that does not may hold an editor's work, so it fails the page, stays in
    place, and nothing is adopted. Otherwise the first Doc is adopted and the others are
    trashed, except one with open comments or suggestions, which fails the page.
    """
    exports = {doc.id: google.export_settled(ctx.session, doc.id) for doc in docs}
    if differing := [doc for doc in docs if not _aligns(page, exports[doc.id])]:
        for doc in differing:
            log.fail(
                page.page_id,
                f"Doc {_doc_url(doc.id)} carries this page id with no state and differs"
                " from the source; restore its state or trash it by hand",
            )
        return None

    adopted, *duplicates = docs
    log.info(page.page_id, f"adopted {_doc_url(adopted.id)}, which had no state")
    for doc in duplicates:
        if reason := _open_work(ctx, doc.id):
            log.fail(
                page.page_id,
                f"Doc {_doc_url(doc.id)} duplicates {_doc_url(adopted.id)} with no"
                f" state but has {reason}; resolve them and trash it by hand",
            )
            continue
        google.trash_file(ctx.session, doc.id)
        log.info(
            page.page_id,
            f"trashed {_doc_url(doc.id)}, a duplicate of {_doc_url(adopted.id)}"
            " with no state",
        )
    return _Result(
        state=_new_state(page, adopted.id, baseline=exports[adopted.id]),
        row={"Last pushed": ctx.now},
    )


def _aligns(page: SyncPage, export: str) -> bool:
    """Whether `export` holds the page's source, as a fresh push of it would."""
    try:
        align_baseline(page=page.page_id, source=page.text, baseline=export)
    except BaselineMismatchError:
        return False
    return True


def _open_work(ctx: Context, doc_id: str) -> str | None:
    """The open suggestions or comments a trash would discard, or None when there are none."""
    if suggestions := google.open_suggestion_ids(ctx.session, doc_id):
        return f"{len(suggestions)} open suggestions"
    if comments := google.list_open_comments(ctx.session, doc_id):
        return f"{len(comments)} open comments"
    return None


def _create(
    ctx: Context,
    page: SyncPage,
    *,
    markdown: str,
    folders: dict[tuple[str, ...], str],
    log: RunLog,
    gone: str | None = None,
) -> _Result | None:
    """Create the page's Doc; `gone` names the Doc it replaces, which is trashed or deleted."""
    parent = folders.get(page.section_path)
    if parent is None:
        parent = google.ensure_folder_path(
            ctx.session,
            drive_id=ctx.drive_id,
            parent_id=ctx.folder_id,
            names=page.section_path,
        )
        folders[page.section_path] = parent
    doc_id = google.create_doc(
        ctx.session,
        name=page.title,
        markdown=markdown,
        parent_id=parent,
        properties={PAGE_ID_PROPERTY: page.page_id, ROOT_PROPERTY: ctx.folder_id},
    )
    baseline = google.export_settled(ctx.session, doc_id)
    try:
        align_baseline(page=page.page_id, source=page.text, baseline=baseline)
    except BaselineMismatchError as exc:
        google.trash_file(ctx.session, doc_id)
        log.fail(page.page_id, f"{exc}. Doc {_doc_url(doc_id)} was trashed")
        return None

    created = f"created {_doc_url(doc_id)}"
    if gone is not None:
        created = f"Doc {_doc_url(gone)} is in the trash or gone; {created}"
    log.info(page.page_id, created)
    return _Result(
        state=_new_state(page, doc_id, baseline=baseline),
        row={"Last pushed": ctx.now},
    )


def _new_state(page: SyncPage, doc_id: str, *, baseline: str) -> PageState:
    return PageState(
        page_id=page.page_id,
        doc_id=doc_id,
        repo=page.repo,
        ref=page.ref,
        path=page.path,
        source_commit=page.commit,
        baseline=baseline,
    )


def _same_source(page: SyncPage, state: PageState) -> bool:
    """Whether the page's file is the blob that was pushed."""
    if (state.repo, state.path) != (page.repo, page.path):
        return False
    if state.source_commit == page.commit:
        return True
    git = _clone_git(page.clone_root)
    pushed = git.run("rev-parse", f"{state.source_commit}:{state.path}")
    current = git.run("rev-parse", f"{page.commit}:{page.path}")
    return pushed == current


def _same_content(export: str, reference: str) -> bool:
    """Whether two exports hold the same blocks, structure included.

    An export the block model cannot read counts as different, so the guard holds.
    """
    try:
        return export_content_key(export) == export_content_key(reference)
    except BlockError:
        return False


def _docs_under_root(ctx: Context) -> dict[str, list[DriveFile]]:
    """Every synced Doc pushed under this run's root folder, by page id."""
    synced = google.list_synced_docs(ctx.session, drive_id=ctx.drive_id)
    docs: dict[str, list[DriveFile]] = {}
    for page_id, files in synced.items():
        if kept := [
            f for f in files if f.properties.get(ROOT_PROPERTY) == ctx.folder_id
        ]:
            docs[page_id] = kept
    return docs


def _report_strays(
    states: Mapping[str, PageState],
    docs: Mapping[str, Sequence[DriveFile]],
    *,
    scope: Iterable[SyncPage],
    log: RunLog,
) -> None:
    in_scope = {page.page_id for page in scope}
    for page_id in sorted(set(states) - in_scope):
        log.info(page_id, "state for a page no longer in scope; left in place")
    for page_id in sorted(set(docs) - in_scope - set(states)):
        log.info(
            page_id,
            f"Doc {_ids(docs[page_id])} for a page no longer in scope has no state;"
            " left in place",
        )


# Settle


@dataclass(frozen=True)
class _Settled:
    """A page after settling its pull request.

    `held` says why the page stays as it is this run: its pull request is open, or
    merged into a branch the page's source does not hold yet. `merged` says this run
    applied the page's merged pull request.
    """

    result: _Result
    held: str | None = None
    merged: bool = False


def _settle(
    ctx: Context,
    page: SyncPage,
    state: PageState,
    *,
    status: str | None,
    doc_gone: bool = False,
    discarding: bool = False,
) -> _Settled:
    """Settle the page's pull request, if it has one.

    An open pull request holds the page. One merged with the page's path counts once its
    merge commit is in the page's source commit: its export becomes `applied_export`.
    One closed, or merged without the page, leaves `applied_export` as it was. Either
    way the page leaves the pull request and the Not applied column says why when edits
    remain. After a merge, Status changes only from PR open, to Merged when the Doc
    still holds the merged edits and to Editing otherwise, so a Status of Ready for
    review set while the pull request was open survives and sends the newer edits.
    After a close, Status becomes Editing whatever it read, except Discard my edits,
    which stays so the discard runs.

    `discarding` says the caller is about to discard the Doc's edits (push, with
    Status Discard my edits). A merge whose commit the source does not hold, or that
    git cannot place, then releases the page instead of holding it, since the discard
    needs the page out of the pull request and the edits are being dropped anyway.

    `doc_gone` says the Doc is in the trash or deleted. Its export is not read.

    Raises:
        GitError: git could not tell whether the merge commit is in the source, and
            `discarding` is False.
        GhError: gh failed, or reports a merged pull request without a merge commit.
    """
    url = state.pr_url
    if url is None:
        return _Settled(_Result(state))
    if _is_open(ctx, state.repo, url):
        return _Settled(_Result(state), held=f"in review at {url}")
    pull_request = ctx.pull_request(url)
    if pull_request.state == "OPEN":
        return _Settled(_Result(state), held=f"in review at {url}")

    if pull_request.state == "MERGED" and state.path in pull_request.files:
        return _settle_merge(
            ctx,
            page,
            state,
            url=url,
            pull_request=pull_request,
            status=status,
            doc_gone=doc_gone,
            discarding=discarding,
        )

    left = dataclasses.replace(state, pr_url=None, pulled_export=None)
    row = {"PR": "", NOT_APPLIED_COLUMN: f"PR {url} closed without merging this page"}
    if status != Status.DISCARD:
        row[STATUS_COLUMN] = Status.EDITING
    return _Settled(_Result(left, row))


def _settle_merge(
    ctx: Context,
    page: SyncPage,
    state: PageState,
    *,
    url: str,
    pull_request: PullRequest,
    status: str | None,
    doc_gone: bool,
    discarding: bool,
) -> _Settled:
    """Settle the page's pull request `url`, merged with its path (see `_settle`)."""
    merge = pull_request.merge_commit
    if merge is None:
        raise GhError(["gh", "pr", "view", url], "MERGED with no merge commit")
    try:
        landed = _holds(page, merge)
    except GitError:
        if not discarding:
            raise
        landed = False

    left = dataclasses.replace(state, pr_url=None, pulled_export=None)
    row = {"PR": ""}
    if not landed:
        if not discarding:
            return _Settled(
                _Result(state),
                held=f"{url} merged; waiting for {page.ref} to include {merge[:12]}",
            )
        row[NOT_APPLIED_COLUMN] = (
            f"PR {url} merged into a branch this page is not read from; edits discarded"
        )
        return _Settled(_Result(left, row))

    applied = dataclasses.replace(left, applied_export=state.pulled_export)
    later = not doc_gone and not _same_content(
        google.export_settled(ctx.session, state.doc_id), _reference(applied)
    )
    row[NOT_APPLIED_COLUMN] = (
        f"PR {url} merged; later edits in this Doc go in the next PR" if later else ""
    )
    if status == Status.PR_OPEN:
        row[STATUS_COLUMN] = Status.EDITING if later else Status.MERGED
    return _Settled(_Result(applied, row), merged=True)


def _is_open(ctx: Context, repo: str, url: str) -> bool:
    return any(item.url == url for item in ctx.open_pull_requests(repo))


def _holds(page: SyncPage, commit: str) -> bool:
    """Whether the page's source commit has `commit` in its history.

    Raises:
        GitError: the clone lacks `commit`, or git failed otherwise.
    """
    args = ("merge-base", "--is-ancestor", commit, page.commit)
    result = _clone_git(page.clone_root).run_unchecked(*args)
    if result.returncode in {0, 1}:
        return result.returncode == 0
    raise GitError(["git", *args], result.stderr)


# pull


@dataclass(frozen=True)
class _Pulled:
    """One page's pulled Doc: its edits merged onto the current source.

    `text` is None when the merge changes nothing: every edit was reported and left
    out, or is already upstream. `entry.refusals` is not empty when a part of the page
    was left unchanged; a page that sends nothing then holds its Doc as it is.
    """

    page: SyncPage
    state: PageState
    export: str
    text: str | None
    entry: PageEntry


def pull(
    ctx: Context,
    *,
    pages: Sequence[SyncPage],
    store: StateStore,
    log: RunLog,
    dry_run_dir: Path | None,
) -> None:
    """Send the edits of every page whose Status is Ready for review, one PR per repository.

    Each page's pull request is settled first (see `_settle`). A page whose pull request
    is still open is skipped. A Ready page whose file an open docsync pull request
    changes fails: sending it would put it in two pull requests. A Ready page whose Doc
    holds no edit since docsync last wrote it or applied its edits keeps its state; its
    Status becomes Merged when this run settled its merge and Editing otherwise, and
    the Not applied column says there is nothing to send. The rest are read and their
    edits merged onto the current source: the edits made since
    `applied_export`, so text a reviewer changed in a merged pull request stays. Each
    repository's pages that change their source go in one new pull request, and their
    Status becomes PR open. A page whose edits change nothing records its export as
    applied, its Status becomes Editing, and its reports, or a note that its edits are
    already in GitHub, go to the Not applied column. A page that sends nothing and has
    a refusal (a part of the page left unchanged, quoting the Doc's text) records no
    export as applied: its Doc keeps the editor's text, `push` leaves it as it is, and
    the Not applied column quotes each refusal and says to rework the edit or discard
    it. A page whose merged file `push` could not read sends nothing and is treated
    the same way, with one refusal naming the error, and fails the run. A report of an
    applied edit (an anchor change or an Author note flag) that an earlier pull
    request carried is not repeated; every other report is. A page that sends a pull
    request shows its refusals there.

    With `dry_run_dir`, each repository's files and PR body go under
    `<dry_run_dir>/<owner>__<name>/` and no state, Sheet, git or gh write happens.

    Raises:
        UnsavedStateError: the state save failed; the changed states are in a file.
    """
    states = store.load()
    rows = _rows_by_page(ctx)
    changed: dict[str, PageState] = {}
    fields: dict[str, dict[str, str]] = {}

    def record(page_id: str, result: _Result) -> None:
        if result.state != states.get(page_id):
            changed[page_id] = result.state
        if result.row:
            fields.setdefault(page_id, {}).update(result.row)

    by_repo: dict[str, list[_Pulled]] = {}
    try:
        for page in pages:
            try:
                pulled = _pull_page(
                    ctx,
                    page,
                    state=states.get(page.page_id),
                    row=rows.get(page.page_id) or {},
                    record=record,
                    log=log,
                )
            except _PAGE_ERRORS as exc:
                log.fail(page.page_id, str(exc))
                continue
            if pulled is None:
                continue
            if pulled.text is not None:
                by_repo.setdefault(page.repo, []).append(pulled)
                continue
            update = {
                "Last pulled": ctx.now,
                NOT_APPLIED_COLUMN: _not_applied(pulled.entry),
                STATUS_COLUMN: Status.EDITING,
            }
            # A refused edit leaves the Doc holding the editor's text, so the export
            # stays unapplied and the next push keeps that text.
            applied = (
                pulled.state
                if pulled.entry.refusals
                else dataclasses.replace(pulled.state, applied_export=pulled.export)
            )
            record(page.page_id, _Result(applied, update))

        branch = edits_branch(datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
        for repo, pulled in by_repo.items():
            if len({item.page.clone_root for item in pulled}) > 1:
                log.fail(repo, "pages of this repository come from more than one clone")
                continue
            try:
                url = _propose(
                    repo,
                    pulled,
                    branch=branch,
                    author=ctx.pr_author,
                    dry_run_dir=dry_run_dir,
                )
            except (PrError, NoChangesError) as exc:
                log.fail(repo, str(exc))
                continue
            log.info(repo, f"opened {url}")
            for item in pulled:
                sent = dataclasses.replace(
                    item.state, pulled_export=item.export, pr_url=url
                )
                record(
                    item.page.page_id,
                    _Result(
                        sent,
                        {
                            "PR": url,
                            "Last pulled": ctx.now,
                            STATUS_COLUMN: Status.PR_OPEN,
                            NOT_APPLIED_COLUMN: "",
                        },
                    ),
                )
    finally:
        if dry_run_dir is None:
            _save(store, states, changed, message=f"docsync pull: {len(changed)} pages")
            _write_rows(
                ctx, [{KEY_COLUMN: page_id, **row} for page_id, row in fields.items()]
            )


def _pull_page(
    ctx: Context,
    page: SyncPage,
    *,
    state: PageState | None,
    row: Mapping[str, str],
    record: Callable[[str, _Result], None],
    log: RunLog,
) -> _Pulled | None:
    """Settle one page and read its Doc's edits, or return None when there are none to read.

    The settled state and Sheet fields go to `record` before the Doc is read, so a
    failure reading it keeps them.

    A Ready page whose file an open docsync pull request changes fails: after settling,
    its state names no open pull request, so that one is a reviewer's commit touching
    the file, a reopened pull request, or one whose creation docsync did not record.

    Raises:
        CommandError: git or gh failed while settling.
    """
    status = row.get(STATUS_COLUMN)
    if state is None:
        if status == Status.READY:
            log.fail(page.page_id, "no state for this page; push it first")
        return None

    settled = _settle(ctx, page, state, status=status)
    record(page.page_id, settled.result)
    if settled.held is not None:
        log.info(page.page_id, f"not pulled: {settled.held}")
        return None
    if settled.result.row.get(STATUS_COLUMN, status) != Status.READY:
        return None
    return _read_ready(
        ctx, page, settled=settled, owner=row.get("Owner"), record=record, log=log
    )


def _read_ready(
    ctx: Context,
    page: SyncPage,
    *,
    settled: _Settled,
    owner: str | None,
    record: Callable[[str, _Result], None],
    log: RunLog,
) -> _Pulled | None:
    """Read a settled Ready page's Doc, or return None when it is not sent (see `pull`)."""
    state = settled.result.state
    if claim := _open_claim(ctx, page):
        log.fail(
            page.page_id,
            f"{page.path} is changed in open PR {claim}; merge or close that PR, or"
            " revert the file on its branch, before sending this page",
        )
        return None
    if google.open_suggestion_ids(ctx.session, state.doc_id):
        log.info(
            page.page_id,
            "not pulled: the Doc has open suggestions; accept or reject them first",
        )
        return None
    export = google.export_settled(ctx.session, state.doc_id)
    if _same_content(export, _reference(state)):
        log.info(page.page_id, "no edits to send")
        status = Status.MERGED if settled.merged else Status.EDITING
        record(
            page.page_id,
            _Result(
                state, {STATUS_COLUMN: status, NOT_APPLIED_COLUMN: NOTHING_TO_SEND}
            ),
        )
        return None
    return _read_edits(page, state=state, export=export, owner=owner, log=log)


def _open_claim(ctx: Context, page: SyncPage) -> str | None:
    """The open docsync pull request that changes the page's file, if any."""
    for item in ctx.open_pull_requests(page.repo):
        if page.path in item.files:
            return item.url
    return None


def _read_edits(
    page: SyncPage, *, state: PageState, export: str, owner: str | None, log: RunLog
) -> _Pulled:
    """Merge the edits in the Doc's `export` onto the current source.

    The edits are those since `applied_export` (or since the baseline when no edit is
    applied): the text docsync last proposed for the Doc stands in for the pushed
    source in the three-way merge, so the current source's changes to it, a
    reviewer's included, survive. The reports exclude the applied-edit kinds
    (`_MERGED_KINDS`) that reading `applied_export` produced too, since an earlier
    pull request carried them.

    When the merged file is one `push` cannot read, nothing is sent for the page, the
    run fails it, and a refusal with no quote names the error.
    """
    pushed = _pushed_text(page, state)
    applied = (
        None
        if state.applied_export is None
        else apply_edits(
            page=page.page_id,
            source=pushed,
            baseline=state.baseline,
            edited=state.applied_export,
        )
    )
    edited = apply_edits(
        page=page.page_id, source=pushed, baseline=state.baseline, edited=export
    )
    merged = merge_onto_current(
        pushed=pushed if applied is None else applied.text,
        edited=edited.text,
        current=page.text,
    )
    fresh = _unseen_reports(edited.reports, () if applied is None else applied.reports)
    text = None if merged.text == page.text else merged.text
    error = None if text is None else _unreadable(text)
    if error is not None:
        text = None
        fresh = [r for r in fresh if r.kind not in _MERGED_KINDS]
    reports = [r.message for r in fresh if r.kind is not ReportKind.REFUSED]
    refusals = [
        Refusal(r.message, r.quote) for r in fresh if r.kind is ReportKind.REFUSED
    ]
    for message in (*reports, *(refusal.message for refusal in refusals)):
        log.info(page.page_id, f"report: {message}")
    if error is not None:
        unreadable = (
            f"the edits would leave a file docsync cannot read: {error}; nothing sent"
        )
        refusals.insert(0, Refusal(unreadable))
        log.fail(page.page_id, unreadable)
    if text is None:
        if error is None:
            log.info(page.page_id, "no edits to send")
    elif merged.clashes:
        log.info(page.page_id, f"{len(merged.clashes)} clashes with upstream flagged")
    return _Pulled(
        page=page,
        state=state,
        export=export,
        text=text,
        entry=PageEntry(
            title=page.title,
            doc_url=_doc_url(state.doc_id),
            owner=owner or None,
            reports=tuple(reports),
            refusals=tuple(refusals),
            clashes=merged.clashes,
        ),
    )


def _unseen_reports(reports: Iterable[Report], seen: Iterable[Report]) -> list[Report]:
    """`reports` less one match for each `_MERGED_KINDS` report of `seen`.

    A match has the same kind, message, and source block span. Two reports that read
    alike, such as the flags of two Author notes, differ by span, so the second note's
    flag survives when the first one's was carried.
    """
    pending = Counter((r.kind, r.message, r.block.span) for r in seen)
    fresh = []
    for report in reports:
        key = (report.kind, report.message, report.block.span)
        if report.kind in _MERGED_KINDS and pending[key] > 0:
            pending[key] -= 1
        else:
            fresh.append(report)
    return fresh


def _not_applied(entry: PageEntry) -> str:
    """The Not applied cell for a page that sends nothing.

    Each refusal gives its message and the Doc's text it left unchanged, the other
    reports follow, and `HOLD_ADVICE` closes when there is a refusal. The cell holds
    at most `NOT_APPLIED_LIMIT` characters when the quotes can bring it there: they
    are cut, each ending with a line saying so (see `render_within`).
    """
    quotes = sum(1 for refusal in entry.refusals if refusal.quote)
    return render_within(
        lambda keep: _not_applied_cell(entry, keep=keep),
        limit=NOT_APPLIED_LIMIT,
        quotes=quotes,
    )


def _not_applied_cell(entry: PageEntry, *, keep: int | None) -> str:
    parts = [
        f"{refusal.message}\nThe Doc has:\n{shorten_quote(refusal.quote, keep=keep)}"
        if refusal.quote
        else refusal.message
        for refusal in entry.refusals
    ]
    parts.extend(entry.reports)
    if entry.refusals:
        parts.append(HOLD_ADVICE)
    return " | ".join(parts or (NOTHING_TO_SEND,))


def _unreadable(text: str) -> BlockError | None:
    """The error `push` would hit reading the source `text`, if any."""
    try:
        to_doc_markdown(text)
    except BlockError as exc:
        return exc
    return None


def _propose(
    repo: str,
    pulled: Sequence[_Pulled],
    *,
    branch: str,
    author: str,
    dry_run_dir: Path | None,
) -> str:
    """Open `repo`'s pull request for `pulled` on `branch`; return its URL.

    Raises:
        PrError: a git or gh command failed, or the base branch changed a file after
            the commit its text was built on (`StaleBaseError`).
        NoChangesError: every file already equals its text on the base branch.
    """
    first = pulled[0].page
    return propose_edits(
        clone_root=first.clone_root,
        repo=repo,
        base=HUB_BASE if first.page_id.partition("/")[0] == HUB else first.ref,
        branch=branch,
        files={
            item.page.path: EditedFile(text=item.text, built_on=item.page.commit)
            for item in pulled
            if item.text is not None
        },
        title=PR_TITLE,
        body=render_pr_body([item.entry for item in pulled]),
        author=author,
        dry_run_dir=None
        if dry_run_dir is None
        else dry_run_dir / repo.replace("/", "__"),
    )


# restore


def restore(
    path: Path,
    *,
    store: StateStore,
    pages: Sequence[str] = (),
    force: bool = False,
) -> None:
    """Save the page states in `path` over the stored ones.

    `path` is a file a run that could not save state wrote (see `_save`): the store's
    tip that run loaded, and its changed page states keyed by page id. Every entry is
    validated before anything is saved, so a malformed file restores nothing.

    When the store's tip differs from the one the run loaded, a later run saved
    state, and the file's states may be older than the stored ones, so restore refuses
    unless `pages` names the pages to restore or `force` is set.

    Raises:
        StateFormatError: the file is unreadable, not of that shape, or holds a
            malformed entry.
        UnknownPageError: `pages` names a page the file does not hold.
        StateMovedError: the store moved since the run loaded it, and neither `pages`
            nor `force` is given.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise StateFormatError(str(path), f"cannot read: {exc}") from exc
    if not (
        isinstance(data, dict)
        and set(data) == {"loaded_tip", "states"}
        and isinstance(data["states"], dict)
        and isinstance(data["loaded_tip"], str | None)
    ):
        raise StateFormatError(
            str(path),
            "expected a JSON object with loaded_tip and states keyed by page id",
        )
    restored = {
        page_id: state_from_json(entry, file=f"{path}: {page_id}", page_id=page_id)
        for page_id, entry in sorted(data["states"].items())
    }
    if unknown := sorted(set(pages) - set(restored)):
        raise UnknownPageError(f"{path} holds no state for {', '.join(unknown)}")
    if pages:
        restored = {page_id: restored[page_id] for page_id in sorted(set(pages))}

    states = store.load()
    loaded, current = data["loaded_tip"], store.tip()
    if current != loaded and not (pages or force):
        raise StateMovedError(
            f"state moved since the failed run ({_short(loaded)} → {_short(current)});"
            " restore page by page with --page, or overwrite with --force"
        )
    for page_id in restored:
        replaced = (
            "replaced its stored state" if page_id in states else "no stored state"
        )
        print(f"{page_id}: restored ({replaced})")
    store.save(
        {**states, **restored},
        message=f"docsync restore: {len(restored)} pages from {path.name}",
    )


def _short(tip: str | None) -> str:
    return "empty" if tip is None else tip[:12]


# Shared


def _rows_by_page(ctx: Context) -> dict[str, dict[str, str]]:
    """The Pages tab's rows keyed by Page id; rows without one are skipped.

    Raises:
        SheetLayoutError: the tab has no Page id or Status column, or two rows share a
            Page id.
    """
    rows = google.read_rows(ctx.session, ctx.sheet_id, tab=PAGES_TAB)
    if rows and (
        missing := [c for c in (KEY_COLUMN, STATUS_COLUMN) if c not in rows[0]]
    ):
        raise SheetLayoutError(
            f"tab {PAGES_TAB!r} has no {' or '.join(missing)} column"
        )
    by_page: dict[str, dict[str, str]] = {}
    for row in rows:
        if not (page_id := row.get(KEY_COLUMN)):
            continue
        if page_id in by_page:
            raise SheetLayoutError(
                f"tab {PAGES_TAB!r} lists {KEY_COLUMN} {page_id!r} more than once"
            )
        by_page[page_id] = row
    return by_page


def _write_rows(ctx: Context, rows: Sequence[Mapping[str, str]]) -> None:
    if rows:
        google.upsert_rows(
            ctx.session,
            ctx.sheet_id,
            tab=PAGES_TAB,
            key_column=KEY_COLUMN,
            rows=rows,
        )


def _save(
    store: StateStore,
    states: Mapping[str, PageState],
    changed: Mapping[str, PageState],
    *,
    message: str,
) -> None:
    """Save `changed` over `states`; on failure write `changed` to a local file.

    The file also records the store's tip this run loaded, so `restore` can tell
    whether a later run saved state over it.

    Raises:
        UnsavedStateError: the save failed; names the file holding `changed`.
    """
    if not changed:
        return
    try:
        store.save({**states, **changed}, message=message)
    except Exception as exc:
        # Any failure here loses Drive writes already made, so keep them whatever it is.
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = Path.cwd() / UNSAVED_STATES_FILE.format(stamp=stamp)
        payload = {
            "loaded_tip": store.tip(),
            "states": {
                page_id: dataclasses.asdict(state)
                for page_id, state in sorted(changed.items())
            },
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        raise UnsavedStateError(
            f"{type(exc).__name__}: {exc}. The {len(changed)} page states this run"
            f" changed are in {path}; restore them into the state store before the"
            " next run"
        ) from exc


def _script_row(page: SyncPage, state: PageState) -> dict[str, str]:
    return {
        KEY_COLUMN: page.page_id,
        "Title": page.title,
        "Section": " / ".join(page.section_path),
        "Doc": _doc_url(state.doc_id),
        "PR": state.pr_url or "",
        "Repo": page.repo,
        "File": page.path,
    }


def _pushed_text(page: SyncPage, state: PageState) -> str:
    """The page's source file as it was pushed."""
    return _clone_git(page.clone_root).run(
        "show", f"{state.source_commit}:{state.path}"
    )


def _clone_git(root: Path) -> Git:
    """A git runner for a page's clone, with the process environment's credentials."""
    return Git(root=root, env=command_env(None))


def _doc_url(doc_id: str) -> str:
    return DOC_URL.format(doc_id=doc_id)


def _ids(files: Iterable[DriveFile]) -> str:
    return ", ".join(file.id for file in files)
