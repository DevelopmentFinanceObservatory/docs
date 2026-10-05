"""The per-page record docsync keeps between push and pull.

Each page's state is one JSON file, `state/<page_id>.json`, with sorted keys, an indent
of two, and a trailing newline. A page id contains `/`, so the files sit in directories
under `state/`.

`DirStateStore` keeps the files under a local directory, for scratch and probe runs.
`BranchStateStore` keeps them on the orphan branch `docsync-state` of the dfo-docs
remote. It reads and commits with git plumbing against a temporary index, as
`prs.propose_edits` does, so the checkout's working tree, index, and checked-out branch
stay as they were. `load` remembers the branch tip it read, and `save` commits on that
tip and pushes only if the branch still sits there, so a run never overwrites the state
another run saved in between.

Each store's `tip` names the stored version it last loaded or saved: the branch commit,
or a digest of the directory's files. A run that cannot save records it, so a later
restore can tell whether another run saved since.

Both stores validate every file on `load` and raise `StateFormatError` naming the file
on anything malformed. Both write the full set on `save`: pages absent from the mapping
are removed.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from dfo_docs.docsync.git import Git, GitError, command_env

STATE_DIR = "state"
STATE_BRANCH = "docsync-state"

_SUFFIX = ".json"
_MODE = "100644"
# `git ls-remote --exit-code` exits 2 when the remote answered and holds no matching
# ref. Any other non-zero status means the remote could not be read.
_LS_REMOTE_NO_MATCH = 2


class StateError(RuntimeError):
    """The state could not be read or written."""


class StateFormatError(StateError):
    """A state file is malformed or disagrees with its path."""

    def __init__(self, file: str, reason: str) -> None:
        self.file = file
        self.reason = reason
        super().__init__(f"{file}: {reason}")


class StateRemoteError(StateError):
    """The remote holding the state branch could not be reached."""


class StateConflictError(StateError):
    """The state branch moved between `load` and `save`; another run saved first."""


@dataclass(frozen=True)
class PageState:
    """What docsync knows about one page's Google Doc.

    Attributes:
        page_id: The page's id, also its file path under `state/` without `.json`.
        doc_id: The Google Doc's Drive file id.
        repo: The source repository as `owner/name`.
        ref: The source branch the page was pushed from.
        path: The source file, relative to the repository root.
        source_commit: The source commit the Doc was last written from.
        baseline: The Doc's export right after it was last written from the source
            at `source_commit`.
        applied_export: An export of this Doc whose edits relative to `baseline` are
            already in the source, or were reported as not applicable; `None` when no
            edit has been applied since the Doc was last written.
        pulled_export: The export the open pull request `pr_url` carries, or `None`
            when the page is in no open pull request.
        pr_url: The one open pull request carrying this page's edits, or `None`.
        discarded_on: When a push last discarded the Doc's edits, kept until a push
            reads a Status other than Discard my edits, so a Status left unchanged by
            a failed Sheet write does not discard again; `None` otherwise.
    """

    page_id: str
    doc_id: str
    repo: str
    ref: str
    path: str
    source_commit: str
    baseline: str
    applied_export: str | None = None
    pulled_export: str | None = None
    pr_url: str | None = None
    discarded_on: str | None = None


class StateStore(Protocol):
    """Where page states live between runs."""

    def load(self) -> dict[str, PageState]:
        """Every stored page state, keyed by page id."""
        ...

    def save(self, states: Mapping[str, PageState], *, message: str) -> None:
        """Replace the stored set with `states`. `message` describes the run."""
        ...

    def tip(self) -> str | None:
        """The stored version last loaded or saved, or None when the store was empty.

        Reads nothing, so it answers after a failed save.
        """
        ...


class _Unloaded:
    """The tip of a `BranchStateStore` that has not called `load` yet."""


_UNLOADED = _Unloaded()


class DirStateStore:
    """Page states as `state/<page_id>.json` files under a local directory."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._tip: str | None = None

    def tip(self) -> str | None:
        """A digest of the files last loaded or saved, or None when there were none."""
        return self._tip

    def load(self) -> dict[str, PageState]:
        """Read and validate every state file under `<path>/state/`.

        Raises:
            StateFormatError: a file is malformed or disagrees with its path.
        """
        root = self.path / STATE_DIR
        files = (
            sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else []
        )
        texts = {file.relative_to(root).as_posix(): file.read_text() for file in files}
        self._tip = _digest(texts)
        return _parse_all(
            (str(root / name), name, text) for name, text in texts.items()
        )

    def save(self, states: Mapping[str, PageState], *, message: str) -> None:
        """Write `states` under `<path>/state/` and delete files for other pages.

        Files whose content is unchanged are left untouched.
        """
        files = _render_all(states)
        root = self.path / STATE_DIR
        for name, text in files.items():
            target = root / name
            if target.is_file() and target.read_text() == text:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)

        if root.is_dir():
            for file in sorted(root.rglob("*"), reverse=True):
                if file.is_file() and file.relative_to(root).as_posix() not in files:
                    file.unlink()
                elif file.is_dir() and not any(file.iterdir()):
                    file.rmdir()
        self._tip = _digest(files)


class BranchStateStore:
    """Page states on a branch of a git remote, committed with plumbing.

    The branch holds only `state/`. A missing branch is empty state, and `save` then
    creates it as an orphan. Commits take their author and committer from git's own
    environment variables and config.

    `load` records the tip it read. `save` commits on that tip and pushes it as a
    fast-forward, so a branch that moved since `load` (or, for a branch that was
    missing, was created since) raises `StateConflictError`. A `save` before any `load`
    takes its tip from the remote at that moment. After a successful `save` the store's tip is the
    commit it pushed, so one store can save repeatedly.

    Args:
        repo_root: A git checkout whose `remote` holds the branch.
        branch: The state branch.
        remote: The git remote to fetch from and push to.
        token: A GitHub token for fetch and push. It reaches git through a
            credential helper set in the command environment, so it is never
            written to a config file or a remote URL. When `None`, git uses the
            user's own credentials.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        branch: str = STATE_BRANCH,
        remote: str = "origin",
        token: str | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.branch = branch
        self.remote = remote
        self._git = Git(root=repo_root, env=command_env(token))
        self._tip: str | _Unloaded | None = _UNLOADED

    def load(self) -> dict[str, PageState]:
        """Fetch the branch, remember its tip, and read every state file on it.

        Raises:
            StateRemoteError: the remote could not be reached.
            StateFormatError: a file is malformed or disagrees with its path.
            GitError: a git command failed after the branch was found.
        """
        commit = self._fetch_tip()
        self._tip = commit
        if commit is None:
            return {}
        listing = self._git.run(
            "ls-tree", "-r", "-z", commit, "--", f"{STATE_DIR}/"
        ).split("\0")
        entries = []
        for line in filter(None, listing):
            meta, name = line.split("\t", 1)
            blob = meta.split()[2]
            entries.append((name, blob))
        return _parse_all(
            (
                f"{self.branch}:{name}",
                PurePosixPath(name).relative_to(STATE_DIR).as_posix(),
                self._git.run("cat-file", "blob", blob),
            )
            for name, blob in entries
        )

    def save(self, states: Mapping[str, PageState], *, message: str) -> None:
        """Commit `states` as the branch's whole tree and push it.

        The commit's parent is the tip `load` read (the remote's tip, if `load` was
        not called), and it is pushed with a plain push, which the remote accepts only
        as a fast-forward of that tip. When the tree equals the tip's tree (or
        `states` is empty and the branch is missing), nothing is committed or pushed.

        Raises:
            StateConflictError: the branch tip differs from the one `load` read.
            StateRemoteError: the remote could not be reached.
            GitError: a git command failed.
        """
        files = _render_all(states)
        if isinstance(self._tip, _Unloaded):
            self._tip = self._fetch_tip()
        parent = self._tip
        tree = self._write_tree(files)

        if parent is None:
            if not files:
                return
            parents: tuple[str, ...] = ()
        else:
            if tree == self._git.run("rev-parse", f"{parent}^{{tree}}").strip():
                return
            parents = ("-p", parent)

        commit = self._git.run(
            "commit-tree", tree, *parents, "-F", "-", stdin=message
        ).strip()
        self._push(commit, expected=parent)
        self._tip = commit

    def tip(self) -> str | None:
        """The branch commit last loaded or saved, or None when the branch was missing.

        Raises:
            StateError: neither `load` nor `save` has run.
        """
        if isinstance(self._tip, _Unloaded):
            raise StateError(f"{self.branch}: tip read before load")
        return self._tip

    def _push(self, commit: str, *, expected: str | None) -> None:
        """Push `commit` as the branch if the branch still sits at `expected`.

        `commit` descends from `expected` (or is an orphan when `expected` is `None`),
        so a plain push is a fast-forward only while the branch is still there. Any
        other tip makes the remote reject it.
        """
        ref = f"refs/heads/{self.branch}"
        result = self._git.run_unchecked("push", "-q", self.remote, f"{commit}:{ref}")
        if result.returncode == 0:
            return
        if self._remote_tip() != expected:
            raise StateConflictError(
                f"{self.branch} on {self.remote} moved since it was loaded; "
                "rerun to start from the current state"
            )
        raise GitError(["git", "push", self.remote, ref], result.stderr)

    def _fetch_tip(self) -> str | None:
        """Fetch the branch and return its tip, or `None` when the remote lacks it."""
        ref = f"refs/heads/{self.branch}"
        if self._remote_tip() is None:
            return None
        self._git.run("fetch", "-q", self.remote, ref)
        return self._git.run("rev-parse", "--verify", "FETCH_HEAD^{commit}").strip()

    def _remote_tip(self) -> str | None:
        """The branch's commit id on the remote, or `None` when the remote lacks it."""
        result = self._git.run_unchecked(
            "ls-remote", "--exit-code", self.remote, f"refs/heads/{self.branch}"
        )
        if result.returncode == _LS_REMOTE_NO_MATCH:
            return None
        if result.returncode != 0:
            raise StateRemoteError(
                f"cannot read {self.branch} from {self.remote}: "
                f"{result.stderr.strip() or f'exit status {result.returncode}'}"
            )
        return result.stdout.split()[0]

    def _write_tree(self, files: Mapping[str, str]) -> str:
        """Write `files` under `state/` as a tree through a temporary index."""
        with tempfile.TemporaryDirectory(prefix="dfo_docsync-state-") as scratch:
            index = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
            for name, text in files.items():
                blob = self._git.run("hash-object", "-w", "--stdin", stdin=text).strip()
                self._git.run(
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"{_MODE},{blob},{STATE_DIR}/{name}",
                    env=index,
                )
            return self._git.run("write-tree", env=index).strip()


