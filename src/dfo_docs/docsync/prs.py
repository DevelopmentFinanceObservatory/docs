"""Open pull requests for Google Docs edits, and read the ones docsync opened.

`propose_edits` pushes one commit carrying the edited files to a new branch named
`docsync/edits-<stamp>`, built on the tip of the remote base branch, and opens a pull
request from it. It refuses with `StaleBaseError` when the base branch changed a file
after the commit its edited text was built on. docsync never pushes to that branch or
edits that pull request again, so reviewers may commit to it. The commit is built with
git plumbing against a temporary index, so the clone's working tree, index, and
checked-out branch stay as they were. That matters for hub pages, whose clone is the
dfo-docs checkout the run started from.

`list_open_pull_requests` lists the open docsync pull requests of one repository, and
`view_pull_request` reads the state, files, and merge commit of one. `render_pr_body`
turns per-page entries into the pull request body, and keeps it under `BODY_LIMIT`
characters by shortening the refusal quotes (see `render_within`).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from dfo_docs.docsync.edits import Clash
from dfo_docs.docsync.git import (
    TOKEN_ENV,
    CommandError,
    Git,
    GitError,
    command_env,
)

# `TOKEN_ENV` and `GitError` live in `git` and are listed so callers can import them
# from here.
__all__ = [
    "BODY_LIMIT",
    "EDITS_BRANCH_PREFIX",
    "TOKEN_ENV",
    "Clash",
    "EditedFile",
    "GhError",
    "GitError",
    "GitIdentity",
    "NoChangesError",
    "OpenPullRequest",
    "PageEntry",
    "PrError",
    "PullRequest",
    "Refusal",
    "StaleBaseError",
    "edits_branch",
    "list_open_pull_requests",
    "propose_edits",
    "render_pr_body",
    "render_within",
    "shorten_quote",
    "view_pull_request",
]

EDITS_BRANCH_PREFIX = "docsync/edits-"
_DEFAULT_MODE = "100644"
_LIST_LIMIT = "1000"

# The most characters `render_pr_body` returns when the refusal quotes can bring it
# there. GitHub accepts 65,536 in a pull request body.
BODY_LIMIT = 60_000

_SHORTENED = "(Shortened here. The full text was in the Doc when this pull ran.)"

# A git or gh command run while proposing edits failed.
PrError = CommandError


class GhError(CommandError):
    """A gh command failed."""


class StaleBaseError(CommandError):
    """The base branch changed a file after the commit its edited text was built on.

    The text would overwrite that change, so nothing is proposed. A later run rebuilds
    the text from the new base.
    """

    def __init__(self, *, base: str, paths: Sequence[str]) -> None:
        self.base = base
        self.paths = tuple(paths)
        self.command = ()
        self.stderr = ""
        RuntimeError.__init__(
            self,
            f"{base} changed {', '.join(self.paths)} after this run read them;"
            " the next run proposes against the new text",
        )


class NoChangesError(ValueError):
    """The edited files equal the base branch, so there is nothing to propose."""


@dataclass(frozen=True)
class EditedFile:
    """The full new text of one file, and the commit whose version of it was edited."""

    text: str
    built_on: str


@dataclass(frozen=True)
class GitIdentity:
    """The author and committer of the docsync commit."""

    name: str
    email: str


@dataclass(frozen=True)
class PullRequest:
    """What gh reports for one pull request.

    Attributes:
        state: OPEN, CLOSED or MERGED.
        files: The paths it changes.
        merge_commit: The commit its merge created on the base branch, once merged.
    """

    state: str
    files: frozenset[str]
    merge_commit: str | None = None


@dataclass(frozen=True)
class OpenPullRequest:
    """An open pull request docsync opened: its URL, head branch, and changed paths."""

    url: str
    branch: str
    files: frozenset[str]


@dataclass(frozen=True)
class Refusal:
    """A part of the page left unchanged: why, and the Doc's text of it.

    `quote` is empty when there is no Doc text to show.
    """

    message: str
    quote: str = ""


@dataclass(frozen=True)
class PageEntry:
    """One page's section of the pull request body."""

    title: str
    doc_url: str
    owner: str | None
    reports: Sequence[str] = field(default_factory=tuple)
    refusals: Sequence[Refusal] = field(default_factory=tuple)
    clashes: Sequence[Clash] = field(default_factory=tuple)


