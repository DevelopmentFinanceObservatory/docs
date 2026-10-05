"""Tests for dfo_docs.manifest: assembling the nav tree, Page records, and the corpus.

Fixture repositories are real `git init` repos under `tmp_path`, fetched with
`fetch_source` exactly as `test_fetch.py` does, so `last_modified` and `source_commit`
are exercised for real rather than stubbed.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from dfo_docs.fetch import fetch_source
from dfo_docs.manifest import build_pages, write_manifest
from dfo_docs.models import (
    FETCHED_KINDS,
    Fetched,
    HubNode,
    Manifest,
    NavKind,
    NavNode,
    Page,
    PageKind,
    Source,
    SourceKind,
)
from dfo_docs.registry import load_hub, load_sources

COMMIT_DATE = "2026-08-14T16:43:28+00:00"
DFO_DOCS_ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    full_env = {**os.environ, **env} if env else None
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=full_env,
    )


def _make_repo(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    return repo


def _commit_all(repo: Path, message: str, *, date: str = COMMIT_DATE) -> str:
    _git(repo, "add", "-A")
    env = {
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_DATE": date,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    _git(repo, "commit", "-q", "-m", message, env=env)
    _git(repo, "branch", "-M", "main")
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _sample_repo(tmp_path: Path) -> Path:
    """A small `sample` docs repo: root index, a plain page with frontmatter, an
    `index.md` nested one level down, and a page nested under a grouping heading -- the
    shapes the path and nav derivations need to cover."""
    repo = _make_repo(tmp_path, "sample")
    (repo / "mkdocs.yml").write_text(
        "site_name: tools/sample\n"
        "title: Sample Package\n"
        "nav:\n"
        "  - index.md\n"
        "  - Getting started: getting-started.md\n"
        "  - Guides:\n"
        "      - guides/index.md\n"
        "      - Advanced: guides/advanced.md\n"
    )
    docs = repo / "docs"
    (docs / "guides").mkdir(parents=True)
    (docs / "index.md").write_text("# Sample\n")
    (docs / "getting-started.md").write_text(
        "---\n"
        "description: Install and go.\n"
        "---\n\n"
        "# Getting started\n\n"
        '!!! note "Heads up"\n'
        "    Read this first.\n"
    )
    (docs / "guides" / "index.md").write_text("# Guides\n")
    (docs / "guides" / "advanced.md").write_text("# Advanced\n\n```py\nprint(1)\n```\n")
    _commit_all(repo, "init")
    return repo


def _sample_source(repo: Path, **overrides) -> Source:
    fields = {"name": "sample", "repo": str(repo), "ref": "main", "docs_dir": "docs"}
    fields.update(overrides)
    return Source(**fields)


def _fetch(source: Source, tmp_path: Path) -> Fetched:
    return fetch_source(source, workdir=tmp_path / "work")


def _hub_with_sample_only() -> HubNode:
    return HubNode(
        title="Hub",
        children=(
            HubNode(title="Home", page="index.md"),
            HubNode(title="Which tool", page="which-tool.md"),
            HubNode(title="Tools", children=(HubNode(mount="sample"),)),
        ),
    )


def _hub_with_sample_and_pkg() -> HubNode:
    return HubNode(
        title="Hub",
        children=(
            HubNode(title="Home", page="index.md"),
            HubNode(title="Which tool", page="which-tool.md"),
            HubNode(
                title="Tools",
                children=(
                    HubNode(mount="sample"),
                    HubNode(external="pkg"),
                ),
            ),
        ),
    )


def _hub_content(tmp_path: Path) -> Path:
    root = tmp_path / "hub_content"
    root.mkdir()
    (root / "index.md").write_text(
        "---\ndescription: The hub landing page.\n---\n\n# DFO docs\n"
    )
    (root / "which-tool.md").write_text("# Which tool\n")
    return root


def _pkg_source(**overrides) -> Source:
    fields = {
        "name": "pkg",
        "repo": "org/pkg",
        "kind": SourceKind.EXTERNAL,
        "ref": None,
        "docs_dir": None,
        "path": "tools/pkg",
        "url": "https://example.com/pkg/",
    }
    fields.update(overrides)
    return Source(**fields)


def _build(
    tmp_path: Path, *, sources: dict[str, Source], hub: HubNode, fetched: list[Fetched]
):
    corpus_root = tmp_path / "corpus"
    nav, pages = build_pages(
        sources,
        hub,
        fetched,
        repo_root=tmp_path,
        hub_content_root=_hub_content(tmp_path),
        corpus_root=corpus_root,
    )
    return nav, pages, corpus_root


def _by_id(pages: list[Page], page_id: str) -> Page:
    return next(page for page in pages if page.id == page_id)


def _find_node(nodes: Sequence[NavNode], *, title: str) -> NavNode | None:
    """Depth-first search of a nav tree for the first node with a matching title."""
    for node in nodes:
        if node.title == title:
            return node
        found = _find_node(node.children, title=title)
        if found is not None:
            return found
    return None


def test_path_construction_including_index_collapse(tmp_path):
    repo = _sample_repo(tmp_path)
    source = _sample_source(repo, path="tools/sample")
    fetched = _fetch(source, tmp_path)
    hub = _hub_with_sample_only()

    _, pages, _ = _build(
        tmp_path, sources={"sample": source}, hub=hub, fetched=[fetched]
    )

    assert (
        _by_id(pages, "sample").path == "tools/sample"
    )  # root index.md collapses fully
    assert (
        _by_id(pages, "sample/getting-started").path == "tools/sample/getting-started"
    )
    assert (
        _by_id(pages, "sample/guides").path == "tools/sample/guides"
    )  # nested index.md
    assert (
        _by_id(pages, "sample/guides/advanced").path == "tools/sample/guides/advanced"
    )


def _breadcrumb(nav, page_id):
    """A page's ancestor group titles, derived by walking `nav` the way a consumer does.

    `Page` carries no `section`, so this is the whole of what a breadcrumb costs a
    consumer: one walk of the tree it already walks to render a sidebar.
    """

    def walk(nodes, ancestors):
        for node in nodes:
            if node.kind is NavKind.GROUP:
                if node.page_id == page_id:
                    return ancestors
                found = walk(node.children, (*ancestors, node.title))
                if found is not None:
                    return found
            elif node.id == page_id:
                return ancestors
        return None

    return walk(nav, ())


def test_breadcrumb_for_page_nested_under_grouping_heading(tmp_path):
    repo = _sample_repo(tmp_path)
    source = _sample_source(repo, path="tools/sample")
    fetched = _fetch(source, tmp_path)
    hub = _hub_with_sample_only()

    nav, pages, _ = _build(
        tmp_path, sources={"sample": source}, hub=hub, fetched=[fetched]
    )

    assert _breadcrumb(nav, "sample/guides/advanced") == (
        "Tools",
        "Sample Package",
        "Guides",
    )

    # A top-level page in the same source's nav carries no fourth segment.
    assert _breadcrumb(nav, "sample/getting-started") == ("Tools", "Sample Package")
    assert _by_id(pages, "sample/getting-started")


def test_landing_page_breadcrumb_excludes_its_own_group_title(tmp_path):
    """A group's own landing page (its leading `index.md`) sits at the group rather than
    inside it, so its breadcrumb stops one level short of every other descendant's."""
    repo = _sample_repo(tmp_path)
    source = _sample_source(repo, path="tools/sample")
    fetched = _fetch(source, tmp_path)
    hub = _hub_with_sample_only()

    nav, _pages, _ = _build(
        tmp_path, sources={"sample": source}, hub=hub, fetched=[fetched]
    )

    # "sample" is the source mount's own landing page; "Sample Package" (its own
    # group's title) must not appear in its own breadcrumb.
    assert _breadcrumb(nav, "sample") == ("Tools",)

    # "sample/guides" is the nested "Guides" group's own landing page; "Guides" must
    # not appear in its own breadcrumb, though "Sample Package" (an ancestor, not this
    # page's own group) still does.
    assert _breadcrumb(nav, "sample/guides") == ("Tools", "Sample Package")


def test_description_from_frontmatter_and_empty_when_absent(tmp_path):
    repo = _sample_repo(tmp_path)
    source = _sample_source(repo, path="tools/sample")
    fetched = _fetch(source, tmp_path)
    hub = _hub_with_sample_only()

    _, pages, _ = _build(
        tmp_path, sources={"sample": source}, hub=hub, fetched=[fetched]
    )

    assert _by_id(pages, "sample/getting-started").description == "Install and go."
    assert _by_id(pages, "sample").description == ""  # index.md carries no frontmatter


def test_external_row_produces_one_entry_with_url(tmp_path):
    repo = _sample_repo(tmp_path)
    source = _sample_source(repo, path="tools/sample")
    fetched = _fetch(source, tmp_path)
    hub = _hub_with_sample_and_pkg()
    pkg = _pkg_source(title="Package X")

    _, pages, _ = _build(
        tmp_path, sources={"sample": source, "pkg": pkg}, hub=hub, fetched=[fetched]
    )

    external = [page for page in pages if page.kind is PageKind.EXTERNAL]
    assert len(external) == 1
    page = external[0]
    assert page.id == "pkg"
    assert page.url == "https://example.com/pkg/"
    assert page.path == "tools/pkg"
    assert page.title == "Package X"
    assert page.corpus_path is None
    assert page.source_path is None


