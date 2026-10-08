"""Locate and parse a source repository's docs sidecar.

Four sidecar shapes exist. `docs/mkdocs.yml` beside `docs/docs/*.md` (the nested shape seven
repositories share). A root `mkdocs.yml` beside `docs/*.md`, carrying either the historical
`site_name` fields or the plain `path`/`title` fields a new repository writes. And a root
`zensical.toml` beside `docs/*.md`. The docs root is resolved relative to wherever the sidecar
itself sits rather than by stripping a fixed number of path segments, which is what lets all four
converge on the same field resolution and the same nav walk.
"""

from __future__ import annotations

import fnmatch
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

from dfo_docs.models import NavEntry, Sidecar, Source, SourceKind
from dfo_docs.yaml_errors import describe_yaml_error

_SIDECAR_CANDIDATES = ("docs/mkdocs.yml", "mkdocs.yml", "zensical.toml")
_H1_RE = re.compile(r"^#(?!#)\s+(.+?)\s*$", re.MULTILINE)


class SidecarError(ValueError):
    """A source repository's sidecar is missing or malformed."""


def find_sidecar(repo_root: Path) -> Path:
    """Locate a repository's docs sidecar.

    Checked in order: `docs/mkdocs.yml`, root `mkdocs.yml`, and root `zensical.toml`. Raises
    SidecarError if none of the three exists.
    """
    for candidate in _SIDECAR_CANDIDATES:
        sidecar_path = repo_root / candidate
        if sidecar_path.is_file():
            return sidecar_path
    tried = ", ".join(_SIDECAR_CANDIDATES)
    raise SidecarError(f"no sidecar found under {repo_root} (tried {tried})")


def load_sidecar(repo_root: Path, source: Source) -> Sidecar:
    """Find, resolve, and parse `source`'s sidecar into a Sidecar.

    The docs root is a `docs_dir`-named subdirectory (default `docs`) of whichever directory the
    sidecar itself sits in. Resolving a bare nav entry's title reads that file for its first H1,
    so `repo_root` must already be a fetched, on-disk tree.

    `docs_root` is required to stay under `repo_root`, and every nav entry's file is required to
    stay under `docs_root`; both raise `SidecarError` naming the source and the offending value
    rather than reading past the source repository's own tree. For a `kind: docs` row,
    `source.path` (when set) is an assertion against the path the sidecar resolves to, not a
    second source of truth: a mismatch raises `SidecarError` naming both values. `kind: external`
    rows never reach this function, and `source.path` stays their only path.

    `source.exclude` is applied after the walk, so `nav` carries what this corpus publishes and
    `excluded` carries what the row held back.
    """
    sidecar_path = find_sidecar(repo_root)
    raw = _read_config(sidecar_path)

    docs_dir = raw.get("docs_dir", "docs")
    docs_root = sidecar_path.parent / docs_dir
    resolve_contained(
        docs_root,
        root=repo_root,
        error=f"{source.name!r}: docs_dir {docs_dir!r}",
        error_type=SidecarError,
    )

    nav = _walk_nav(
        raw.get("nav", []), docs_root=docs_root, source=source, breadcrumb=()
    )
    if not nav:
        raise SidecarError(
            f"{source.name!r}: {sidecar_path.name} declares no nav, so the source would "
            f"publish nothing. In a zensical.toml this usually means the nav array sits "
            f"after a [project.<table>] header and TOML has scoped it into that table."
        )
    nav, excluded = _apply_exclusions(nav, source)

    path = _resolve_path(raw, source)
    if (
        source.kind is SourceKind.DOCS
        and source.path is not None
        and source.path != path
    ):
        raise SidecarError(
            f"{source.name!r}: sources.yaml declares path {source.path!r}, "
            f"sidecar resolves to {path!r}"
        )

    return Sidecar(
        path=path,
        title=_resolve_title(raw, source),
        description=raw.get("site_description"),
        nav=nav,
        docs_root=docs_root,
        excluded=excluded,
        docs_url=_dfo_extra_docs_url(raw),
    )