def edits_branch(stamp: str) -> str:
    """The head branch of the pull request a run opens, for its UTC `stamp`."""
    return EDITS_BRANCH_PREFIX + stamp


def render_pr_body(entries: Sequence[PageEntry]) -> str:
    """Render the pull request body: one section per page, in the order given.

    Each section links the page's Google Doc, names its owner, lists the reports,
    shows each refusal with the Doc's text of the part of the page left unchanged, and
    shows each flagged clash with the editor's text and the upstream text it replaced.
    The reports are edits docsync did not apply (code, structure, tables, a folded
    description, a callout kind), anchors that change with a heading, and Author note
    flags: a note that became page text, a paragraph that became a note, or a note
    and the page text beside it changed together.

    The title, owner, reports, and refusal messages come from the Sheet, the Doc, or the
    source, so each is written as an inline code span on one line (see `_inline`). No
    Markdown, mention, or issue reference in them takes effect. Refusal and clash text
    goes in a fence longer than any backtick run inside it, byte for byte (see
    `_fenced`). A refusal quote is cut, and ends with a line saying so, when the body
    would pass `BODY_LIMIT` characters (see `render_within`).
    """
    quotes = sum(1 for entry in entries for refusal in entry.refusals if refusal.quote)
    return render_within(
        lambda keep: _render(entries, keep=keep), limit=BODY_LIMIT, quotes=quotes
    )


