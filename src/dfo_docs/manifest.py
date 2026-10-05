"""Assemble manifest.json and the corpus tree it describes.

Walks `hub.yaml`, the ordering authority, into a `NavNode` tree, expanding each mounted
source's own sidecar nav in place, or, for a `kind: skill` source, the skills
`skills.load_skills` walks from its tree. Walks each fetched source a second time
to normalise every page it finds and write it under `corpus/<source.name>/`, and does
the same for the hub's own content in `content/hub/`, whose pages mount at the corpus
root rather than under a source's own path. Adds one `Page` per enabled `kind: external`
row. Where a page sits is recorded once, in the `NavNode` tree, and a `Page` carries no
copy of it.

`build_pages` is the entry point `cli.py` calls; `write_manifest` serialises its
result to disk.
"""

from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Callable, Mapping, Sequence
from functools import partial
from pathlib import Path, PurePosixPath

import yaml

from dfo_docs.fetch import last_modified
from dfo_docs.models import (
    Fetched,
    HubNode,
    Manifest,
    NavEntry,
    NavKind,
    NavNode,
    Page,
    PageKind,
    Sidecar,
    Source,
    SourceKind,
)
from dfo_docs.normalise import FRONTMATTER_RE, normalise_markdown
from dfo_docs.sidecar import load_sidecar, title_from_text
from dfo_docs.skills import Skill, load_skills, skill_page_text

# The hub's own content has no registered Source, so it is given a stand-in name and
# repo shorthand consistent with the "owner/name" shape every other source_repo carries.
_HUB_SOURCE_NAME = "hub"
_HUB_SOURCE_REPO = "ONEcampaign/dfo-docs"
# The hub page each generated skill header links to, relative to the hub's content root.
_SKILL_INSTALL_PAGE = "skills/use-in-your-agent.md"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class ManifestError(ValueError):
    """A source's sidecar navigates a file that does not exist on disk, or `hub.yaml`
    mounts a source that was not fetched.

    `dfo_docs.guards.check_nav_drift` is meant to catch a missing navigated file first
    and name it per source before any page is built, so that case is a backstop rather
    than the primary defence. It turns what would otherwise be a bare `FileNotFoundError`
    into an error that names the source, the nav entry, and the path it expected to find.
    """


def build_pages(
    sources: Mapping[str, Source],
    hub: HubNode,
    fetched: Sequence[Fetched],
    *,
    repo_root: Path,
    hub_content_root: Path,
    corpus_root: Path,
) -> tuple[list[NavNode], list[Page]]:
    """Assemble the nav tree and every manifest Page, and write the corpus tree that
    backs them.

    Walks `hub`, which is the ordering authority, into a `NavNode` tree: a `page` leaf
    becomes a `page` node, a `mount` leaf becomes a `group` node expanding that source's
    own sidecar nav (folding a leading `index.md` into the group's own `page_id` rather
    than a child leaf), and an `external` leaf becomes a single `external` node.

    Also walks each `Fetched` source's sidecar nav to normalise each page's markdown and
    write it under `corpus_root/<source.name>/`, walks `hub`'s own nav for the pages
    under `hub_content_root` and writes them under `corpus_root/hub/`, and adds one
    `Page` for every enabled `kind: external` row in `sources`, carrying a `url` and no
    file.

    A `mount` of a `kind: skill` source becomes a group titled by `Source.title`, with
    no landing page, holding one node per skill: a group whose `page_id` is the skill
    page when the skill has reference files, which are its children, and a `page` leaf
    when it has none.

    `sources` supplies the external rows and may be the full registry or just the
    enabled subset; a disabled row is skipped either way. `fetched` drives the
    `docs`- and `skill`-kind pages and nav subtrees. `repo_root` is dfo-docs's own repository root,
    against which a hub page's transclusion targets (if any) resolve.

    Returns `(nav, pages)`. `pages` array order carries no meaning; ordering comes from
    flattening `nav`.
    """
    sidecars = {
        item.source.name: load_sidecar(item.repo_root, item.source)
        for item in fetched
        if item.source.kind is SourceKind.DOCS
    }
    skill_sets = {
        item.source.name: load_skills(item)
        for item in fetched
        if item.source.kind is SourceKind.SKILL
    }

    nav = _build_nav_children(
        hub.children,
        sidecars=sidecars,
        skill_sets=skill_sets,
        sources=sources,
        hub_content_root=hub_content_root,
        key_path=(),
    )

    pages: list[Page] = []
    pages.extend(
        _hub_pages(
            hub,
            hub_content_root=hub_content_root,
            corpus_root=corpus_root,
            repo_root=repo_root,
        )
    )
    for item in fetched:
        name = item.source.name
        if name in skill_sets:
            pages.extend(_skill_pages(item, skill_sets[name], corpus_root=corpus_root))
        else:
            pages.extend(_source_pages(item, sidecars[name], corpus_root=corpus_root))
    pages.extend(
        _external_page(source)
        for source in sources.values()
        if source.enabled and source.kind is SourceKind.EXTERNAL
    )
    return nav, pages


def write_manifest(manifest: Manifest, path: Path) -> None:
    """Write `manifest` to `path` as the manifest.json envelope the site reads."""
    raw: dict[str, object] = {
        "schema_version": manifest.schema_version,
        "generated_at": manifest.generated_at,
        "generator_commit": manifest.generator_commit,
        "nav": [_nav_json(node) for node in manifest.nav],
        "pages": [_page_json(page) for page in manifest.pages],
    }
    payload = {key: value for key, value in raw.items() if value is not None}
    path.write_text(json.dumps(payload, indent=2) + "\n")


# --- Nav tree construction --------------------------------------------------------


def _build_nav_children(
    nodes: Sequence[HubNode],
    *,
    sidecars: Mapping[str, Sidecar],
    skill_sets: Mapping[str, Sequence[Skill]],
    sources: Mapping[str, Source],
    hub_content_root: Path,
    key_path: tuple[str, ...],
) -> list[NavNode]:
    """Build the `NavNode` list for one level of `hub.yaml`'s tree."""
    result: list[NavNode] = []
    for node in nodes:
        if node.page is not None:
            result.append(_hub_page_nav_node(node, hub_content_root=hub_content_root))
        elif node.mount is not None and node.mount in skill_sets:
            result.append(
                _skill_mount_nav_node(
                    sources[node.mount], skill_sets[node.mount], key_path=key_path
                )
            )
        elif node.mount is not None:
            result.append(
                _mount_nav_node(node.mount, sidecars=sidecars, key_path=key_path)
            )
        elif node.external is not None:
            result.append(_external_nav_node(node.external, sources=sources))
        else:
            result.append(
                _heading_nav_node(
                    node,
                    sidecars=sidecars,
                    skill_sets=skill_sets,
                    sources=sources,
                    hub_content_root=hub_content_root,
                    key_path=key_path,
                )
            )
    return result


def _hub_page_nav_node(node: HubNode, *, hub_content_root: Path) -> NavNode:
    assert node.page is not None
    slug = _page_slug(node.page)
    title = (
        node.title
        if node.title is not None
        else title_from_text(
            (hub_content_root / node.page).read_text(), PurePosixPath(node.page).stem
        )
    )
    return NavNode(
        id=_page_id(_HUB_SOURCE_NAME, slug),
        title=title,
        kind=NavKind.PAGE,
    )


def _mount_nav_node(
    mount: str, *, sidecars: Mapping[str, Sidecar], key_path: tuple[str, ...]
) -> NavNode:
    if mount not in sidecars:
        raise ManifestError(f"hub.yaml mounts {mount!r}, which was not fetched")
    sidecar = sidecars[mount]
    group_key = (*key_path, mount)
    landing, children = _build_source_nav(
        mount, sidecar.nav, depth=0, key_path=group_key, path_prefix=sidecar.path
    )
    return NavNode(
        id=_group_id(group_key),
        title=sidecar.title,
        kind=NavKind.GROUP,
        page_id=landing,
        children=tuple(children),
    )


def _skill_mount_nav_node(
    source: Source, skills: Sequence[Skill], *, key_path: tuple[str, ...]
) -> NavNode:
    assert source.title is not None  # registry requires `title` on a skill row
    group_key = (*key_path, source.name)
    children = []
    for skill in skills:
        page_id = _page_id(source.name, skill.directory)
        if not skill.references:
            children.append(NavNode(id=page_id, title=skill.name, kind=NavKind.PAGE))
            continue
        references = tuple(
            NavNode(
                id=_page_id(source.name, _page_slug(reference.file)),
                title=reference.title,
                kind=NavKind.PAGE,
            )
            for reference in skill.references
        )
        children.append(
            NavNode(
                id=_group_id((*group_key, skill.directory)),
                title=skill.name,
                kind=NavKind.GROUP,
                page_id=page_id,
                children=references,
            )
        )
    return NavNode(
        id=_group_id(group_key),
        title=source.title,
        kind=NavKind.GROUP,
        children=tuple(children),
    )


def _external_nav_node(external: str, *, sources: Mapping[str, Source]) -> NavNode:
    if external not in sources:
        raise ManifestError(
            f"hub.yaml mounts external {external!r}, which is not registered"
        )
    source = sources[external]
    return NavNode(
        id=source.name,
        title=source.title or source.name,
        kind=NavKind.EXTERNAL,
    )


def _heading_nav_node(
    node: HubNode,
    *,
    sidecars: Mapping[str, Sidecar],
    skill_sets: Mapping[str, Sequence[Skill]],
    sources: Mapping[str, Source],
    hub_content_root: Path,
    key_path: tuple[str, ...],
) -> NavNode:
    assert node.title is not None
    group_key = (*key_path, _slugify(node.title))
    children = _build_nav_children(
        node.children,
        sidecars=sidecars,
        skill_sets=skill_sets,
        sources=sources,
        hub_content_root=hub_content_root,
        key_path=group_key,
    )
    return NavNode(
        id=_group_id(group_key),
        title=node.title,
        kind=NavKind.GROUP,
        children=tuple(children),
    )


def _build_source_nav(
    source_name: str,
    entries: Sequence[NavEntry],
    *,
    depth: int,
    key_path: tuple[str, ...],
    path_prefix: str,
) -> tuple[str | None, list[NavNode]]:
    """Build one source-nav group's own landing page id, if it has one, and its
    `NavNode` children.

    Rebuilds nesting from consecutive runs of matching `NavEntry.breadcrumb`, since
    `sidecar._walk_nav` flattens the whole nav into one list. A group's own leading
    `index.md`, at this level (not nested one level deeper), becomes its landing page
    instead of a child leaf; called once for the source's own top-level nav (`depth=0`)
    and recursively for each nested grouping heading inside it.
    """
    landing: str | None = None
    if entries and len(entries[0].breadcrumb) == depth and _is_index(entries[0].file):
        landing = _page_id(source_name, _page_slug(entries[0].file))
        entries = entries[1:]

    children: list[NavNode] = []
    position = 0
    total = len(entries)
    while position < total:
        entry = entries[position]
        if len(entry.breadcrumb) > depth:
            group_title = entry.breadcrumb[depth]
            end = position
            while (
                end < total
                and len(entries[end].breadcrumb) > depth
                and entries[end].breadcrumb[depth] == group_title
            ):
                end += 1
            sub_key = (*key_path, _slugify(group_title))
            sub_landing, sub_children = _build_source_nav(
                source_name,
                entries[position:end],
                depth=depth + 1,
                key_path=sub_key,
                path_prefix=path_prefix,
            )
            children.append(
                NavNode(
                    id=_group_id(sub_key),
                    title=group_title,
                    kind=NavKind.GROUP,
                    page_id=sub_landing,
                    children=tuple(sub_children),
                )
            )
            position = end
        else:
            slug = _page_slug(entry.file)
            children.append(
                NavNode(
                    id=_page_id(source_name, slug),
                    title=entry.title or entry.file,
                    kind=NavKind.PAGE,
                )
            )
            position += 1

    return landing, children


def _group_id(key_path: tuple[str, ...]) -> str:
    return "group:" + "/".join(key_path)


def _is_index(file: str) -> bool:
    return PurePosixPath(file).name == "index.md"


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-")


# --- Page construction -------------------------------------------------------------


def _source_pages(
    fetched: Fetched,
    sidecar: Sidecar,
    *,
    corpus_root: Path,
) -> list[Page]:
    return [
        _fetched_page(
            fetched,
            docs_root=sidecar.docs_root,
            file=nav_entry.file,
            slug=_page_slug(nav_entry.file),
            path_prefix=sidecar.path,
            title=nav_entry.title or nav_entry.file,
            kind=PageKind.PAGE,
            corpus_root=corpus_root,
            excluded=sidecar.excluded,
            docs_url=sidecar.docs_url,
        )
        for nav_entry in sidecar.nav
    ]


def _skill_pages(
    fetched: Fetched, skills: Sequence[Skill], *, corpus_root: Path
) -> list[Page]:
    """One `skill` page per skill, with the generated header, and one `page` per
    reference file. Paths follow the files: `<path>/<skill>` for a skill and
    `<path>/<skill>/references/<stem>` for a reference."""
    source = fetched.source
    assert source.path is not None  # registry requires `path` on a skill row
    install_target = f"{_HUB_SOURCE_NAME}/{_SKILL_INSTALL_PAGE}"

    pages = []
    for skill in skills:
        install_link = posixpath.relpath(
            install_target, f"{source.name}/{skill.directory}"
        )
        pages.append(
            _fetched_page(
                fetched,
                docs_root=fetched.docs_root,
                file=skill.file,
                slug=skill.directory,
                path_prefix=source.path,
                title=skill.name,
                kind=PageKind.SKILL,
                corpus_root=corpus_root,
                transform=partial(
                    skill_page_text, skill=skill, install_link=install_link
                ),
            )
        )
        pages.extend(
            _fetched_page(
                fetched,
                docs_root=fetched.docs_root,
                file=reference.file,
                slug=_page_slug(reference.file),
                path_prefix=source.path,
                title=reference.title,
                kind=PageKind.PAGE,
                corpus_root=corpus_root,
            )
            for reference in skill.references
        )
    return pages


def _fetched_page(
    fetched: Fetched,
    *,
    docs_root: Path,
    file: str,
    slug: str,
    path_prefix: str,
    title: str,
    kind: PageKind,
    corpus_root: Path,
    excluded: tuple[str, ...] = (),
    docs_url: str | None = None,
    transform: Callable[[str], str] | None = None,
) -> Page:
    """Read `docs_root / file`, apply `transform` if given, normalise the result, write
    it to `corpus/<source>/<file>`, and return its `Page`, whose description is the
    text's front matter `description`.

    Raises `ManifestError`, naming the file relative to the source repository, if the
    file does not exist.
    """
    source = fetched.source
    source_path = (docs_root.relative_to(fetched.repo_root) / file).as_posix()
    try:
        text = (docs_root / file).read_text()
    except FileNotFoundError as exc:
        raise ManifestError(
            f"{source.name!r} publishes {source_path!r}, which does not exist in "
            f"{source.repo}"
        ) from exc
    if transform is not None:
        text = transform(text)

    _write_corpus_file(
        corpus_root / source.name / file,
        normalise_markdown(
            text,
            repo_root=fetched.repo_root,
            page_path=docs_root / file,
            docs_root=docs_root,
            source_name=source.name,
            excluded=excluded,
            docs_url=docs_url,
        ),
    )

    return Page(
        id=_page_id(source.name, slug),
        path=_join_path(path_prefix, slug),
        title=title,
        kind=kind,
        description=_frontmatter_description(text),
        source_repo=source.repo,
        source_path=source_path,
        source_commit=fetched.commit,
        last_modified=last_modified(fetched.repo_root, source_path),
        corpus_path=f"corpus/{source.name}/{file}",
    )


