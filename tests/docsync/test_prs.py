"""Tests for dfo_docs.docsync.prs: the docsync branch, its pull request, and the body.

Remotes are local bare repositories and `gh` is a fake on PATH that records each call
to a JSON-lines log, so nothing reaches the network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dfo_docs.docsync.git import command_env
from dfo_docs.docsync.prs import (
    BODY_LIMIT,
    TOKEN_ENV,
    Clash,
    EditedFile,
    GhError,
    GitError,
    GitIdentity,
    NoChangesError,
    OpenPullRequest,
    PageEntry,
    PrError,
    PullRequest,
    Refusal,
    StaleBaseError,
    edits_branch,
    list_open_pull_requests,
    propose_edits,
    render_pr_body,
    shorten_quote,
    view_pull_request,
)

REPO = "DevelopmentFinanceObservatory/apis"
PR_URL = "https://github.com/DevelopmentFinanceObservatory/apis/pull/7"
BOT = GitIdentity(name="dfo-docsync[bot]", email="dfo-docsync@users.noreply.github.com")
BRANCH = edits_branch("20261001T090000Z")
WJ = "\u2060"
AUTHOR = "app/dfo-docsync"

_FAKE_GH = f"""#!{sys.executable}
import json, os, sys
state = os.environ["FAKE_GH_STATE"]
args = sys.argv[1:]
body = sys.stdin.read() if "--body-file" in args else None
with open(os.path.join(state, "calls.jsonl"), "a") as log:
    log.write(json.dumps({{"args": args, "stdin": body,
                           "gh_token": os.environ.get("GH_TOKEN")}}) + "\\n")
if os.environ.get("FAKE_GH_FAIL"):
    sys.stderr.write("HTTP 403: Resource not accessible by integration\\n")
    sys.exit(1)
reply = os.path.join(state, "reply.json")
if args[:2] in (["pr", "list"], ["pr", "view"]):
    print(open(reply).read())
elif args[:2] == ["pr", "create"]:
    if os.environ.get("FAKE_GH_CREATE_FAIL"):
        sys.stderr.write("HTTP 502: Bad Gateway\\n")
        sys.exit(1)
    print("Creating pull request")
    print({PR_URL!r})
"""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _commit(clone: Path, files: dict[str, str], message: str) -> str:
    for name, text in files.items():
        path = clone / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    _git(clone, "add", "-A")
    _git(clone, "commit", "-q", "-m", message)
    return _git(clone, "rev-parse", "HEAD")


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A bare remote whose `main` holds two docs pages and a script."""
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", str(bare), str(seed))
    _identity(seed)
    _commit(
        seed,
        {
            "docs/guide/index.md": "# Guide\n\nOld intro.\n",
            "docs/guide/use.md": "# Use\n\nOld use.\n",
            "run.sh": "#!/bin/sh\necho hi\n",
        },
        "seed",
    )
    (seed / "run.sh").chmod(0o755)
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "make run.sh executable")
    _git(seed, "push", "-q", "origin", "main")
    return bare


@pytest.fixture
def clone(tmp_path: Path, remote: Path) -> Path:
    path = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(remote), str(path))
    _identity(path)
    return path


@pytest.fixture
def gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Install the fake gh on PATH; return the directory holding its log and state."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "gh"
    script.write_text(_FAKE_GH)
    script.chmod(0o755)
    state = tmp_path / "gh-state"
    state.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_STATE", str(state))
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    return state


def _identity(repo: Path) -> None:
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def _calls(state: Path) -> list[dict[str, object]]:
    log = state / "calls.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def _propose(
    clone: Path,
    files: dict[str, str],
    *,
    base: str = "main",
    branch: str = BRANCH,
    built_on: str | None = None,
    token: str | None = None,
    dry_run_dir: Path | None = None,
) -> str:
    """Propose `files`, each built on `built_on` (the clone's `origin/main` by default)."""
    commit = built_on or _git(clone, "rev-parse", "origin/main")
    return propose_edits(
        clone_root=clone,
        repo=REPO,
        base=base,
        branch=branch,
        files={
            path: EditedFile(text=text, built_on=commit) for path, text in files.items()
        },
        title="Docs edits from Google Docs",
        body="Body text.\n",
        author=AUTHOR,
        identity=BOT,
        token=token,
        dry_run_dir=dry_run_dir,
    )