def render_within(
    render: Callable[[int | None], str], *, limit: int, quotes: int
) -> str:
    """`render(None)` when it fits `limit` characters, else a text with cut quotes.

    `render(keep)` returns the text with each quote cut to `keep` characters (see
    `shorten_quote`), or whole for `None`. When the whole text is too long, the room
    left once every quote is cut to nothing is shared equally among the `quotes`
    quotes. The text stays over `limit` only when what surrounds the quotes does.
    """
    text = render(None)
    if len(text) <= limit or not quotes:
        return text
    room = limit - len(render(0))
    return render(max(room, 0) // quotes)


def shorten_quote(quote: str, *, keep: int | None) -> str:
    """`quote` cut to its first `keep` characters and a line saying it was cut.

    A quote of `keep` characters or fewer, or any quote when `keep` is `None`, is
    returned whole.
    """
    if keep is None or len(quote) <= keep:
        return quote
    return f"{quote[:keep].rstrip()}\n{_SHORTENED}"


def _render(entries: Sequence[PageEntry], *, keep: int | None) -> str:
    parts = [
        "Edits made in Google Docs, applied to the source files by docsync. "
        "Review each page below before merging."
    ]
    for entry in entries:
        parts.append(f"## {_inline(entry.title)}")
        owner = _inline(entry.owner) if entry.owner else "not set"
        parts.append(f"[Google Doc]({entry.doc_url}) · Owner: {owner}")
        if entry.reports:
            parts.append(
                "Reports:\n\n"
                + "\n".join(f"- {_inline(report)}" for report in entry.reports)
            )
        parts.extend(_refusal_part(refusal, keep=keep) for refusal in entry.refusals)
        for number, clash in enumerate(entry.clashes, start=1):
            parts.append(
                f"**Flagged clash {number}.** The editor and upstream both changed "
                "this block. This pull request applies the editor's text.\n\n"
                f"Editor's text:\n\n{_fenced(clash.editor_text)}\n\n"
                f"Upstream text:\n\n{_fenced(clash.upstream_text)}"
            )
    return "\n\n".join(parts) + "\n"


def _refusal_part(refusal: Refusal, *, keep: int | None) -> str:
    """One refusal: its message, then the Doc's text in a fence when there is any."""
    head = f"**Not applied.** {_inline(refusal.message)}"
    if not refusal.quote:
        return head
    quote = shorten_quote(refusal.quote, keep=keep)
    return f"{head}\n\nThe Doc has:\n\n{_fenced(quote)}"


def propose_edits(
    *,
    clone_root: Path,
    repo: str,
    base: str,
    branch: str,
    files: Mapping[str, EditedFile],
    title: str,
    body: str,
    author: str,
    identity: GitIdentity | None = None,
    token: str | None = None,
    remote: str = "origin",
    dry_run_dir: Path | None = None,
) -> str:
    """Push `files` as one commit on the new branch `branch` and open a PR from it.

    The commit sits on the tip of `base` on `remote`. For hub pages pass `dev`, the
    branch edits are proposed against, whatever `clone_root` has checked out. The push
    is a plain push of a branch that does not exist yet, so it can never replace
    commits on an existing branch. If `branch` exists, the remote rejects it.

    Each file's text replaces the whole file, so after fetching `base` the file at the
    tip must be the blob it was at `built_on`. Otherwise the commit would revert what
    `base` changed in between, and `StaleBaseError` is raised before anything is pushed.

    gh can create the pull request and still exit non-zero, so a failed `gh pr create`
    is followed by a lookup of the open pull request `author` opened from `branch`.
    One found is returned as if the create had succeeded.

    Args:
        clone_root: The git checkout to build and push the commit from.
        repo: The GitHub repository as `owner/name`, passed to gh.
        base: The branch the pull request targets.
        branch: The new head branch, from `edits_branch`.
        files: Each edited file's new text and the commit it was built on, keyed by
            repo-relative POSIX path.
        title: The pull request title, also the commit subject.
        body: The pull request body, from `render_pr_body`.
        author: The gh `--author` docsync's pull requests carry, as in
            `list_open_pull_requests`.
        identity: Author and committer of the commit. When `None`, git resolves them
            from its own environment variables and config.
        token: A GitHub token for the push and for gh. When `None`, the `DFO_DOCSYNC_TOKEN`
            environment variable is used if set, else the user's own git and gh
            credentials. The token reaches git through a credential helper set in the
            command environment, and gh through `GH_TOKEN`, so it is never written to
            a config file or a remote URL.
        remote: The git remote that holds `base`.
        dry_run_dir: When set, write each file under `<dry_run_dir>/files/` and the
            title and body to `<dry_run_dir>/pr.md`, and run no git or gh command.

    Returns:
        The pull request URL, or in a dry run the `file://` URI of `pr.md`.

    Raises:
        ValueError: `files` is empty, names a path outside the repository, or
            `branch` does not start with `docsync/edits-`.
        StaleBaseError: `base` changed a file after its `built_on` commit.
        NoChangesError: every file already equals its text on `base`.
        GitError: a git command failed, including a push to a branch that exists;
            carries its stderr.
        GhError: a gh command failed, and no pull request from `branch` exists;
            carries its stderr.
    """
    if not files:
        raise ValueError(f"{repo}: no files to propose")
    if not branch.startswith(EDITS_BRANCH_PREFIX) or branch == EDITS_BRANCH_PREFIX:
        raise ValueError(f"{branch!r} is not a docsync edits branch")
    for path in files:
        _check_relative(path)

    texts = {path: file.text for path, file in files.items()}
    if dry_run_dir is not None:
        return _write_dry_run(dry_run_dir, files=texts, title=title, body=body)

    env = _env(token)
    git = Git(root=clone_root, env=env)

    git.run("fetch", "-q", remote, f"refs/heads/{base}")
    base_commit = git.run("rev-parse", "--verify", "FETCH_HEAD^{commit}").strip()
    if stale := _stale_paths(git, base_commit=base_commit, files=files):
        raise StaleBaseError(base=base, paths=stale)
    commit = _build_commit(
        git, base_commit=base_commit, files=texts, message=title, identity=identity
    )
    git.run("push", "-q", remote, f"{commit}:refs/heads/{branch}")

    try:
        created = _gh(
            env,
            clone_root,
            "pr",
            "create",
            "--repo",
            repo,
            "--base",
            base,
            "--head",
            branch,
            "--title",
            title,
            "--body-file",
            "-",
            stdin=body,
        ).split()
    except GhError:
        if url := _find_pull_request(env, repo=repo, branch=branch, author=author):
            return url
        raise
    if not created:
        raise GhError(["gh", "pr", "create"], "printed no pull request URL")
    return created[-1]


def list_open_pull_requests(
    repo: str, *, author: str, token: str | None = None
) -> tuple[OpenPullRequest, ...]:
    """The open pull requests `author` opened in `repo` from a `docsync/edits-` branch.

    Filtering by author keeps out pull requests from forks or people whose branch
    happens to carry the same name.

    Args:
        repo: The GitHub repository as `owner/name`.
        author: The gh `--author` value: `app/dfo-docsync` for the bot, or a login.
        token: A GitHub token for gh, handled as in `propose_edits`.

    Raises:
        GhError: gh failed or printed something other than a JSON list.
    """
    command = (
        "pr", "list", "--repo", repo, "--state", "open", "--author", author,
        "--limit", _LIST_LIMIT, "--json", "url,headRefName,files",
    )  # fmt: skip
    payload = _gh_json(_env(token), None, *command)
    if not isinstance(payload, list):
        raise GhError(["gh", *command], "printed no JSON list")
    return tuple(
        OpenPullRequest(
            url=item["url"],
            branch=item["headRefName"],
            files=frozenset(f["path"] for f in item.get("files") or []),
        )
        for item in payload
        if item["headRefName"].startswith(EDITS_BRANCH_PREFIX)
    )


def view_pull_request(url: str, *, token: str | None = None) -> PullRequest:
    """What gh reports for pull request `url`.

    Raises:
        GhError: gh failed or printed something other than a JSON object.
    """
    command = ("pr", "view", url, "--json", "state,files,mergeCommit")
    payload = _gh_json(_env(token), None, *command)
    if not isinstance(payload, dict):
        raise GhError(["gh", *command], "printed no JSON object")
    merge_commit = payload.get("mergeCommit") or {}
    return PullRequest(
        state=payload["state"],
        files=frozenset(item["path"] for item in payload.get("files") or []),
        merge_commit=merge_commit.get("oid"),
    )


def _find_pull_request(
    env: Mapping[str, str], *, repo: str, branch: str, author: str
) -> str | None:
    """The URL of the open pull request `author` opened from `branch`, if gh finds one."""
    command = (
        "pr", "list", "--repo", repo, "--state", "open", "--head", branch,
        "--author", author, "--json", "url",
    )  # fmt: skip
    try:
        payload = _gh_json(env, None, *command)
    except GhError:
        return None
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0].get("url")
    return None


def _build_commit(
    git: Git,
    *,
    base_commit: str,
    files: Mapping[str, str],
    message: str,
    identity: GitIdentity | None,
) -> str:
    """Commit `files` over `base_commit` through a temporary index; return its id."""
    base_tree = git.run("rev-parse", f"{base_commit}^{{tree}}").strip()
    with tempfile.TemporaryDirectory(prefix="dfo_docsync-index-") as scratch:
        index = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
        git.run("read-tree", base_commit, env=index)
        for path, text in files.items():
            blob = git.run("hash-object", "-w", "--stdin", stdin=text).strip()
            mode = _mode_at(git, commit=base_commit, path=path)
            git.run(
                "update-index",
                "--add",
                "--cacheinfo",
                f"{mode},{blob},{path}",
                env=index,
            )
        # The clone may be partial (`--filter=blob:none`), so blobs of untouched files
        # are absent locally. The remote already holds them.
        tree = git.run("write-tree", "--missing-ok", env=index).strip()

    if tree == base_tree:
        raise NoChangesError(f"every file already matches {base_commit}")

    author = {}
    if identity is not None:
        author = {
            "GIT_AUTHOR_NAME": identity.name,
            "GIT_AUTHOR_EMAIL": identity.email,
            "GIT_COMMITTER_NAME": identity.name,
            "GIT_COMMITTER_EMAIL": identity.email,
        }
    return git.run(
        "commit-tree", tree, "-p", base_commit, "-F", "-", stdin=message, env=author
    ).strip()


