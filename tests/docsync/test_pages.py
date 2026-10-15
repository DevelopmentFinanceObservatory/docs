"""Tests for dfo_docs.docsync.pages: the docsync allowlist and the pages it enumerates.

Every repository is a real `git init` repo under `tmp_path`: a stand-in dfo-docs checkout
carrying sources.yaml, hub.yaml and content/hub/, and the source repositories its
sources.yaml points at by local path, so fetching runs real git without the network.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

from dfo_docs.docsync.pages import (
    DocsyncConfig,
    DocsyncConfigError,
    SyncPage,
    load_config,
    load_sync_pages,
)
from dfo_docs.fetch import fetch_all
from dfo_docs.manifest import build_pages
from dfo_docs.models import FETCHED_KINDS
from dfo_docs.registry import enabled_sources, load_hub, load_sources

DFO_DOCS_ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip("\n"))


def _repo(root: Path, files: dict[str, str]) -> Path:
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _write(root, files)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _site(tmp_path: Path) -> Path:
    """A dfo-docs checkout mounting a docs source, a skill source, a source docsync
    leaves out, an external row, and a disabled row."""
    guide = _repo(
        tmp_path / "guide",
        {
            "mkdocs.yml": """
                path: guide
                title: Guide
                nav:
                  - index.md
                  - Start: start.md
                  - Deep:
                      - deep/index.md
                      - Detail: deep/detail.md
            """,
            "docs/index.md": "# Guide home\n",
            "docs/start.md": "---\ndescription: Begin.\n---\n\n# Start\n",
            "docs/deep/index.md": "# Deep\n",
            "docs/deep/detail.md": "# Detail\n",
        },
    )
    skills = _repo(
        tmp_path / "skills",
        {
            "skills/alpha/SKILL.md": "---\nname: alpha\ndescription: >-\n  Alpha. More.\n---\n\nBody.\n",
            "skills/alpha/references/flow-types.md": "# Flow types\n",
            "skills/beta/SKILL.md": "---\nname: beta\ndescription: Beta.\n---\n\n# Beta\n",
            "skills/_template/SKILL.md": "---\nname: _template\n---\n",
        },
    )
    other = _repo(
        tmp_path / "other",
        {
            "mkdocs.yml": "path: other\ntitle: Other\nnav:\n  - index.md\n",
            "docs/index.md": "# Other\n",
        },
    )
    return _repo(
        tmp_path / "site",
        {
            "sources.yaml": f"""
                sources:
                  - name: guide
                    repo: {guide}
                    path: guide
                  - name: dfo-skills
                    repo: {skills}
                    kind: skill
                    docs_dir: skills
                    path: skills
                    title: All skills
                  - name: other
                    repo: {other}
                  - name: pkg
                    repo: org/pkg
                    kind: external
                    url: https://example.com/pkg/
                    path: tools/pkg
                    title: Pkg
                  - name: parked
                    repo: org/parked
                    enabled: false
            """,
            "hub.yaml": """
                title: Hub
                nav:
                  - title: Home
                    page: index.md
                  - title: Build
                    children:
                      - title: Share
                        page: build/share.md
                      - mount: guide
                  - title: Skills
                    children:
                      - page: skills/what.md
                      - mount: dfo-skills
                  - title: Packages
                    children:
                      - mount: other
                      - external: pkg
            """,
            "content/hub/index.md": "# Home page\n",
            "content/hub/build/share.md": "# Share\n",
            "content/hub/skills/what.md": "# What a skill is\n",
            "content/hub/draft.md": "# Not in hub.yaml\n",
        },
    )


def _config(*sources: str) -> DocsyncConfig:
    return DocsyncConfig(
        sources=sources, drive_folder_id="folder", pr_author="app/dfo-docsync"
    )


def _pages(site: Path, tmp_path: Path, *sources: str) -> tuple[SyncPage, ...]:
    return load_sync_pages(_config(*sources), repo_root=site, workdir=tmp_path / "work")


# --- load_sync_pages --------------------------------------------------------------


def test_pages_follow_the_nav_with_their_sections_and_titles(tmp_path):
    site = _site(tmp_path)
    pages = _pages(site, tmp_path, "hub", "guide", "dfo-skills")

    assert [(p.page_id, p.section_path, p.title) for p in pages] == [
        ("hub", (), "Home"),
        ("hub/build/share", ("Build",), "Share"),
        ("guide", ("Build", "Guide"), "Guide home"),
        ("guide/start", ("Build", "Guide"), "Start"),
        ("guide/deep", ("Build", "Guide", "Deep"), "Deep"),
        ("guide/deep/detail", ("Build", "Guide", "Deep"), "Detail"),
        ("hub/skills/what", ("Skills",), "What a skill is"),
        ("dfo-skills/alpha", ("Skills", "All skills", "alpha"), "alpha"),
        (
            "dfo-skills/alpha/references/flow-types",
            ("Skills", "All skills", "alpha"),
            "Flow types",
        ),
        ("dfo-skills/beta", ("Skills", "All skills"), "beta"),
    ]


def test_page_ids_match_the_full_build_manifest(tmp_path):
    site = _site(tmp_path)
    pages = _pages(site, tmp_path, "hub", "guide", "dfo-skills")

    sources = load_sources(site / "sources.yaml")
    fetched = fetch_all(
        (s for s in enabled_sources(sources).values() if s.kind in FETCHED_KINDS),
        workdir=tmp_path / "full",
    )
    _, manifest_pages = build_pages(
        sources,
        load_hub(site / "hub.yaml"),
        fetched,
        repo_root=site,
        hub_content_root=site / "content/hub",
        corpus_root=tmp_path / "corpus",
    )
    manifest = {page.id: page for page in manifest_pages}

    for page in pages:
        assert page.page_id in manifest
        assert page.title == manifest[page.page_id].title
        assert page.path == manifest[page.page_id].source_path


def test_each_page_carries_raw_text_at_its_commit_in_a_live_clone(tmp_path):
    site = _site(tmp_path)
    pages = {p.page_id: p for p in _pages(site, tmp_path, "hub", "guide", "dfo-skills")}

    hub = pages["hub/build/share"]
    assert hub.clone_root == site
    assert hub.repo == "DevelopmentFinanceObservatory/docs"
    assert hub.ref == "main"
    assert hub.commit == _git(site, "rev-parse", "HEAD").strip()
    assert hub.path == "content/hub/build/share.md"
    assert hub.text == "# Share\n"

    skill = pages["dfo-skills/alpha"]
    assert skill.clone_root == tmp_path / "work" / "dfo-skills"
    assert skill.repo == str(tmp_path / "skills")
    assert skill.commit == _git(tmp_path / "skills", "rev-parse", "HEAD").strip()
    assert skill.path == "skills/alpha/SKILL.md"
    # SKILL.md itself, without the header the build adds to the published page.
    assert skill.text == (tmp_path / "skills/skills/alpha/SKILL.md").read_text()

    for page in pages.values():
        shown = _git(page.clone_root, "show", f"{page.commit}:{page.path}")
        assert shown == page.text


def test_hub_left_out_of_the_allowlist_publishes_no_hub_page(tmp_path):
    site = _site(tmp_path)
    pages = _pages(site, tmp_path, "guide")

    assert [p.page_id for p in pages] == [
        "guide",
        "guide/start",
        "guide/deep",
        "guide/deep/detail",
    ]
    assert not (tmp_path / "work" / "dfo-skills").exists()


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("missing", "is not a source"),
        ("parked", "is disabled"),
        ("pkg", "publishes no pages"),
    ],
)
def test_an_allowlisted_name_docsync_cannot_publish_is_refused(tmp_path, name, message):
    site = _site(tmp_path)
    with pytest.raises(DocsyncConfigError, match=message):
        _pages(site, tmp_path, "hub", name)


def test_an_allowlisted_source_hub_yaml_does_not_mount_is_refused(tmp_path):
    site = _site(tmp_path)
    (site / "hub.yaml").write_text(
        "title: Hub\nnav:\n  - title: Home\n    page: index.md\n"
    )
    _git(site, "commit", "-qam", "unmount")
    with pytest.raises(DocsyncConfigError, match="not mounted"):
        _pages(site, tmp_path, "guide")


def test_uncommitted_hub_content_is_refused(tmp_path):
    site = _site(tmp_path)
    (site / "content/hub/build/share.md").write_text("# Share, edited\n")
    with pytest.raises(RuntimeError, match="uncommitted changes"):
        _pages(site, tmp_path, "hub")


# --- load_config ------------------------------------------------------------------


def test_load_config_reads_the_repository_docsync_yaml():
    config = load_config(DFO_DOCS_ROOT / "docsync.yaml")
    assert config.sources == ("hub", "dfo-apis", "dfo-ai", "dfo-skills")
    assert config.drive_folder_id == "1DL_BWEeo92oksJEr28xlXFD46xQxFQG1"
    assert config.pr_author == "app/dfo-docsync"


def test_the_repository_allowlist_names_publishable_sources():
    sources = load_sources(DFO_DOCS_ROOT / "sources.yaml")
    for name in load_config(DFO_DOCS_ROOT / "docsync.yaml").sources:
        if name != "hub":
            assert sources[name].enabled
            assert sources[name].kind in FETCHED_KINDS


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("drive_folder_id: x\npr_author: a\n", "sources must be"),
        ("sources: []\ndrive_folder_id: x\npr_author: a\n", "sources must be"),
        ("sources: [hub, hub]\ndrive_folder_id: x\npr_author: a\n", "more than once"),
        ("sources: [hub]\npr_author: a\n", "drive_folder_id is not set"),
        ("sources: [hub]\ndrive_folder_id: x\n", "pr_author is not set"),
        ("sources: [hub]\ndrive_folder_id: x\npr_author: ''\n", "pr_author is not set"),
        (
            "sources: [hub]\ndrive_folder_id: x\npr_author: a\nsheet_id: s\n",
            "unknown keys",
        ),
        ("- hub\n", "mapping"),
    ],
)
def test_load_config_refuses_a_malformed_file(tmp_path, text, message):
    path = tmp_path / "docsync.yaml"
    path.write_text(text)
    with pytest.raises(DocsyncConfigError, match=message):
        load_config(path)


def test_load_config_refuses_a_missing_file(tmp_path):
    with pytest.raises(DocsyncConfigError, match="file not found"):
        load_config(tmp_path / "docsync.yaml")