def _changed(remote: Path, base: str, branch: str = BRANCH) -> list[str]:
    diff = _git(remote, "diff", "--name-only", base, branch)
    return diff.splitlines()


def test_creates_branch_one_commit_over_base_and_opens_pr(
    clone: Path, remote: Path, gh: Path
) -> None:
    edited = "# Guide\n\nNew intro, edited in Docs.\n"
    url = _propose(
        clone, {"docs/guide/index.md": edited, "docs/guide/new.md": "# New\n"}
    )

    assert url == PR_URL
    main = _git(remote, "rev-parse", "main")
    assert _git(remote, "rev-parse", f"{BRANCH}^") == main
    assert _git(remote, "show", f"{BRANCH}:docs/guide/index.md") + "\n" == edited
    assert sorted(_changed(remote, "main")) == [
        "docs/guide/index.md",
        "docs/guide/new.md",
    ]
    author = _git(remote, "log", "-1", "--format=%an <%ae>|%cn|%s", BRANCH)
    assert author == (
        "dfo-docsync[bot] <dfo-docsync@users.noreply.github.com>|dfo-docsync[bot]|"
        "Docs edits from Google Docs"
    )

    (create,) = _calls(gh)
    args = create["args"]
    assert args[:2] == ["pr", "create"]
    assert args[args.index("--base") + 1] == "main"
    assert args[args.index("--head") + 1] == BRANCH
    assert create["stdin"] == "Body text.\n"


def test_never_pushes_over_an_existing_branch(
    tmp_path: Path, clone: Path, remote: Path, gh: Path
) -> None:
    _propose(clone, {"docs/guide/index.md": "# Guide\n\nFirst run.\n"})
    review = tmp_path / "review"
    _git(tmp_path, "clone", "-q", "-b", BRANCH, str(remote), str(review))
    _identity(review)
    reviewed = _commit(review, {"docs/guide/index.md": "# Guide\n\nReviewed.\n"}, "r")
    _git(review, "push", "-q", "origin", BRANCH)

    with pytest.raises(GitError) as caught:
        _propose(clone, {"docs/guide/use.md": "# Use\n\nSecond run.\n"})

    assert caught.value.command[:2] == ("git", "push")
    assert _git(remote, "rev-parse", BRANCH) == reviewed
    assert [call["args"][:2] for call in _calls(gh)] == [["pr", "create"]]


def test_a_later_run_opens_a_new_branch_on_the_current_base(
    tmp_path: Path, clone: Path, remote: Path, gh: Path
) -> None:
    _propose(clone, {"docs/guide/index.md": "# Guide\n\nFirst run.\n"})
    first = _git(remote, "rev-parse", BRANCH)

    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(remote), str(other))
    _identity(other)
    upstream = _commit(other, {"docs/guide/use.md": "# Use\n\nUpstream.\n"}, "up")
    _git(other, "push", "-q", "origin", "main")

    later = edits_branch("20261002T090000Z")
    _propose(
        clone,
        {"docs/guide/use.md": "# Use\n\nSecond run.\n"},
        branch=later,
        built_on=upstream,
    )

    assert _git(remote, "rev-parse", BRANCH) == first
    assert _git(remote, "rev-parse", f"{later}^") == upstream
    assert _changed(remote, "main", later) == ["docs/guide/use.md"]


@pytest.mark.parametrize("branch", ["docsync/edits", "docsync/edits-", "main"])
def test_rejects_a_branch_outside_the_docsync_prefix(
    clone: Path, gh: Path, branch: str
) -> None:
    with pytest.raises(ValueError, match="not a docsync edits branch"):
        _propose(clone, {"docs/guide/index.md": "x\n"}, branch=branch)
    assert _calls(gh) == []


def test_refuses_when_base_changed_a_file_after_its_text_was_built(
    tmp_path: Path, clone: Path, remote: Path, gh: Path
) -> None:
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(remote), str(other))
    _identity(other)
    _commit(other, {"docs/guide/index.md": "# Guide\n\nUpstream fix.\n"}, "up")
    _git(other, "push", "-q", "origin", "main")
    refs_before = _git(remote, "for-each-ref")

    with pytest.raises(StaleBaseError) as caught:
        _propose(
            clone,
            {
                "docs/guide/index.md": "# Guide\n\nOld intro, edited.\n",
                "docs/guide/use.md": "# Use\n\nEdited.\n",
            },
        )

    assert caught.value.paths == ("docs/guide/index.md",)
    assert _git(remote, "for-each-ref") == refs_before
    assert _calls(gh) == []