def render_state(state: PageState) -> str:
    """The JSON text of `state`: sorted keys, indent two, trailing newline."""
    return (
        json.dumps(
            dataclasses.asdict(state), sort_keys=True, indent=2, ensure_ascii=False
        )
        + "\n"
    )


def parse_state(text: str, *, file: str, page_id: str) -> PageState:
    """Parse and validate one state file.

    Args:
        text: The file's content.
        file: The file's name, for error messages.
        page_id: The page id its path implies.

    Raises:
        StateFormatError: the text is not a JSON object with the `PageState` fields,
            a field has the wrong type, or its `page_id` differs from `page_id`.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise StateFormatError(file, f"invalid JSON: {error}") from error
    return state_from_json(data, file=file, page_id=page_id)


def state_from_json(data: object, *, file: str, page_id: str) -> PageState:
    """Validate one decoded state object.

    Every `PageState` field must be present. The optional ones may be null.

    Args:
        data: The decoded JSON value.
        file: Where it came from, for error messages.
        page_id: The page id it must carry.

    Raises:
        StateFormatError: `data` is not an object with exactly the `PageState`
            fields, a field has the wrong type, or its `page_id` differs from
            `page_id`.
    """
    if not isinstance(data, dict):
        raise StateFormatError(file, "expected a JSON object")

    fields = {field.name: field for field in dataclasses.fields(PageState)}
    unknown = sorted(set(data) - set(fields))
    if unknown:
        raise StateFormatError(file, f"unknown fields: {', '.join(unknown)}")
    missing = sorted(set(fields) - set(data))
    if missing:
        raise StateFormatError(file, f"missing fields: {', '.join(missing)}")
    for name, value in data.items():
        optional = fields[name].default is None
        if not (isinstance(value, str) or (optional and value is None)):
            expected = "a string or null" if optional else "a string"
            raise StateFormatError(file, f"{name} must be {expected}")

    if data["page_id"] != page_id:
        raise StateFormatError(
            file, f"page_id {data['page_id']!r} disagrees with its path ({page_id!r})"
        )
    try:
        _check_page_id(page_id)
    except ValueError as error:
        raise StateFormatError(file, str(error)) from error
    return PageState(**data)


def _parse_all(files: Iterable[tuple[str, str, str]]) -> dict[str, PageState]:
    """Parse `(display name, path under state/, text)` triples into states."""
    states = {}
    for file, name, text in files:
        if not name.endswith(_SUFFIX):
            raise StateFormatError(file, f"not a {_SUFFIX} file")
        page_id = name.removesuffix(_SUFFIX)
        states[page_id] = parse_state(text, file=file, page_id=page_id)
    return states


def _digest(files: Mapping[str, str]) -> str | None:
    """A digest of state files keyed by path under `state/`; None when there are none."""
    if not files:
        return None
    digest = hashlib.sha256()
    for name, text in sorted(files.items()):
        digest.update(f"{name}\0{text}\0".encode())
    return digest.hexdigest()


def _render_all(states: Mapping[str, PageState]) -> dict[str, str]:
    """The text of each state file, keyed by its path under `state/`."""
    files = {}
    for key, state in states.items():
        if key != state.page_id:
            raise ValueError(f"state keyed {key!r} has page_id {state.page_id!r}")
        _check_page_id(state.page_id)
        files[state.page_id + _SUFFIX] = render_state(state)
    return files


def _check_page_id(page_id: str) -> None:
    """Refuse an id that would name a file outside `state/` or an odd path."""
    parts = page_id.split("/")
    if "\\" in page_id or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{page_id!r} is not a usable page id")
