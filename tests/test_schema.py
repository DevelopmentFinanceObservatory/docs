"""Validate a real generator run against the published schemas under
src/dfo_docs/schema/.

For the manifest: builds an envelope through `manifest.build_pages` and
`manifest.write_manifest` from fixtures exercising every node kind (`group` with and
without a landing page, `page`, `external`) and every page kind (`page`, `skill`,
`external`), then validates the written JSON against
the published schema. For the roadmap: runs `dfo_docs.cli.main`, the real emission
path, against this repository's own committed `roadmap/` directory, and validates
`roadmap.json` and every `roadmap/<track>.json` it writes against their own published
schemas. A schema validated only against a handwritten example proves nothing about
what the generator actually emits; this file is what keeps each pair honest.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from importlib import resources
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from dfo_docs.cli import main as cli_main
from dfo_docs.fetch import fetch_source
from dfo_docs.manifest import build_pages, write_manifest
from dfo_docs.models import (
    SCHEMA_VERSION,
    HubNode,
    Manifest,
    Source,
    SourceKind,
)

COMMIT_DATE = "2026-08-14T16:43:28+00:00"
REPO_ROOT = Path(__file__).resolve().parent.parent


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


def _commit_all(repo: Path) -> None:
    _git(repo, "add", "-A")
    env = {
        "GIT_AUTHOR_DATE": COMMIT_DATE,
        "GIT_COMMITTER_DATE": COMMIT_DATE,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    _git(repo, "commit", "-q", "-m", "init", env=env)
    _git(repo, "branch", "-M", "main")


def _sample_repo(tmp_path: Path) -> Path:
    """A small docs repo with a root index, a plain page, and a nested group with its
    own landing page, so the built nav exercises a `group` node with a landing page
    (the mount itself), a `group` node without one (the nested "Guides" heading), and
    plain `page` leaves."""
    repo = _make_repo(tmp_path, "sample")
    (repo / "mkdocs.yml").write_text(
        "site_name: tools/sample\n"
        "title: Sample Package\n"
        "nav:\n"
        "  - index.md\n"
        "  - Getting started: getting-started.md\n"
        "  - Guides:\n"
        "      - Advanced: guides/advanced.md\n"
    )
    docs = repo / "docs"
    (docs / "guides").mkdir(parents=True)
    (docs / "index.md").write_text("# Sample\n")
    (docs / "getting-started.md").write_text(
        "---\ndescription: Install and go.\n---\n\n# Getting started\n"
    )
    (docs / "guides" / "advanced.md").write_text("# Advanced\n")
    _commit_all(repo)
    return repo


def _skills_repo(tmp_path: Path) -> Path:
    """A skills repo with one skill and one reference file under `skills/`, so the skill
    ships and the built manifest carries a `skill` page with a `bundle_path`."""
    repo = _make_repo(tmp_path, "skills-repo")
    skill_dir = repo / "skills" / "alpha"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: Covers alpha.\n---\n\n## Overview\n"
    )
    (skill_dir / "references" / "flow-types.md").write_text("# Flow types\n")
    (repo / "skills" / "categories.yaml").write_text("sources:\n  - alpha\n")
    _commit_all(repo)
    return repo


def _build_real_envelope(tmp_path: Path) -> Manifest:
    """Build a `Manifest` through `build_pages`, covering every nav node kind: a
    `group` with a landing page (the "sample" mount), a `group` without one ("Guides"),
    `page` leaves, and an `external` node."""
    repo = _sample_repo(tmp_path)
    sample = Source(
        name="sample", repo=str(repo), ref="main", docs_dir="docs", path="tools/sample"
    )
    pkg = Source(
        name="pkg",
        repo="org/pkg",
        kind=SourceKind.EXTERNAL,
        ref=None,
        docs_dir=None,
        path="tools/pkg",
        url="https://example.com/pkg/",
        title="Package X",
    )
    skills = Source(
        name="skills",
        repo=str(_skills_repo(tmp_path)),
        kind=SourceKind.SKILL,
        docs_dir="skills",
        path="skills",
        title="All skills",
    )
    fetched = [
        fetch_source(sample, workdir=tmp_path / "work"),
        fetch_source(skills, workdir=tmp_path / "work"),
    ]

    hub_content_root = tmp_path / "hub_content"
    hub_content_root.mkdir()
    (hub_content_root / "index.md").write_text(
        "---\ndescription: The hub landing page.\n---\n\n# DFO docs\n"
    )

    hub = HubNode(
        title="Hub",
        children=(
            HubNode(title="Home", page="index.md"),
            HubNode(
                title="Tools",
                children=(
                    HubNode(mount="sample"),
                    HubNode(external="pkg"),
                    HubNode(mount="skills"),
                ),
            ),
        ),
    )

    nav, pages = build_pages(
        {"sample": sample, "pkg": pkg, "skills": skills},
        hub,
        fetched,
        repo_root=tmp_path,
        hub_content_root=hub_content_root,
        corpus_root=tmp_path / "corpus",
    )

    return Manifest(
        schema_version=SCHEMA_VERSION,
        generated_at="2026-09-12T10:04:11Z",
        generator_commit="efadc40e1b2c3d4e5f60718293a4b5c6d7e8f901",
        nav=tuple(nav),
        pages=tuple(pages),
    )


def _schema() -> dict:
    traversable = resources.files("dfo_docs") / "schema" / "manifest.schema.json"
    return json.loads(traversable.read_text())


def test_schema_is_itself_a_valid_draft_2020_12_schema():
    Draft202012Validator.check_schema(_schema())


def test_schema_declares_draft_2020_12():
    assert _schema()["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_real_generator_output_validates_against_schema(tmp_path):
    manifest = _build_real_envelope(tmp_path)
    out = tmp_path / "manifest.json"
    write_manifest(manifest, out)
    data = json.loads(out.read_text())

    validator = Draft202012Validator(_schema())
    errors = list(validator.iter_errors(data))
    assert not errors, best_match(errors)

    # Sanity: the fixture actually exercises every kind the schema constrains,
    # so a validator that accepted anything would not pass this test vacuously.
    nav_kinds = _collect_nav_kinds(data["nav"])
    assert nav_kinds == {"group", "page", "external"}
    page_kinds = {page["kind"] for page in data["pages"]}
    assert page_kinds == {"page", "external", "skill"}
    assert any("bundle_path" in page for page in data["pages"])


def test_manifest_missing_required_field_fails_validation():
    invalid = {
        "generated_at": "2026-09-12T10:04:11Z",
        "nav": [],
        "pages": [],
    }
    validator = Draft202012Validator(_schema())
    assert not validator.is_valid(invalid)


def test_nav_node_rejects_page_id_on_a_page_kind_node():
    envelope = {
        "schema_version": 1,
        "generated_at": "2026-09-12T10:04:11Z",
        "nav": [
            {
                "id": "sample/getting-started",
                "title": "Getting started",
                "kind": "page",
                "page_id": "sample/getting-started",
                "path": "tools/sample/getting-started",
            }
        ],
        "pages": [],
    }
    validator = Draft202012Validator(_schema())
    assert not validator.is_valid(envelope)


def _collect_nav_kinds(nodes: list[dict]) -> set[str]:
    kinds = set()
    for node in nodes:
        kinds.add(node["kind"])
        kinds |= _collect_nav_kinds(node.get("children", []))
    return kinds


# --- the roadmap index and track schemas ------------------------------------------


def _roadmap_schema() -> dict:
    traversable = resources.files("dfo_docs") / "schema" / "roadmap.schema.json"
    return json.loads(traversable.read_text())


def _roadmap_track_schema() -> dict:
    traversable = resources.files("dfo_docs") / "schema" / "roadmap-track.schema.json"
    return json.loads(traversable.read_text())


def test_roadmap_schema_is_itself_a_valid_draft_2020_12_schema():
    Draft202012Validator.check_schema(_roadmap_schema())


def test_roadmap_track_schema_is_itself_a_valid_draft_2020_12_schema():
    Draft202012Validator.check_schema(_roadmap_track_schema())


def test_real_roadmap_output_validates_against_its_own_schemas(tmp_path: Path):
    """Runs the real roadmap emission path (`dfo_docs.cli.main`) against a copy of
    this repository's own committed `roadmap/` directory: real, substantive data for
    the data track, and the empty-by-design shape for platform and ai-tools.

    `--repo-root` here carries no `sources.yaml`, so the corpus half fails
    immediately afterwards with exit 2, before touching the network; that failure is
    irrelevant to this test, since the roadmap has already published unconditionally
    by that point (see `dfo_docs.cli._run`).
    """
    repo_root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "roadmap", repo_root / "roadmap")
    out_dir = tmp_path / "out"

    exit_code = cli_main(["--out", str(out_dir), "--repo-root", str(repo_root)])

    assert exit_code == 2
    index = json.loads((out_dir / "roadmap.json").read_text())

    index_errors = list(Draft202012Validator(_roadmap_schema()).iter_errors(index))
    assert not index_errors, best_match(index_errors)
    assert {ref["id"] for ref in index["tracks"]} == {"data", "platform", "ai-tools"}

    track_validator = Draft202012Validator(_roadmap_track_schema())
    for ref in index["tracks"]:
        track = json.loads((out_dir / ref["file"]).read_text())
        track_errors = list(track_validator.iter_errors(track))
        assert not track_errors, best_match(track_errors)
        assert track["track"] == ref["id"]

    data_track = json.loads((out_dir / "roadmap" / "data.json").read_text())
    assert data_track["entries"], "the data track's real content should not be empty"


def test_roadmap_missing_required_field_fails_validation():
    invalid = {"generated_at": "2026-09-12T10:04:11Z", "tracks": []}
    validator = Draft202012Validator(_roadmap_schema())
    assert not validator.is_valid(invalid)


def test_roadmap_track_released_entry_without_released_on_fails_validation():
    invalid = {
        "schema_version": 1,
        "generated_at": "2026-09-12T10:04:11Z",
        "track": "data",
        "categories": [],
        "entries": [
            {
                "id": "foo",
                "title": "Foo",
                "description": "Foo does a thing.",
                "status": "released",
            }
        ],
    }
    validator = Draft202012Validator(_roadmap_track_schema())
    assert not validator.is_valid(invalid)