def test_stale_base_error_is_a_pr_error() -> None:
    error = StaleBaseError(base="dev", paths=["a.md"])
    assert isinstance(error, PrError)
    assert str(error) == (
        "dev changed a.md after this run read them; the next run proposes against"
        " the new text"
    )


def test_proposes_against_base_not_the_checked_out_branch(
    clone: Path, remote: Path, gh: Path
) -> None:
    _git(clone, "checkout", "-q", "-b", "feat/local")
    local_head = _commit(clone, {"docs/guide/local.md": "# Local\n"}, "local only")
    (clone / "docs/guide/use.md").write_text("uncommitted work\n")
    status = _git(clone, "status", "--porcelain")

    _propose(clone, {"docs/guide/index.md": "# Guide\n\nEdited.\n"})

    assert _git(remote, "rev-parse", f"{BRANCH}^") == _git(remote, "rev-parse", "main")
    assert _changed(remote, "main") == ["docs/guide/index.md"]
    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD") == "feat/local"
    assert _git(clone, "rev-parse", "HEAD") == local_head
    assert _git(clone, "status", "--porcelain") == status
    assert (clone / "docs/guide/index.md").read_text() == "# Guide\n\nOld intro.\n"


def test_targets_a_non_default_base(clone: Path, remote: Path, gh: Path) -> None:
    _git(clone, "push", "-q", "origin", "main:dev")

    _propose(clone, {"docs/guide/index.md": "# Guide\n\nOn dev.\n"}, base="dev")

    assert _git(remote, "rev-parse", f"{BRANCH}^") == _git(remote, "rev-parse", "dev")
    create = _calls(gh)[0]["args"]
    assert create[create.index("--base") + 1] == "dev"


def test_keeps_the_mode_of_an_existing_file(
    clone: Path, remote: Path, gh: Path
) -> None:
    _propose(clone, {"run.sh": "#!/bin/sh\necho edited\n"})

    assert _git(remote, "ls-tree", BRANCH, "--", "run.sh").startswith("100755")


def test_builds_the_commit_in_a_partial_sparse_clone(
    tmp_path: Path, remote: Path, gh: Path
) -> None:
    _git(remote, "config", "uploadpack.allowFilter", "true")
    partial = tmp_path / "partial"
    _git(
        tmp_path,
        "clone", "-q", "--filter=blob:none", "--sparse", f"file://{remote}", str(partial),
    )  # fmt: skip
    _identity(partial)

    propose_edits(
        clone_root=partial,
        repo=REPO,
        base="main",
        branch=BRANCH,
        files={
            "docs/guide/index.md": EditedFile(
                text="# Guide\n\nPartial.\n",
                built_on=_git(partial, "rev-parse", "origin/main"),
            )
        },
        title="t",
        body="b",
        author=AUTHOR,
        identity=BOT,
    )

    assert _changed(remote, "main") == ["docs/guide/index.md"]


def test_files_equal_to_base_raise(clone: Path, gh: Path) -> None:
    with pytest.raises(NoChangesError):
        _propose(clone, {"docs/guide/index.md": "# Guide\n\nOld intro.\n"})
    assert _calls(gh) == []


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "../outside.md", "docs/../../x.md", ""]
)
def test_rejects_paths_outside_the_repository(clone: Path, gh: Path, path: str) -> None:
    with pytest.raises(ValueError, match="repo-relative"):
        _propose(clone, {path: "text\n"})


def test_rejects_empty_files(clone: Path, gh: Path) -> None:
    with pytest.raises(ValueError, match="no files"):
        _propose(clone, {})


def test_git_failure_raises_git_error_with_stderr(clone: Path, gh: Path) -> None:
    with pytest.raises(GitError) as caught:
        _propose(clone, {"docs/guide/index.md": "x\n"}, base="no-such-branch")
    assert "no-such-branch" in caught.value.stderr
    assert caught.value.command[:2] == ("git", "fetch")


def test_gh_failure_raises_gh_error_with_stderr(
    clone: Path, gh: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_GH_FAIL", "1")
    with pytest.raises(GhError, match="Resource not accessible") as caught:
        _propose(clone, {"docs/guide/index.md": "x\n"})
    assert caught.value.command[:3] == ("gh", "pr", "create")


@pytest.mark.parametrize(("listed", "found"), [([{"url": PR_URL}], True), ([], False)])
def test_failed_create_looks_the_pr_up_by_its_branch(
    clone: Path,
    gh: Path,
    monkeypatch: pytest.MonkeyPatch,
    listed: list[dict[str, str]],
    found: bool,
) -> None:
    """gh can create the pull request and still exit non-zero."""
    monkeypatch.setenv("FAKE_GH_CREATE_FAIL", "1")
    (gh / "reply.json").write_text(json.dumps(listed))

    if found:
        assert _propose(clone, {"docs/guide/index.md": "x\n"}) == PR_URL
    else:
        with pytest.raises(GhError, match="Bad Gateway"):
            _propose(clone, {"docs/guide/index.md": "x\n"})

    create, lookup = (call["args"] for call in _calls(gh))
    assert create[:2] == ["pr", "create"]
    assert lookup[:2] == ["pr", "list"]
    assert lookup[lookup.index("--head") + 1] == BRANCH
    assert lookup[lookup.index("--author") + 1] == AUTHOR
    assert lookup[lookup.index("--state") + 1] == "open"


def test_token_reaches_gh_and_git_only_through_the_environment(
    clone: Path, remote: Path, gh: Path
) -> None:
    _git(clone, "config", "credential.helper", "!echo password=from-config-file; :")
    config_before = (clone / ".git" / "config").read_text()

    _propose(clone, {"docs/guide/index.md": "x\n"}, token="ghs_secret")

    assert {call["gh_token"] for call in _calls(gh)} == {"ghs_secret"}
    assert (clone / ".git" / "config").read_text() == config_before
    assert _git(clone, "remote", "get-url", "origin") == str(remote)
    assert "ghs_secret" not in config_before


def test_token_credential_helper_answers_github_with_the_token(
    clone: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    _git(clone, "config", "credential.helper", "!echo password=from-config-file; :")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.abbrev")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "12")

    env = command_env("ghs_secret")
    filled = subprocess.run(
        ["git", "credential", "fill"],
        cwd=clone,
        env=env,
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert "username=x-access-token" in filled
    assert "password=ghs_secret" in filled
    assert env["GIT_CONFIG_KEY_0"] == "core.abbrev"
    assert env["GIT_CONFIG_COUNT"] == "3"


def test_token_defaults_to_the_environment(
    clone: Path, gh: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(TOKEN_ENV, "ghs_from_env")
    _propose(clone, {"docs/guide/index.md": "x\n"})
    assert {call["gh_token"] for call in _calls(gh)} == {"ghs_from_env"}


def test_no_token_leaves_gh_on_its_own_credentials(clone: Path, gh: Path) -> None:
    _propose(clone, {"docs/guide/index.md": "x\n"})
    assert {call["gh_token"] for call in _calls(gh)} == {None}


def test_dry_run_writes_files_and_body_and_touches_no_remote(
    tmp_path: Path, clone: Path, remote: Path, gh: Path
) -> None:
    refs_before = _git(remote, "for-each-ref")
    out = tmp_path / "dry"

    url = _propose(clone, {"docs/guide/index.md": "# Guide\n\nDry.\n"}, dry_run_dir=out)

    assert url == (out / "pr.md").resolve().as_uri()
    assert (out / "files/docs/guide/index.md").read_text() == "# Guide\n\nDry.\n"
    assert (
        out / "pr.md"
    ).read_text() == "# Docs edits from Google Docs\n\nBody text.\n"
    assert _git(remote, "for-each-ref") == refs_before
    assert _calls(gh) == []


def test_list_open_pull_requests_keeps_the_authors_docsync_branches(
    gh: Path,
) -> None:
    (gh / "reply.json").write_text(
        json.dumps(
            [
                {
                    "url": PR_URL,
                    "headRefName": BRANCH,
                    "files": [{"path": "docs/a.md"}, {"path": "docs/b.md"}],
                },
                {"url": "u2", "headRefName": "feat/other", "files": []},
            ]
        )
    )

    listed = list_open_pull_requests(REPO, author="app/dfo-docsync", token="ghs_secret")

    assert listed == (
        OpenPullRequest(
            url=PR_URL, branch=BRANCH, files=frozenset({"docs/a.md", "docs/b.md"})
        ),
    )
    ((call),) = _calls(gh)
    args = call["args"]
    assert args[:2] == ["pr", "list"]
    assert args[args.index("--repo") + 1] == REPO
    assert args[args.index("--state") + 1] == "open"
    assert args[args.index("--author") + 1] == "app/dfo-docsync"
    assert call["gh_token"] == "ghs_secret"


def test_list_open_pull_requests_refuses_output_that_is_not_a_list(gh: Path) -> None:
    (gh / "reply.json").write_text("{}")
    with pytest.raises(GhError, match="no JSON list"):
        list_open_pull_requests(REPO, author="app/dfo-docsync")


def test_view_pull_request_reads_state_files_and_merge_commit(gh: Path) -> None:
    (gh / "reply.json").write_text(
        json.dumps(
            {
                "state": "MERGED",
                "files": [{"path": "docs/a.md"}],
                "mergeCommit": {"oid": "c" * 40},
            }
        )
    )

    assert view_pull_request(PR_URL) == PullRequest(
        state="MERGED", files=frozenset({"docs/a.md"}), merge_commit="c" * 40
    )
    assert _calls(gh)[0]["args"] == [
        "pr", "view", PR_URL, "--json", "state,files,mergeCommit",
    ]  # fmt: skip


def test_view_pull_request_failure_raises_gh_error(
    gh: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_GH_FAIL", "1")
    with pytest.raises(GhError, match="Resource not accessible"):
        view_pull_request(PR_URL)


def test_render_pr_body() -> None:
    body = render_pr_body(
        [
            PageEntry(
                title="Get data",
                doc_url="https://docs.google.com/document/d/abc/edit",
                owner="Ana",
                reports=["Code block edit at line 12 was not applied."],
                clashes=[
                    Clash(
                        editor_text="Editor ```x``` words.", upstream_text="Upstream."
                    )
                ],
            ),
            PageEntry(
                title="Use",
                doc_url="https://docs.google.com/document/d/def/edit",
                owner=None,
            ),
        ]
    )

    assert body == (
        "Edits made in Google Docs, applied to the source files by docsync. "
        "Review each page below before merging.\n"
        "\n"
        "## `Get data`\n"
        "\n"
        "[Google Doc](https://docs.google.com/document/d/abc/edit) · Owner: `Ana`\n"
        "\n"
        "Reports:\n"
        "\n"
        "- `Code block edit at line 12 was not applied.`\n"
        "\n"
        "**Flagged clash 1.** The editor and upstream both changed this block. "
        "This pull request applies the editor's text.\n"
        "\n"
        "Editor's text:\n"
        "\n"
        "````text\n"
        "Editor ```x``` words.\n"
        "````\n"
        "\n"
        "Upstream text:\n"
        "\n"
        "```text\n"
        "Upstream.\n"
        "```\n"
        "\n"
        "## `Use`\n"
        "\n"
        "[Google Doc](https://docs.google.com/document/d/def/edit) · Owner: not set\n"
    )


def test_render_pr_body_neutralises_sheet_and_doc_text() -> None:
    body = render_pr_body(
        [
            PageEntry(
                title="Use\n# Injected heading",
                doc_url="https://docs.google.com/document/d/abc/edit",
                owner="@ONEcampaign/everyone Closes #42, fixes o/r#7\n\n**Approved**",
                reports=["tab label 'a`b' holds a quote\n- [link](https://x)"],
            )
        ]
    )

    lines = body.splitlines()
    assert lines[2] == f"## `Use #{WJ} Injected heading`"
    assert lines[4] == (
        "[Google Doc](https://docs.google.com/document/d/abc/edit) · Owner: "
        f"`@{WJ}ONEcampaign/everyone C{WJ}loses #{WJ}42, f{WJ}ixes o/r#{WJ}7 **Approved**`"
    )
    assert lines[8] == f"- ``tab label 'a`b' holds a quote - [link](https:/{WJ}/x)``"
    assert len(lines) == 9
    assert "@ONEcampaign" not in body
    assert "#42" not in body


def test_render_pr_body_fences_clash_text_unchanged() -> None:
    text = (
        "Fixes https://github.com/o/r/issues/1, closes DevelopmentFinanceObservatory/docs#42, "
        "cc @ONEcampaign/data"
    )
    body = render_pr_body(
        [
            PageEntry(
                title="Use",
                doc_url="https://docs.google.com/document/d/abc/edit",
                owner=None,
                clashes=[Clash(editor_text=text, upstream_text=f"Was: {text}")],
            )
        ]
    )

    assert f"```text\n{text}\n```" in body
    assert f"```text\nWas: {text}\n```" in body
    assert WJ not in body


def test_render_pr_body_fences_a_refusals_quote_byte_for_byte() -> None:
    quote = (
        "Fixes https://github.com/o/r/issues/1, cc @ONEcampaign/data ```x```\n"
        "\n"
        "  Second paragraph, closes #42."
    )
    body = render_pr_body(
        [
            PageEntry(
                title="Use",
                doc_url="https://docs.google.com/document/d/abc/edit",
                owner=None,
                refusals=[
                    Refusal(
                        "an Author note cannot sit in a quote; this part of the page"
                        " is not changed",
                        quote,
                    ),
                    Refusal("the edits would leave a file docsync cannot read"),
                ],
            )
        ]
    )

    assert body.endswith(
        "## `Use`\n"
        "\n"
        "[Google Doc](https://docs.google.com/document/d/abc/edit) · Owner: not set\n"
        "\n"
        "**Not applied.** `an Author note cannot sit in a quote; this part of the page"
        " is not changed`\n"
        "\n"
        "The Doc has:\n"
        "\n"
        f"````text\n{quote}\n````\n"
        "\n"
        "**Not applied.** `the edits would leave a file docsync cannot read`\n"
    )
    assert WJ not in body.split("````text")[1]


def _refused_entry(*quotes: str) -> PageEntry:
    return PageEntry(
        title="Use",
        doc_url="https://docs.google.com/document/d/abc/edit",
        owner=None,
        refusals=[Refusal("a part is not changed", quote) for quote in quotes],
    )


def test_render_pr_body_cuts_a_refusal_quote_to_stay_under_the_limit() -> None:
    quote = "First line.\n\n" + "word " * 30_000 + "last words."

    body = render_pr_body([_refused_entry(quote)])

    assert BODY_LIMIT - 100 < len(body) <= BODY_LIMIT
    assert "````" not in body
    assert "```text\nFirst line.\n\nword word" in body
    assert "last words." not in body
    assert body.endswith(
        "\n(Shortened here. The full text was in the Doc when this pull ran.)\n```\n"
    )


def test_render_pr_body_shares_the_room_between_refusal_quotes() -> None:
    long = "word " * 30_000
    body = render_pr_body(
        [_refused_entry("Short quote.", long, long), _refused_entry(long)]
    )

    assert len(body) <= BODY_LIMIT
    assert "```text\nShort quote.\n```" in body
    assert body.count("(Shortened here.") == 3
    first, second, third = (
        len(chunk.split("\n(Shortened")[0]) for chunk in body.split("```text")[2:]
    )
    assert abs(first - second) <= 1
    assert abs(first - third) <= 1


def test_render_pr_body_keeps_a_quote_whole_when_the_body_fits() -> None:
    quote = " ".join(["word"] * 5_000)

    body = render_pr_body([_refused_entry(quote)])

    assert f"```text\n{quote}\n```" in body
    assert "Shortened" not in body


def test_shorten_quote() -> None:
    assert shorten_quote("abc def", keep=None) == "abc def"
    assert shorten_quote("abc def", keep=7) == "abc def"
    assert shorten_quote("abc def", keep=4) == (
        "abc\n(Shortened here. The full text was in the Doc when this pull ran.)"
    )


@pytest.mark.parametrize(
    ("text", "joined"),
    [
        (
            "Closes https://github.com/o/r/issues/1",
            f"C{WJ}loses https:/{WJ}/github.com/o/r/issues/1",
        ),
        ("FIXED and Resolve it", f"F{WJ}IXED and R{WJ}esolve it"),
        ("close, closed, fix, fixes, resolves, resolved", None),
        (
            "a prefix, disclosed, fixture, enclose",
            "a prefix, disclosed, fixture, enclose",
        ),
    ],
)
def test_render_pr_body_breaks_closing_keywords_and_urls(
    text: str, joined: str | None
) -> None:
    entry = PageEntry(title="Use", doc_url="https://docs.google.com/d/abc", owner=text)
    body = render_pr_body([entry])

    if joined is None:
        joined = ", ".join(f"{word[0]}{WJ}{word[1:]}" for word in text.split(", "))
    assert f"Owner: `{joined}`" in body
