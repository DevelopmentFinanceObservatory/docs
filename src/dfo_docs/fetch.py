"""Fetch a `docs`- or `skill`-kind Source's documentation directory into a working area.

Records the resolved commit on every `Fetched`, so a build is reproducible. Collects
every source's outcome before raising, so one failing repository never hides the rest.
Checks the fetched docs directory is non-empty before calling a fetch a success, so a
renamed docs directory fails loudly instead of vanishing silently.

Repository rename and archival detection need the GitHub API and belong to the monthly
registry-health job. `build.py` talks to git and nothing else.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from dfo_docs.models import FETCHED_KINDS, Fetched, Source


class FetchError(RuntimeError):
    """One or more sources failed to fetch.

    Raised by `fetch_all` only after every source has been attempted, so a single bad
    repository never hides the outcome of the rest. `failures` maps source name to the
    error message.
    """

    def __init__(self, failures: dict[str, str]) -> None:
        self.failures = failures
        detail = "\n".join(f"  {name}: {message}" for name, message in failures.items())
        super().__init__(f"{len(failures)} source(s) failed to fetch:\n{detail}")


def fetch_source(source: Source, *, workdir: Path) -> Fetched:
    """Clone `source` into `workdir` and return where it landed and its resolved commit.

    Clones with `--filter=blob:none --sparse`, keeping full history so `last_modified`
    can read `git log` with no API calls, then sparse-checks-out `source.docs_dir`,
    `source.internal_dir` when the row sets one, and the repository root (cone mode
    already includes top-level files, but the pattern is set explicitly so a root
    `mkdocs.yml`, `zensical.toml`, `CHANGELOG.md`, or `CONTRIBUTING.md` is never in
    doubt). Checks out `source.commit` if set, `source.ref` otherwise.

    Raises `ValueError` if `source` is `kind: external`, or if the checked-out docs
    directory is missing or contains no Markdown file. A missing `internal_dir` passes
    here, and `skills.check_internal_dir` warns of it. Raises `RuntimeError` if a git
    command fails.
    """
    if source.kind not in FETCHED_KINDS:
        raise ValueError(
            f"{source.name!r} is not a fetched source (kind={source.kind!r})"
        )
    if source.docs_dir is None:
        raise ValueError(f"{source.name!r} has no docs_dir configured")

    dest = workdir / source.name
    clone_args = ["clone", "-q", "--filter=blob:none", "--sparse"]
    if source.ref:
        clone_args += ["--branch", source.ref]
    clone_args += [_clone_url(source.repo), str(dest)]
    _run_git(None, clone_args)

    _run_git(dest, ["sparse-checkout", "init", "--cone"])
    directories = [source.docs_dir]
    if source.internal_dir is not None:
        directories.append(source.internal_dir)
    _run_git(dest, ["sparse-checkout", "set", *directories, "."])

    if source.commit:
        _run_git(dest, ["checkout", "-q", source.commit])

    commit = _run_git(dest, ["rev-parse", "HEAD"]).strip()
    docs_root = dest / source.docs_dir
    _check_docs_dir(source.name, docs_root)

    return Fetched(source=source, repo_root=dest, docs_root=docs_root, commit=commit)


def fetch_all(sources: Iterable[Source], *, workdir: Path) -> list[Fetched]:
    """Fetch every source in `sources`, collecting every failure before raising.

    Returns a `Fetched` per source, in input order, if all succeed. Raises `FetchError`
    naming every failed source only once every source has been attempted.
    """
    fetched: list[Fetched] = []
    failures: dict[str, str] = {}
    for source in sources:
        try:
            fetched.append(fetch_source(source, workdir=workdir))
        except Exception as exc:  # collected per source, reported below
            failures[source.name] = str(exc)

    if failures:
        raise FetchError(failures)
    return fetched


def last_modified(repo_root: Path, path: str | Path) -> str:
    """Return the last commit date for `path`, e.g. `"2026-08-14T16:43:28Z"`.

    Reads `git log`, so it costs no API call and works against a `--filter=blob:none`
    clone. `path` is relative to `repo_root` and must fall inside the checked-out
    sparse cone. Raises `ValueError` if `path` has no commit history there.
    """
    output = _run_git(repo_root, ["log", "-1", "--format=%cI", "--", str(path)])
    stamp = output.strip()
    if not stamp:
        raise ValueError(f"no commit history for {path!r} in {repo_root}")

    moment = datetime.fromisoformat(stamp).astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _clone_url(repo: str) -> str:
    """Resolve a sources.yaml `repo` field to a git remote.

    A bare `org/name` shorthand resolves to the GitHub HTTPS URL. Anything that already
    looks like a URL or a filesystem path passes through unchanged, which is how tests
    point at local fixture repositories.
    """
    if "://" in repo or repo.startswith(("/", ".", "~")):
        return repo
    return f"https://github.com/{repo}.git"


def _check_docs_dir(name: str, docs_root: Path) -> None:
    if not docs_root.is_dir():
        raise ValueError(
            f"{name!r}: docs directory {docs_root} does not exist after checkout"
        )
    if not any(docs_root.rglob("*.md")):
        raise ValueError(f"{name!r}: docs directory {docs_root} has no Markdown files")


def _run_git(cwd: Path | None, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout
