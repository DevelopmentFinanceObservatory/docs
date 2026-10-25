"""Enumerate the pages docsync publishes to Google Docs.

`docsync.yaml` names the sources in scope: `hub` for this repository's own pages under
`content/hub/`, and any enabled `docs` or `skill` row of `sources.yaml` that `hub.yaml`
mounts. `load_sync_pages` fetches those sources with the build's own `fetch_all` and
runs `manifest.build_pages` over a copy of `hub.yaml` cut down to them, so every
`SyncPage.page_id`, title, and nav position is the one the published manifest carries.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from dfo_docs.docsync.git import Git, command_env
from dfo_docs.fetch import fetch_all
from dfo_docs.manifest import build_pages
from dfo_docs.models import FETCHED_KINDS, Fetched, HubNode, NavNode, Page, Source
from dfo_docs.registry import load_hub, load_sources
from dfo_docs.yaml_errors import describe_yaml_error

CONFIG_FILE = "docsync.yaml"
# The allowlist name for this repository's own pages, and their page id prefix.
HUB = "hub"

_SOURCES_FILE = "sources.yaml"
_HUB_FILE = "hub.yaml"
_HUB_CONTENT_DIR = "content/hub"
_CONFIG_KEYS = frozenset({"sources", "drive_folder_id", "pr_author"})


class DocsyncConfigError(ValueError):
    """docsync.yaml failed to load, or names a source docsync cannot publish."""


class HubCheckoutError(RuntimeError):
    """The dfo-docs checkout cannot supply hub pages.

    Its hub content has uncommitted changes, it has no branch checked out, or its
    `HEAD` is not the remote's `dev`.
    """


@dataclass(frozen=True)
class DocsyncConfig:
    """docsync.yaml: the sources in scope and where their Docs live in Google Drive.

    `drive_folder_id` is the "DFO docs" folder itself. Docs go in folders under it, and
    the tracking Sheet sits in it, found by its Drive property `dfo_role`.
    `pr_author` is the gh `--author` value docsync's pull requests are listed by:
    `app/<slug>` for the GitHub App that opens them in CI.
    """

    sources: tuple[str, ...]
    drive_folder_id: str
    pr_author: str


@dataclass(frozen=True)
class SyncPage:
    """One page docsync publishes as a Google Doc.

    `page_id` and `title` equal the manifest `Page`'s `id` and `title`. `section_path`
    holds the titles of the nav groups the page sits under, outermost first, and is empty
    for a top-level hub page. `path` is relative to `clone_root`, the git checkout the
    page was read from, and `text` is that file's raw content at `commit`, so
    `git -C <clone_root> show <commit>:<path>` reproduces it. `ref` is the branch
    `commit` was read from, which edits are proposed against.
    """

    page_id: str
    title: str
    section_path: tuple[str, ...]
    repo: str
    ref: str
    commit: str
    path: str
    text: str
    clone_root: Path


def load_config(path: Path) -> DocsyncConfig:
    """Load docsync.yaml.

    Raises:
        DocsyncConfigError: the file is missing or malformed, `sources` is not a
            non-empty list of unique names, `drive_folder_id` or `pr_author` is not
            set, or the file holds any other key.
    """
    raw = _read_yaml(path)
    unknown = sorted(set(raw) - _CONFIG_KEYS)
    if unknown:
        raise DocsyncConfigError(f"{path}: unknown keys {unknown}")
    sources = raw.get("sources")
    if (
        not isinstance(sources, list)
        or not sources
        or not all(isinstance(name, str) for name in sources)
    ):
        raise DocsyncConfigError(f"{path}: sources must be a non-empty list of names")
    if len(set(sources)) != len(sources):
        raise DocsyncConfigError(f"{path}: sources lists a name more than once")

    folder_id = raw.get("drive_folder_id")
    if not isinstance(folder_id, str) or not folder_id:
        raise DocsyncConfigError(f"{path}: drive_folder_id is not set")

    pr_author = raw.get("pr_author")
    if not isinstance(pr_author, str) or not pr_author:
        raise DocsyncConfigError(f"{path}: pr_author is not set")

    return DocsyncConfig(
        sources=tuple(sources), drive_folder_id=folder_id, pr_author=pr_author
    )


def load_sync_pages(
    config: DocsyncConfig, *, repo_root: Path, workdir: Path
) -> tuple[SyncPage, ...]:
    """Fetch every source `config` allowlists and return its pages, in nav order.

    Each fetched source is cloned to `workdir/<name>` and stays there for the caller,
    who reads past commits and pushes branches from it. Hub pages are read from
    `repo_root` at its `HEAD`, on the branch checked out there.

    Raises:
        DocsyncConfigError: an allowlisted name is not `hub` or an enabled `docs` or
            `skill` row of sources.yaml that hub.yaml mounts.
        HubCheckoutError: `content/hub/` or `hub.yaml` has uncommitted changes while
            `hub` is allowlisted, or `repo_root` has no branch checked out.
        GitError: a git command on a clone failed.
        FetchError: one or more sources failed to fetch.
    """
    sources = load_sources(repo_root / _SOURCES_FILE)
    hub = load_hub(repo_root / _HUB_FILE)
    allowed = _allowed_sources(config, sources=sources, hub=hub)

    fetched = fetch_all(allowed.values(), workdir=workdir)
    clones = {item.source.name: _Clone.from_fetched(item) for item in fetched}
    if HUB in config.sources:
        clones[HUB] = _Clone.from_hub(repo_root)

    hub_in_scope = _prune_hub(hub, allowed=set(config.sources))
    with tempfile.TemporaryDirectory(prefix="dfo_docsync-corpus-") as corpus:
        nav, pages = build_pages(
            allowed,
            hub_in_scope,
            fetched,
            repo_root=repo_root,
            hub_content_root=repo_root / _HUB_CONTENT_DIR,
            corpus_root=Path(corpus),
        )

    by_id = {page.id: page for page in pages}
    placed = list(_nav_pages(nav, section_path=()))
    if sorted(page_id for page_id, _ in placed) != sorted(by_id):
        raise RuntimeError("the nav and the page list built for docsync disagree")

    return tuple(
        _sync_page(by_id[page_id], section_path=section_path, clones=clones)
        for page_id, section_path in placed
    )


@dataclass(frozen=True)
class _Clone:
    """A git checkout pages are read from, and the commit and branch they are read at."""

    root: Path
    commit: str
    ref: str

    @classmethod
    def from_fetched(cls, fetched: Fetched) -> _Clone:
        ref = fetched.source.ref
        assert ref is not None  # registry defaults `ref` on every fetched kind
        return cls(root=fetched.repo_root, commit=fetched.commit, ref=ref)

    @classmethod
    def from_hub(cls, repo_root: Path) -> _Clone:
        dirty = _git(
            repo_root, "status", "--porcelain", "--", _HUB_CONTENT_DIR, _HUB_FILE
        )
        if dirty.strip():
            raise HubCheckoutError(
                f"{repo_root}: {_HUB_CONTENT_DIR}/ or {_HUB_FILE} has uncommitted "
                f"changes; commit them before syncing hub pages:\n{dirty.rstrip()}"
            )
        ref = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        if ref == "HEAD":
            raise HubCheckoutError(f"{repo_root}: no branch is checked out")
        commit = _git(repo_root, "rev-parse", "HEAD").strip()
        return cls(root=repo_root, commit=commit, ref=ref)


def _allowed_sources(
    config: DocsyncConfig, *, sources: Mapping[str, Source], hub: HubNode
) -> dict[str, Source]:
    """The registry rows `config` allowlists, keyed by name, with `hub` left out."""
    mounted = {node.mount for node in _walk(hub) if node.mount is not None}
    allowed: dict[str, Source] = {}
    for name in config.sources:
        if name == HUB:
            continue
        source = sources.get(name)
        if source is None:
            raise DocsyncConfigError(f"{name!r} is not a source in {_SOURCES_FILE}")
        if not source.enabled:
            raise DocsyncConfigError(f"{name!r} is disabled in {_SOURCES_FILE}")
        if source.kind not in FETCHED_KINDS:
            raise DocsyncConfigError(
                f"{name!r} is a {source.kind.value!r} source, which publishes no pages"
            )
        if name not in mounted:
            raise DocsyncConfigError(f"{name!r} is not mounted in {_HUB_FILE}")
        allowed[name] = source
    return allowed


def _prune_hub(hub: HubNode, *, allowed: set[str]) -> HubNode:
    """`hub` keeping only the hub pages (if `hub` is allowed) and the allowed mounts.

    A heading left with no children is dropped. Group and page ids depend only on a
    node's own title or name and its ancestors', so pruning leaves every kept id alone.
    """

    def prune(nodes: Sequence[HubNode]) -> tuple[HubNode, ...]:
        kept: list[HubNode] = []
        for node in nodes:
            if node.page is not None:
                if HUB in allowed:
                    kept.append(node)
            elif node.mount is not None:
                if node.mount in allowed:
                    kept.append(node)
            elif node.external is None and (children := prune(node.children)):
                kept.append(HubNode(title=node.title, children=children))
        return tuple(kept)

    return HubNode(title=hub.title, children=prune(hub.children))


def _walk(node: HubNode) -> Iterator[HubNode]:
    yield node
    for child in node.children:
        yield from _walk(child)


def _nav_pages(
    nodes: Sequence[NavNode], *, section_path: tuple[str, ...]
) -> Iterator[tuple[str, tuple[str, ...]]]:
    """Every page id in `nodes`, in nav order, with the group titles it sits under.

    A group's landing page sits inside the group, ahead of its children.
    """
    for node in nodes:
        if node.children or node.page_id is not None:
            inner = (*section_path, node.title)
            if node.page_id is not None:
                yield node.page_id, inner
            yield from _nav_pages(node.children, section_path=inner)
        else:
            yield node.id, section_path


def _sync_page(
    page: Page, *, section_path: tuple[str, ...], clones: Mapping[str, _Clone]
) -> SyncPage:
    assert page.source_path is not None  # only external pages lack one
    clone = clones[page.id.partition("/")[0]]
    return SyncPage(
        page_id=page.id,
        title=page.title,
        section_path=section_path,
        repo=page.source_repo,
        ref=clone.ref,
        commit=clone.commit,
        path=page.source_path,
        text=_git(clone.root, "show", f"{clone.commit}:{page.source_path}"),
        clone_root=clone.root,
    )


def _git(cwd: Path, *args: str) -> str:
    return Git(root=cwd, env=command_env(None)).run(*args)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text()
    except FileNotFoundError as exc:
        raise DocsyncConfigError(f"{path}: file not found") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise DocsyncConfigError(f"{path}: {describe_yaml_error(exc)}") from exc
    if not isinstance(data, dict):
        raise DocsyncConfigError(f"{path}: expected a mapping at the top level")
    return data