def _apply_exclusions(
    nav: tuple[NavEntry, ...], source: Source
) -> tuple[tuple[NavEntry, ...], tuple[str, ...]]:
    """Split `nav` into the entries this corpus admits and the files `source.exclude` holds back.

    Patterns are globs matched against an entry's docs-root-relative path, so `reference/*`
    excludes a section and `reference/query.md` excludes one page. A pattern that matches no nav
    entry raises `SidecarError` naming it, since a pattern surviving an upstream rename would
    otherwise start admitting the pages it was written to keep out, silently.

    A nav group whose every entry is excluded leaves no trace. `manifest.build_pages` rebuilds
    nesting from the breadcrumbs the surviving entries carry, so a group nothing survives under is
    never built in the first place.
    """
    if not source.exclude:
        return nav, ()

    kept: list[NavEntry] = []
    excluded: list[str] = []
    matched: set[str] = set()
    for entry in nav:
        hit = next(
            (p for p in source.exclude if fnmatch.fnmatch(entry.file, p)),
            None,
        )
        if hit is None:
            kept.append(entry)
        else:
            excluded.append(entry.file)
            matched.add(hit)

    unused = [p for p in source.exclude if p not in matched]
    if unused:
        raise SidecarError(
            f"{source.name!r}: exclude pattern(s) {', '.join(repr(p) for p in unused)} "
            f"match no nav entry"
        )

    return tuple(kept), tuple(excluded)


def resolve_contained(
    candidate: Path, *, root: Path, error: str, error_type: type[Exception]
) -> Path:
    """Resolve `candidate` and confirm it stays under `root`, returning the resolved path.

    The one containment rule for every file a source publishes: `load_sidecar` applies it
    to a docs source's docs_dir and nav entries, and `skills.load_skills` to a skill
    source's docs root, skill directories, and files.

    Mirrors `normalise.expand_transclusion`: both sides are fully resolved, so a symlink chain
    or a symlinked directory is followed rather than sidestepped, and compared with
    `Path.is_relative_to` rather than a string prefix. A string prefix is the classic bypass,
    since `/tmp/clone-evil` starts with `/tmp/clone`.

    Raises `error_type`, prefixed with `error`, naming the offending value and `root`.
    """
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise error_type(f"{error} resolves outside {root}: {candidate}")
    return resolved


def nav_source_path(sidecar: Sidecar, repo_root: Path, file: str) -> str:
    """A nav entry's `file`, named relative to `repo_root` instead of `sidecar.docs_root`.

    `sidecar.docs_root` sits under a temporary fetch directory that differs on every
    run and means nothing to whoever has to act on a finding or a manifest entry;
    `guards.check_nav_drift` and `manifest.build_pages` both name a nav entry's file
    this way instead, relative to the source repository's own root.
    """
    return (sidecar.docs_root.relative_to(repo_root) / file).as_posix()


def _read_config(path: Path) -> dict[str, Any]:
    """Read a sidecar file into a plain mapping, regardless of its format.

    A `zensical.toml` carries everything the parser needs under its `[project]` table; the YAML
    shapes carry it at the top level. Raises `SidecarError`, naming the file and the parser's own
    line and column, if the file cannot be read or fails to parse.
    """
    try:
        text = path.read_text()
    except FileNotFoundError as exc:
        raise SidecarError(f"{path}: file not found") from exc

    if path.suffix == ".toml":
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise SidecarError(f"{path}: {exc}") from exc
        project = data.get("project")
        if not isinstance(project, dict):
            raise SidecarError(f"{path}: expected a [project] table")
        return project

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SidecarError(f"{path}: {describe_yaml_error(exc)}") from exc
    if not isinstance(data, dict):
        raise SidecarError(f"{path}: expected a mapping at the top level")
    return data


def _resolve_path(raw: dict[str, Any], source: Source) -> str:
    """Read the public path: `extra.dfo.path`, falling back to `path`, then `site_name`."""
    path = _dfo_extra_path(raw) or raw.get("path") or raw.get("site_name")
    if not path:
        raise SidecarError(f"{source.name!r}: sidecar declares no path")
    return path