def _hub_pages(
    hub: HubNode,
    *,
    hub_content_root: Path,
    corpus_root: Path,
    repo_root: Path,
) -> list[Page]:
    pages = []
    for file, page_title in _hub_nav_pages(hub):
        source_file = hub_content_root / file
        raw_text = source_file.read_text()
        slug = _page_slug(file)
        page_id = _page_id(_HUB_SOURCE_NAME, slug)
        title = (
            page_title
            if page_title is not None
            else title_from_text(raw_text, PurePosixPath(file).stem)
        )

        _write_corpus_file(
            corpus_root / _HUB_SOURCE_NAME / file,
            normalise_markdown(
                raw_text,
                repo_root=repo_root,
                page_path=source_file,
                docs_root=hub_content_root,
            ),
        )

        pages.append(
            Page(
                id=page_id,
                path=_join_path("", slug),
                title=title,
                kind=PageKind.PAGE,
                description=_frontmatter_description(raw_text),
                source_repo=_HUB_SOURCE_REPO,
                # No git plumbing tracks the hub's own commit history. Hub content lives
                # directly in this repository rather than being `fetched`, so there is no
                # resolved commit or per-file `git log` lookup to read here, and
                # provenance narrower than the file's own location is left unset rather
                # than faked.
                source_path=f"content/hub/{file}",
                source_commit=None,
                last_modified=None,
                corpus_path=f"corpus/{_HUB_SOURCE_NAME}/{file}",
            )
        )
    return pages


def _hub_nav_pages(hub: HubNode) -> list[tuple[str, str | None]]:
    """Every hub.yaml node carrying `page`, as (file, title), in nav order."""
    pages: list[tuple[str, str | None]] = []

    def walk(node: HubNode) -> None:
        if node.page is not None:
            pages.append((node.page, node.title))
        for child in node.children:
            walk(child)

    for child in hub.children:
        walk(child)
    return pages


def _external_page(source: Source) -> Page:
    return Page(
        id=source.name,
        path=source.path or source.name,
        title=source.title or source.name,
        kind=PageKind.EXTERNAL,
        description="",
        source_repo=source.repo,
        source_path=None,
        source_commit=None,
        last_modified=None,
        corpus_path=None,
        url=source.url,
    )


def _page_id(name: str, slug: str) -> str:
    return f"{name}/{slug}" if slug else name


def _join_path(prefix: str, slug: str) -> str:
    if not slug:
        return prefix
    if not prefix:
        return slug
    return f"{prefix}/{slug}"


def _page_slug(file: str) -> str:
    """The page's own portion of its public path, with `.md` dropped and `index.md`
    collapsed to its directory (or to nothing, at the docs root)."""
    location = PurePosixPath(file)
    if location.name == "index.md":
        parent = location.parent
        return "" if parent == PurePosixPath(".") else parent.as_posix()
    return location.with_suffix("").as_posix()


def _frontmatter_description(text: str) -> str:
    """The page's frontmatter `description`, or "" if there is none."""
    match = FRONTMATTER_RE.match(text)
    if match is None:
        return ""
    frontmatter = yaml.safe_load(match.group("body"))
    if not isinstance(frontmatter, dict):
        return ""
    return frontmatter.get("description") or ""


def _write_corpus_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _nav_json(node: NavNode) -> dict[str, object]:
    raw: dict[str, object] = {
        "id": node.id,
        "title": node.title,
        "kind": node.kind.value,
        "page_id": node.page_id,
    }
    result = {key: value for key, value in raw.items() if value is not None}
    if node.children:
        result["children"] = [_nav_json(child) for child in node.children]
    return result


def _page_json(page: Page) -> dict[str, object]:
    raw: dict[str, object] = {
        "id": page.id,
        "path": page.path,
        "title": page.title,
        "kind": page.kind.value,
        "description": page.description or None,
        "source_repo": page.source_repo,
        "source_path": page.source_path,
        "source_commit": page.source_commit,
        "last_modified": page.last_modified,
        "corpus_path": page.corpus_path,
        "url": page.url,
    }
    return {key: value for key, value in raw.items() if value is not None}