def _stale_paths(
    git: Git, *, base_commit: str, files: Mapping[str, EditedFile]
) -> list[str]:
    """The paths whose blob at `base_commit` differs from the blob at their `built_on`.

    Raises:
        GitError: a `built_on` commit is not in the clone.
    """
    stale = []
    for path, file in files.items():
        git.run("rev-parse", "--verify", "-q", f"{file.built_on}^{{commit}}")
        if _blob_at(git, file.built_on, path) != _blob_at(git, base_commit, path):
            stale.append(path)
    return stale


def _blob_at(git: Git, commit: str, path: str) -> str | None:
    """The blob id of `path` at `commit`, or `None` when the commit lacks the file."""
    result = git.run_unchecked("rev-parse", "--verify", "-q", f"{commit}:{path}")
    return result.stdout.strip() if result.returncode == 0 else None


def _mode_at(git: Git, *, commit: str, path: str) -> str:
    """The file mode of `path` at `commit`, or a regular file's mode if it is new."""
    listing = git.run("ls-tree", commit, "--", path).strip()
    return listing.split(maxsplit=1)[0] if listing else _DEFAULT_MODE


def _env(token: str | None) -> dict[str, str]:
    return command_env(token if token is not None else os.environ.get(TOKEN_ENV))


def _gh(
    env: Mapping[str, str], cwd: Path | None, *args: str, stdin: str | None = None
) -> str:
    command = ["gh", *args]
    result = subprocess.run(
        command,
        cwd=cwd,
        env=dict(env),
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise GhError(command, result.stderr)
    return result.stdout


def _gh_json(env: Mapping[str, str], cwd: Path | None, *args: str) -> object:
    try:
        return json.loads(_gh(env, cwd, *args))
    except json.JSONDecodeError as exc:
        raise GhError(["gh", *args], f"printed invalid JSON: {exc}") from exc


def _check_relative(path: str) -> None:
    pure = PurePosixPath(path)
    if not path or pure.is_absolute() or ".." in pure.parts or "\\" in path:
        raise ValueError(f"{path!r} is not a repo-relative POSIX path")


def _write_dry_run(
    out: Path, *, files: Mapping[str, str], title: str, body: str
) -> str:
    for path, text in files.items():
        target = out / "files" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    pr = out / "pr.md"
    pr.write_text(f"# {title}\n\n{body}")
    return pr.resolve().as_uri()


def _fenced(text: str) -> str:
    """`text` in a fence longer than any backtick run inside it, unchanged.

    GitHub renders no mention, reference, or closing keyword inside a fenced block,
    so the text stays as the editor and upstream wrote it.
    """
    longest = run = 0
    for char in text:
        run = run + 1 if char == "`" else 0
        longest = max(longest, run)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{text.rstrip('\n')}\n{fence}"


def _inline(text: str) -> str:
    """`text` on one line as an inline code span that nothing inside can close.

    GitHub renders no Markdown, `@` mention, or issue reference inside a code span, so
    an Owner cell such as `@org/team Closes #42` notifies nobody and closes nothing.
    `_join_words` breaks those patterns with an invisible word joiner (U+2060) for any
    reader that ignores code spans.
    """
    flat = _join_words(" ".join(text.split()))
    longest = max((len(run) for run in re.findall(r"`+", flat)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if flat.startswith("`") or flat.endswith("`") else ""
    return f"{fence}{pad}{flat}{pad}{fence}"


_CLOSING_KEYWORD = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b", re.IGNORECASE
)


def _join_words(text: str) -> str:
    """`text` with a word joiner (U+2060) breaking each way GitHub links or closes.

    The joiner follows each `@` and `#`, sits between the slashes of `://`, and follows
    the first letter of each closing keyword (close, fix, resolve and their forms), so
    `Closes https://github.com/o/r/issues/1` closes nothing even outside a code span.
    """
    text = text.replace("@", "@\u2060").replace("#", "#\u2060")
    text = text.replace("://", ":/\u2060/")
    return _CLOSING_KEYWORD.sub(lambda m: f"{m[0][0]}\u2060{m[0][1:]}", text)