def _resolve_title(raw: dict[str, Any], source: Source) -> str:
    """Read the display title: `title`, then `site_name`, then `source.title`, then the
    source's own name.

    `site_name` is skipped for the title when it looks like a path (it carries a `/`), since that
    means it is already supplying the public path and must not also become an unreadable title.
    `source.title` is the registry's bridge title for a source whose sidecar carries no real
    title yet; a sidecar that declares its own still wins over it, which is what makes the bridge
    disappear on its own once the source repository is updated.
    """
    title = raw.get("title")
    if title:
        return title

    site_name = raw.get("site_name")
    if site_name and "/" not in site_name:
        return site_name

    if source.title:
        return source.title

    return source.name


def _dfo_extra_path(raw: dict[str, Any]) -> str | None:
    return _dfo_extra(raw).get("path")


def _dfo_extra_docs_url(raw: dict[str, Any]) -> str | None:
    """Read `extra.dfo.docs_url`. Absent is legal; there is no `site_url` fallback.

    See `Sidecar.docs_url` for why: the one live `site_url` is a bare repository root that
    404s for exactly the pages this field exists to rewrite links into.
    """
    return _dfo_extra(raw).get("docs_url")


def _dfo_extra(raw: dict[str, Any]) -> dict[str, Any]:
    extra = raw.get("extra")
    if not isinstance(extra, dict):
        return {}
    dfo = extra.get("dfo")
    if not isinstance(dfo, dict):
        return {}
    return dfo


def _walk_nav(
    items: list[Any], *, docs_root: Path, source: Source, breadcrumb: tuple[str, ...]
) -> tuple[NavEntry, ...]:
    """Walk a parsed nav list into ordered NavEntry records.

    Each item is either a bare file (`index.md`), a titled leaf (`{"Getting started":
    "getting-started.md"}`), or a group (`{"Available data importers": [...]}`) whose children
    are walked recursively with the group's title appended to their breadcrumb. Every existing
    sidecar nests one level deep; this handles arbitrary depth regardless.
    """
    entries: list[NavEntry] = []
    for item in items:
        if isinstance(item, str):
            entries.append(
                _leaf(
                    item,
                    title=None,
                    breadcrumb=breadcrumb,
                    docs_root=docs_root,
                    source=source,
                )
            )
            continue

        if not isinstance(item, dict) or len(item) != 1:
            raise SidecarError(f"unrecognised nav entry: {item!r}")
        ((title, value),) = item.items()

        if isinstance(value, str):
            entries.append(
                _leaf(
                    value,
                    title=title,
                    breadcrumb=breadcrumb,
                    docs_root=docs_root,
                    source=source,
                )
            )
        elif isinstance(value, list):
            entries.extend(
                _walk_nav(
                    value,
                    docs_root=docs_root,
                    source=source,
                    breadcrumb=(*breadcrumb, title),
                )
            )
        else:
            raise SidecarError(f"unrecognised nav group {title!r}: {value!r}")

    return tuple(entries)


def _leaf(
    file: str,
    *,
    title: str | None,
    breadcrumb: tuple[str, ...],
    docs_root: Path,
    source: Source,
) -> NavEntry:
    candidate = docs_root / file
    # Checked inline, before the H1 read below, so an escaping entry is rejected before its
    # bytes are ever touched rather than after.
    resolve_contained(
        candidate,
        root=docs_root,
        error=f"{source.name!r}: nav entry {file!r}",
        error_type=SidecarError,
    )
    resolved_title = title if title is not None else _title_from_file(candidate)
    return NavEntry(file=file, title=resolved_title, breadcrumb=breadcrumb)


def _title_from_file(md_path: Path) -> str:
    """A bare entry's title is the file's first H1, or the de-kebabed filename if it has none."""
    return title_from_text(md_path.read_text(), md_path.stem)


def title_from_text(text: str, stem: str) -> str:
    """A page's title when nothing upstream names it is `text`'s first H1, or the
    de-kebabed filename `stem`.

    Shared with `manifest._hub_pages`, which already has the page's text in hand (it
    reads it for other reasons first) and so calls this directly instead of going
    through `_title_from_file`, which would read the same file again.
    """
    match = _H1_RE.search(text)
    if match:
        return match.group(1).strip()
    return de_kebab(stem)


def de_kebab(stem: str) -> str:
    """A kebab- or snake-case name as a sentence-case title, `flow-types` to `Flow types`."""
    text = " ".join(stem.replace("_", "-").split("-"))
    return text[:1].upper() + text[1:]