def test_external_row_without_title_falls_back_to_source_name(tmp_path):
    repo = _sample_repo(tmp_path)
    source = _sample_source(repo, path="tools/sample")
    fetched = _fetch(source, tmp_path)
    hub = _hub_with_sample_and_pkg()
    pkg = _pkg_source()  # no title override

    _, pages, _ = _build(
        tmp_path, sources={"sample": source, "pkg": pkg}, hub=hub, fetched=[fetched]
    )

    assert _by_id(pages, "pkg").title == "pkg"


def test_disabled_external_row_produces_no_entry(tmp_path):
    repo = _sample_repo(tmp_path)
    source = _sample_source(repo, path="tools/sample")
    fetched = _fetch(source, tmp_path)
    hub = _hub_with_sample_and_pkg()
    pkg = _pkg_source(enabled=False, reason="not yet public")

    _, pages, _ = _build(
        tmp_path, sources={"sample": source, "pkg": pkg}, hub=hub, fetched=[fetched]
    )

    assert not any(page.id == "pkg" for page in pages)


def test_hub_pages_land_at_corpus_root(tmp_path):
    repo = _sample_repo(tmp_path)
    source = _sample_source(repo, path="tools/sample")
    fetched = _fetch(source, tmp_path)
    hub = _hub_with_sample_only()

    _, pages, corpus_root = _build(
        tmp_path, sources={"sample": source}, hub=hub, fetched=[fetched]
    )

    home = _by_id(pages, "hub")
    assert home.path == ""  # root index.md, no "tools/" or "hub/" prefix
    assert home.title == "Home"
    assert home.description == "The hub landing page."
    assert home.corpus_path == "corpus/hub/index.md"
    assert home.source_repo == "ONEcampaign/dfo-docs"
    assert home.source_commit is None
    assert home.last_modified is None
    assert (corpus_root / "hub" / "index.md").is_file()

    which_tool = _by_id(pages, "hub/which-tool")
    assert which_tool.path == "which-tool"
    assert which_tool.corpus_path == "corpus/hub/which-tool.md"


def test_fetched_page_provenance_and_corpus_write(tmp_path):
    repo = _sample_repo(tmp_path)
    source = _sample_source(repo, path="tools/sample")
    fetched = _fetch(source, tmp_path)
    hub = _hub_with_sample_only()

    _, pages, corpus_root = _build(
        tmp_path, sources={"sample": source}, hub=hub, fetched=[fetched]
    )

    page = _by_id(pages, "sample/getting-started")
    assert page.source_repo == str(repo)
    assert page.source_path == "docs/getting-started.md"
    assert page.source_commit == fetched.commit
    assert page.last_modified == "2026-08-14T16:43:28Z"
    assert page.corpus_path == "corpus/sample/getting-started.md"

    written = (corpus_root / "sample" / "getting-started.md").read_text()
    assert "> [!NOTE]" in written  # admonition conversion ran
    assert "!!!" not in written

    advanced = (corpus_root / "sample" / "guides" / "advanced.md").read_text()
    assert "```python" in advanced  # fence tag normalisation ran


def _dir_link_repo(tmp_path: Path) -> Path:
    """A repo whose nested `guides/index.md` carries a `../getting-started/`
    directory-form link, with a same-named `guides/getting-started.md` decoy sitting
    right beside it. The off-by-one bug in the directory-link rewrite resolves the
    link to that decoy instead of the docs-root `getting-started.md`, and does so
    silently, since the decoy file exists."""
    repo = _make_repo(tmp_path, "dirlinks")
    (repo / "mkdocs.yml").write_text(
        "site_name: tools/dirlinks\n"
        "title: Dir Links\n"
        "nav:\n"
        "  - index.md\n"
        "  - Getting started: getting-started.md\n"
        "  - Guides:\n"
        "      - guides/index.md\n"
        "      - guides/getting-started.md\n"
    )
    docs = repo / "docs"
    (docs / "guides").mkdir(parents=True)
    (docs / "index.md").write_text("# Home\n")
    (docs / "getting-started.md").write_text("# Getting started\n")
    (docs / "guides" / "index.md").write_text(
        "# Guides\n\nSee [earlier](../getting-started/) for background.\n"
    )
    (docs / "guides" / "getting-started.md").write_text("# Getting started (guides)\n")
    _commit_all(repo, "init")
    return repo


def test_directory_index_link_rewrite_runs_through_the_real_build_pipeline(tmp_path):
    """Regression: `build_pages` (the real pipeline, not a direct `normalise_markdown`
    call) must pass `docs_root` through to the directory-link rewrite. Without it,
    `guides/index.md`'s `../getting-started/` link resolves to the `guides/`-local
    decoy instead of the docs-root page it actually points at."""
    repo = _dir_link_repo(tmp_path)
    source = _sample_source(repo, name="dirlinks", path="tools/dirlinks")
    fetched = _fetch(source, tmp_path)
    hub = HubNode(children=(HubNode(mount="dirlinks"),))

    _, _, corpus_root = _build(
        tmp_path, sources={"dirlinks": source}, hub=hub, fetched=[fetched]
    )

    written = (corpus_root / "dirlinks" / "guides" / "index.md").read_text()
    assert "[earlier](../getting-started.md)" in written
    assert "[earlier](getting-started.md)" not in written


def test_nested_sidecar_shape_source_path_carries_both_docs_segments(tmp_path):
    """Seven of the eight live sources use the nested shape (`docs/mkdocs.yml` beside
    `docs/docs/*.md`), where the on-disk path is two `docs` segments deep even though
    `docs_dir` is just `docs`. `source_path` must reflect the real on-disk location."""
    repo = _make_repo(tmp_path, "nested")
    (repo / "docs").mkdir()
    (repo / "docs" / "mkdocs.yml").write_text(
        "site_name: tools/nested\ntitle: Nested Package\nnav:\n  - Home: index.md\n"
    )
    (repo / "docs" / "docs").mkdir()
    (repo / "docs" / "docs" / "index.md").write_text("# Home\n")
    _commit_all(repo, "init")

    source = Source(name="nested", repo=str(repo), ref="main", docs_dir="docs")
    fetched = _fetch(source, tmp_path)
    hub = HubNode(children=(HubNode(mount="nested"),))

    _, pages, corpus_root = _build(
        tmp_path, sources={"nested": source}, hub=hub, fetched=[fetched]
    )

    page = _by_id(pages, "nested")
    assert page.source_path == "docs/docs/index.md"
    assert page.last_modified == "2026-08-14T16:43:28Z"
    assert (corpus_root / "nested" / "index.md").is_file()


def test_mount_group_folds_leading_index_into_page_id_and_path(tmp_path):
    """A source's leading `index.md` becomes its mount group's own `page_id` and
    `path` rather than a child leaf, so the group is never followed by a same-titled
    child (the "IMF reader > IMF reader" bug)."""
    repo = _sample_repo(tmp_path)
    source = _sample_source(repo, path="tools/sample")
    fetched = _fetch(source, tmp_path)
    hub = _hub_with_sample_only()

    nav, _, _ = _build(tmp_path, sources={"sample": source}, hub=hub, fetched=[fetched])

    tools = _find_node(nav, title="Tools")
    sample_group = _find_node(tools.children, title="Sample Package")
    assert sample_group.kind is NavKind.GROUP
    assert sample_group.page_id == "sample"

    child_titles = [child.title for child in sample_group.children]
    assert "Sample Package" not in child_titles
    assert child_titles == ["Getting started", "Guides"]

    guides_group = _find_node(sample_group.children, title="Guides")
    assert guides_group.kind is NavKind.GROUP
    assert guides_group.page_id == "sample/guides"
    assert [child.title for child in guides_group.children] == ["Advanced"]


def test_nav_node_ids_join_to_pages_and_groups_are_opaque(tmp_path):
    repo = _sample_repo(tmp_path)
    source = _sample_source(repo, path="tools/sample")
    fetched = _fetch(source, tmp_path)
    hub = _hub_with_sample_and_pkg()
    pkg = _pkg_source()

    nav, pages, _ = _build(
        tmp_path, sources={"sample": source, "pkg": pkg}, hub=hub, fetched=[fetched]
    )

    tools = _find_node(nav, title="Tools")
    sample_group = _find_node(tools.children, title="Sample Package")
    assert sample_group.id == "group:tools/sample"

    guides_group = _find_node(sample_group.children, title="Guides")
    assert guides_group.id == "group:tools/sample/guides"

    getting_started = _find_node(sample_group.children, title="Getting started")
    assert getting_started.kind is NavKind.PAGE
    assert getting_started.id == "sample/getting-started"
    assert getting_started.id == _by_id(pages, "sample/getting-started").id

    pkg_node = _find_node(tools.children, title="pkg")
    assert pkg_node.kind is NavKind.EXTERNAL
    assert pkg_node.id == "pkg"
    assert pkg_node.id == _by_id(pages, "pkg").id


def test_write_manifest_omits_generator_commit_and_description(tmp_path):
    manifest = Manifest(
        schema_version=1,
        generated_at="2026-09-12T10:04:11Z",
        generator_commit=None,
        nav=(
            NavNode(
                id="sample/getting-started",
                title="Getting started",
                kind=NavKind.PAGE,
            ),
            NavNode(id="pkg", title="pkg", kind=NavKind.EXTERNAL),
        ),
        pages=(
            Page(
                id="sample/getting-started",
                path="tools/sample/getting-started",
                title="Getting started",
                kind=PageKind.PAGE,
                description="Install and go.",
                source_repo="org/sample",
                source_path="docs/getting-started.md",
                source_commit="abc123",
                last_modified="2026-08-14T16:43:28Z",
                corpus_path="corpus/sample/getting-started.md",
            ),
            Page(
                id="pkg",
                path="tools/pkg",
                title="pkg",
                kind=PageKind.EXTERNAL,
                description="",
                source_repo="org/pkg",
                source_path=None,
                source_commit=None,
                last_modified=None,
                corpus_path=None,
                url="https://example.com/pkg/",
            ),
        ),
    )

    out = tmp_path / "manifest.json"
    write_manifest(manifest, out)
    data = json.loads(out.read_text())

    assert data["schema_version"] == 1
    assert data["generated_at"] == "2026-09-12T10:04:11Z"
    assert "generator_commit" not in data

    assert data["nav"][0]["kind"] == "page"
    assert "children" not in data["nav"][0]

    pages = data["pages"]
    assert pages[0]["kind"] == "page"
    assert "url" not in pages[0]

    assert pages[1]["kind"] == "external"
    assert pages[1]["url"] == "https://example.com/pkg/"
    assert "description" not in pages[1]  # "" is omitted like None
    for absent in ("source_path", "source_commit", "last_modified", "corpus_path"):
        assert absent not in pages[1]


def _write_stand_in_docs(repo: Path, source: Source) -> None:
    """An index page and a sidecar for `source`. Each of the source's real `exclude`
    patterns applies, and a pattern matching no nav entry is an error, so the stand-in
    carries one navigable page per pattern."""
    docs_dir = source.docs_dir
    assert docs_dir is not None
    (repo / docs_dir / "index.md").write_text(f"# {source.name}\n")
    nav = ["  - index.md"]
    for pattern in source.exclude:
        excluded = pattern.replace("*", "page")
        target = repo / docs_dir / excluded
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {excluded}\n")
        nav.append(f"  - {excluded}")
    (repo / "mkdocs.yml").write_text(
        f"title: {source.name}\npath: {source.path}\ndocs_dir: {docs_dir}\n"
        "nav:\n" + "\n".join(nav) + "\n"
    )


def test_nav_tree_orders_dcp_tools_after_oda_group_per_hub_yaml(tmp_path):
    """Regression test for the reported defect: `hub.yaml`, not `sources.yaml`'s array
    order, decides where `dcp-tools` sits in the nav. `sources.yaml` lists `dcp-tools`
    before the ODA sources; `hub.yaml` nests it after the ODA group. Built against the
    repository's own `hub.yaml` and `sources.yaml` so the fix is proven closed against
    the real registry, not a fixture standing in for it."""
    sources = load_sources(DFO_DOCS_ROOT / "sources.yaml")
    hub = load_hub(DFO_DOCS_ROOT / "hub.yaml")

    # Every enabled fetched row, since hub.yaml mounts each of them.
    fetched_source_names = [
        name
        for name, source in sources.items()
        if source.enabled and source.kind in FETCHED_KINDS
    ]
    fetched = []
    for name in fetched_source_names:
        repo = _make_repo(tmp_path, f"real-{name}")
        docs_dir = sources[name].docs_dir
        (repo / docs_dir).mkdir(parents=True)
        if sources[name].kind is SourceKind.SKILL:
            (repo / docs_dir / "example").mkdir()
            (repo / docs_dir / "example" / "SKILL.md").write_text(
                "---\nname: example\ndescription: Covers an example.\n---\n"
            )
        else:
            _write_stand_in_docs(repo, sources[name])
        _commit_all(repo, "init")
        _git(repo, "branch", "-M", sources[name].ref)
        local_source = dataclasses.replace(sources[name], repo=str(repo))
        fetched.append(_fetch(local_source, tmp_path))

    nav, _pages = build_pages(
        sources,
        hub,
        fetched,
        repo_root=tmp_path,
        hub_content_root=DFO_DOCS_ROOT / "content" / "hub",
        corpus_root=tmp_path / "corpus",
    )

    tools = _find_node(nav, title="Python packages")
    order = [child.title for child in tools.children]

    assert order == [
        "ODA",
        "dcp-tools",
        "imf-reader",
        "tossd-reader",
        "pydeflate",
        "ResolveKit",
    ]

    oda_index = order.index("ODA")
    dcp_index = order.index("dcp-tools")
    assert dcp_index > oda_index

    # sources.yaml itself lists dcp-tools before the ODA sources; the assertion above
    # only holds because hub.yaml, not that array order, drives the nav.
    sources_yaml_order = [s.name for s in sources.values() if s.enabled]
    assert sources_yaml_order.index("dcp-tools") < sources_yaml_order.index(
        "oda_reader"
    )


# --- kind: skill ------------------------------------------------------------------


def _skills_repo(tmp_path: Path) -> Path:
    """A skills repo: `alpha` with two references, `beta` with none and its own H1,
    and `_template`, which is never published."""
    repo = _make_repo(tmp_path, "skills-repo")
    skills = repo / "skills"
    (skills / "alpha" / "references").mkdir(parents=True)
    (skills / "beta").mkdir()
    (skills / "_template").mkdir()
    (skills / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: >-\n  Covers alpha. Use when asked.\n---\n\n"
        "## References\n\n- [references/flow-types.md](references/flow-types.md)\n"
    )
    (skills / "alpha" / "references" / "flow-types.md").write_text("# Flow types\n")
    (skills / "alpha" / "references" / "price-basis.md").write_text("## No H1\n")
    (skills / "beta" / "SKILL.md").write_text(
        "---\nname: beta\ndescription: Covers beta\n---\n\n# beta\n\n## Overview\n"
    )
    (skills / "_template" / "SKILL.md").write_text("---\nname: _template\n---\n")
    _commit_all(repo, "init")
    return repo


def _skills_source(repo: Path) -> Source:
    return Source(
        name="dfo-skills",
        repo=str(repo),
        kind=SourceKind.SKILL,
        docs_dir="skills",
        path="skills",
        title="All skills",
    )


def _build_skills(tmp_path: Path):
    source = _skills_source(_skills_repo(tmp_path))
    hub = HubNode(
        title="Hub",
        children=(
            HubNode(title="Home", page="index.md"),
            HubNode(
                title="Skills",
                children=(
                    HubNode(title="Which tool", page="which-tool.md"),
                    HubNode(mount="dfo-skills"),
                ),
            ),
        ),
    )
    return _build(
        tmp_path,
        sources={"dfo-skills": source},
        hub=hub,
        fetched=[_fetch(source, tmp_path)],
    )


def test_skill_mount_nav_is_one_group_of_skills(tmp_path):
    nav, _, _ = _build_skills(tmp_path)

    skills_heading = _find_node(nav, title="Skills")
    assert skills_heading is not None
    mount = skills_heading.children[1]
    assert mount == NavNode(
        id="group:skills/dfo-skills",
        title="All skills",
        kind=NavKind.GROUP,
        children=(
            NavNode(
                id="group:skills/dfo-skills/alpha",
                title="alpha",
                kind=NavKind.GROUP,
                page_id="dfo-skills/alpha",
                children=(
                    NavNode(
                        id="dfo-skills/alpha/references/flow-types",
                        title="Flow types",
                        kind=NavKind.PAGE,
                    ),
                    NavNode(
                        id="dfo-skills/alpha/references/price-basis",
                        title="Price basis",
                        kind=NavKind.PAGE,
                    ),
                ),
            ),
            NavNode(id="dfo-skills/beta", title="beta", kind=NavKind.PAGE),
        ),
    )


def test_skill_pages_follow_the_files(tmp_path):
    _, pages, _ = _build_skills(tmp_path)

    skill_pages = [page for page in pages if page.source_repo.endswith("skills-repo")]
    assert [(page.id, page.path, page.kind, page.title) for page in skill_pages] == [
        ("dfo-skills/alpha", "skills/alpha", PageKind.SKILL, "alpha"),
        (
            "dfo-skills/alpha/references/flow-types",
            "skills/alpha/references/flow-types",
            PageKind.PAGE,
            "Flow types",
        ),
        (
            "dfo-skills/alpha/references/price-basis",
            "skills/alpha/references/price-basis",
            PageKind.PAGE,
            "Price basis",
        ),
        ("dfo-skills/beta", "skills/beta", PageKind.SKILL, "beta"),
    ]
    alpha = _by_id(pages, "dfo-skills/alpha")
    assert alpha.description == "Covers alpha. Use when asked."
    assert alpha.source_path == "skills/alpha/SKILL.md"
    assert alpha.corpus_path == "corpus/dfo-skills/alpha/SKILL.md"
    assert alpha.last_modified == "2026-08-14T16:43:28Z"
    reference = _by_id(pages, "dfo-skills/alpha/references/flow-types")
    assert reference.corpus_path == "corpus/dfo-skills/alpha/references/flow-types.md"


def test_skill_corpus_files_carry_the_header_and_keep_links(tmp_path):
    _, _, corpus_root = _build_skills(tmp_path)

    install = (
        "To load this skill in your own agent, see [Use skills in your own agent]"
        "(../../hub/skills/use-in-your-agent.md)."
    )
    alpha = (corpus_root / "dfo-skills" / "alpha" / "SKILL.md").read_text()
    assert alpha == (
        "---\nname: alpha\ndescription: >-\n  Covers alpha. Use when asked.\n---\n\n"
        f"# alpha\n\nCovers alpha.\n\n{install}\n\n"
        "## References\n\n- [references/flow-types.md](references/flow-types.md)\n"
    )
    beta = (corpus_root / "dfo-skills" / "beta" / "SKILL.md").read_text()
    assert beta.count("# beta") == 1
    assert "# beta\n\nCovers beta\n\n" in beta
    assert (
        corpus_root / "dfo-skills" / "alpha" / "references" / "flow-types.md"
    ).is_file()
    assert not (corpus_root / "dfo-skills" / "_template").exists()
