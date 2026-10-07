"""Tests for dfo_docs.cli: the run sequence `scripts/build.py` drives.

Every fixture "source repository" is a real local `git init` repo, fetched with the
real `dfo_docs.fetch` machinery exactly as `test_manifest.py` does — `fetch.py` passes
a filesystem path straight through as a clone URL, so this never touches the network.
`main()` reads `sources.yaml`, `hub.yaml`, and `content/hub/` from
the current directory, so each test builds a small dfo-docs-shaped tree under
`tmp_path` and `monkeypatch.chdir`s into it before calling `main`.
"""

from __future__ import annotations

import json
import os
import subprocess
from importlib import resources
from pathlib import Path

import pytest

from dfo_docs import cli
from dfo_docs.cli import main

COMMIT_DATE = "2026-08-14T16:43:28+00:00"


def _git(repo: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": COMMIT_DATE,
        "GIT_COMMITTER_DATE": COMMIT_DATE,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env
    )


def _make_source_repo(
    path: Path,
    *,
    nav: str,
    files: dict[str, str],
    assets: dict[str, bytes] | None = None,
) -> Path:
    """A real `git init` repo with a root `mkdocs.yml` and the given `docs/` files."""
    path.mkdir(parents=True)
    (path / "mkdocs.yml").write_text(nav)
    docs = path / "docs"
    for name, text in files.items():
        file_path = docs / name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(text)
    for name, data in (assets or {}).items():
        asset_path = docs / name
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        asset_path.write_bytes(data)

    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    _git(path, "branch", "-M", "main")
    return path


def _sound_repo(tmp_path: Path) -> Path:
    """A source repo whose nav and docs directory agree completely."""
    return _make_source_repo(
        tmp_path / "sound",
        nav=(
            "site_name: tools/sound\ntitle: Sound Package\nnav:\n"
            "  - index.md\n  - Getting started: getting-started.md\n"
        ),
        files={
            "index.md": "# Sound\n",
            "getting-started.md": "# Getting started\n",
        },
    )


def _drifted_repo(tmp_path: Path) -> Path:
    """A source repo whose nav points at a file that does not exist."""
    return _make_source_repo(
        tmp_path / "drifted",
        nav=(
            "site_name: tools/drifted\ntitle: Drifted Package\nnav:\n"
            "  - index.md\n  - Missing: missing.md\n"
        ),
        files={"index.md": "# Drifted\n"},
    )


def _directive_repo(tmp_path: Path) -> Path:
    """A source repo whose index page carries a mkdocstrings directive."""
    return _make_source_repo(
        tmp_path / "directive",
        nav="site_name: tools/directive\ntitle: Directive Package\nnav:\n  - index.md\n",
        files={"index.md": "# Directive\n\n::: directive.module\n"},
    )


_PNG_BYTES = b"\x89PNG\r\n\x1a\n"


def _repo_with_image(tmp_path: Path) -> Path:
    """A source repo whose index page references an image beside it."""
    return _make_source_repo(
        tmp_path / "imaged",
        nav="site_name: tools/imaged\ntitle: Imaged Package\nnav:\n  - index.md\n",
        files={"index.md": "# Imaged\n\n![Diagram](diagram.png)\n"},
        assets={"diagram.png": _PNG_BYTES},
    )


def _untidy_repo(tmp_path: Path) -> Path:
    """A source repo with a docs file the nav never reaches."""
    return _make_source_repo(
        tmp_path / "untidy",
        nav="site_name: tools/untidy\ntitle: Untidy Package\nnav:\n  - index.md\n",
        files={"index.md": "# Untidy\n", "orphan.md": "# Orphan\n"},
    )


def _repo_with_missing_transclusion(tmp_path: Path) -> Path:
    """A source repo whose index page transcludes a file that does not exist."""
    return _make_source_repo(
        tmp_path / "broken-transclusion",
        nav=(
            "site_name: tools/broken-transclusion\ntitle: Broken Package\nnav:\n"
            "  - index.md\n"
        ),
        files={"index.md": '--8<-- "MISSING.md"\n'},
    )


def _write_registry(
    tmp_path: Path,
    *,
    sources_yaml: str,
    hub_yaml: str | None = None,
    write_roadmap: bool = True,
) -> None:
    (tmp_path / "sources.yaml").write_text(sources_yaml)
    (tmp_path / "hub.yaml").write_text(
        hub_yaml or "title: Hub\nnav:\n  - title: Home\n    page: index.md\n"
    )
    hub_content = tmp_path / "content" / "hub"
    hub_content.mkdir(parents=True, exist_ok=True)
    (hub_content / "index.md").write_text("# Hub home\n")
    if write_roadmap:
        _write_sound_roadmap(tmp_path)


def _write_sound_roadmap(tmp_path: Path) -> Path:
    """A minimal, guard-clean roadmap/: one track, no categories, no entries.

    `main()` runs the roadmap phase ahead of `load_sources` (see `dfo_docs.cli`), so
    every CLI test needs a roadmap tree that loads and passes its own guards purely
    to reach the corpus phase these tests are actually about.
    """
    roadmap_dir = tmp_path / "roadmap"
    roadmap_dir.mkdir(parents=True, exist_ok=True)
    (roadmap_dir / "index.yaml").write_text("- id: data\n  label: Data\n")
    (roadmap_dir / "data.yaml").write_text("track: data\ncategories: []\nentries: []\n")
    return roadmap_dir


def _sources_yaml(name: str, repo: Path) -> str:
    return (
        "sources:\n"
        f"  - name: {name}\n"
        f"    repo: {repo}\n"
        "    ref: main\n"
        "    docs_dir: docs\n"
        f"    path: tools/{name}\n"
    )


def _hub_yaml_mounting(*names: str) -> str:
    mounts = "\n".join(f"      - mount: {name}" for name in names)
    return (
        "title: Hub\n"
        "nav:\n"
        "  - title: Home\n"
        "    page: index.md\n"
        "  - title: Tools\n"
        "    children:\n" + mounts + "\n"
    )


@pytest.fixture
def chdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- a clean first run -------------------------------------------------------------


def test_first_run_publishes_corpus_and_manifest(chdir: Path):
    repo = _sound_repo(chdir)
    _write_registry(
        chdir,
        sources_yaml=_sources_yaml("sound", repo),
        hub_yaml=_hub_yaml_mounting("sound"),
    )
    out_dir = chdir / "out"

    exit_code = main(["--out", str(out_dir)])

    assert exit_code == 0
    assert (out_dir / "corpus" / "sound" / "index.md").is_file()
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["schema_version"] == 2
    assert "nav" in manifest
    assert {entry["id"] for entry in manifest["pages"]} == {
        "hub",
        "sound",
        "sound/getting-started",
    }


def test_first_run_publishes_the_manifest_schema(chdir: Path):
    """The schema is package data carried inside `dfo_docs` itself (see
    `dfo_docs.cli._load_schema_bytes`), not a file read from `--repo-root`, so it is
    published unchanged regardless of what `repo_root` happens to point at."""
    repo = _sound_repo(chdir)
    _write_registry(
        chdir,
        sources_yaml=_sources_yaml("sound", repo),
        hub_yaml=_hub_yaml_mounting("sound"),
    )
    out_dir = chdir / "out"

    exit_code = main(["--out", str(out_dir)])

    assert exit_code == 0
    published_schema = (out_dir / "manifest.schema.json").read_text()
    packaged_schema = (
        resources.files("dfo_docs") / "schema" / "manifest.schema.json"
    ).read_text()
    assert published_schema == packaged_schema


def test_generator_commit_resolves_dfo_docs_own_head(chdir: Path):
    """`generator_commit` is resolved through the `dfo_docs` package's own location
    on disk (see `dfo_docs.cli._generator_commit`), not through `--repo-root`, so it
    reports dfo-docs's checkout even though `chdir` here is not a git repository at
    all."""
    repo = _sound_repo(chdir)
    _write_registry(
        chdir,
        sources_yaml=_sources_yaml("sound", repo),
        hub_yaml=_hub_yaml_mounting("sound"),
    )
    package_root = Path(str(resources.files("dfo_docs")))
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=package_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    out_dir = chdir / "out"

    exit_code = main(["--out", str(out_dir)])
    manifest = json.loads((out_dir / "manifest.json").read_text())

    assert exit_code == 0
    assert manifest["generator_commit"] == head


def test_build_reports_page_counts(chdir: Path, capsys: pytest.CaptureFixture):
    repo = _sound_repo(chdir)
    _write_registry(
        chdir,
        sources_yaml=_sources_yaml("sound", repo),
        hub_yaml=_hub_yaml_mounting("sound"),
    )

    exit_code = main(["--out", str(chdir / "out")])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "page: 3" in output


def test_disabled_source_is_reported_by_name_and_not_fetched(
    chdir: Path, capsys: pytest.CaptureFixture
):
    repo = _sound_repo(chdir)
    sources_yaml = _sources_yaml("sound", repo) + (
        "  - name: shelved\n"
        "    repo: ONEcampaign/shelved\n"
        "    enabled: false\n"
        "    reason: Not ready yet.\n"
    )
    _write_registry(
        chdir, sources_yaml=sources_yaml, hub_yaml=_hub_yaml_mounting("sound")
    )

    exit_code = main(["--out", str(chdir / "out")])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "shelved: Not ready yet." in output


# --- the nav-drift defect ------------------------------------------------------------


def test_nav_drift_error_fails_before_manifest_and_publishes_nothing(
    chdir: Path, capsys: pytest.CaptureFixture
):
    repo = _drifted_repo(chdir)
    _write_registry(
        chdir,
        sources_yaml=_sources_yaml("drifted", repo),
        hub_yaml=_hub_yaml_mounting("drifted"),
    )
    out_dir = chdir / "out"

    exit_code = main(["--out", str(out_dir)])
    output = capsys.readouterr().out

    # A corpus-half failure: the roadmap fixture is sound and already published by
    # the time nav drift is caught, so this is 2, not 1 (see dfo_docs.cli.main).
    assert exit_code == 2
    assert "missing.md" in output
    assert "[error]" in output
    assert not out_dir.exists() or not (out_dir / "manifest.json").exists()


def test_nav_drift_warning_does_not_block_the_build(
    chdir: Path, capsys: pytest.CaptureFixture
):
    repo = _untidy_repo(chdir)
    _write_registry(
        chdir,
        sources_yaml=_sources_yaml("untidy", repo),
        hub_yaml=_hub_yaml_mounting("untidy"),
    )

    exit_code = main(["--out", str(chdir / "out")])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "orphan.md" in output
    assert "[warning]" in output


# --- nothing publishes on failure ------------------------------------------------------


def test_guard_failure_leaves_previous_publish_untouched(chdir: Path):
    repo = _directive_repo(chdir)
    _write_registry(
        chdir,
        sources_yaml=_sources_yaml("directive", repo),
        hub_yaml=_hub_yaml_mounting("directive"),
    )
    out_dir = chdir / "out"
    out_dir.mkdir()
    (out_dir / "manifest.json").write_text("[]")
    (out_dir / "corpus").mkdir()
    (out_dir / "corpus" / "sentinel.txt").write_text("previous publish\n")

    exit_code = main(["--out", str(out_dir)])

    # A corpus-half failure with a sound roadmap: 2, not 1 (see dfo_docs.cli.main).
    assert exit_code == 2
    # The old publish is untouched: still the sentinel, not a fresh corpus/manifest.
    assert (out_dir / "corpus" / "sentinel.txt").is_file()
    assert (out_dir / "manifest.json").read_text() == "[]"


def test_no_guards_skips_directive_guard_but_not_nav_drift(chdir: Path):
    directive = _directive_repo(chdir)
    drifted = _drifted_repo(chdir)
    _write_registry(
        chdir,
        sources_yaml=_sources_yaml("directive", directive),
        hub_yaml=_hub_yaml_mounting("directive"),
    )

    # --no-guards lets an otherwise-failing directive guard through...
    assert main(["--out", str(chdir / "out"), "--no-guards"]) == 0

    # ...but never bypasses nav drift, which is not a guard that can be opted out of.
    _write_registry(
        chdir,
        sources_yaml=_sources_yaml("drifted", drifted),
        hub_yaml=_hub_yaml_mounting("drifted"),
    )
    exit_code = main(["--out", str(chdir / "out2"), "--no-guards"])
    # Nav drift is a corpus-half failure with a sound roadmap: 2, not 1.
    assert exit_code == 2


# --- the roadmap and the corpus are two independent artefacts -----------------------


def test_roadmap_guard_failure_returns_1_and_publishes_nothing(
    chdir: Path, capsys: pytest.CaptureFixture
):
    """The roadmap runs ahead of the corpus and is validated in full before either
    artefact is written. An entry naming a category its own track does not declare
    is caught by `dfo_docs.guards.check_roadmap_categories`, so the run stops there
    before the corpus is ever reached: exit 1, and nothing is published at all, not
    even the roadmap."""
    repo = _sound_repo(chdir)
    _write_registry(
        chdir,
        sources_yaml=_sources_yaml("sound", repo),
        hub_yaml=_hub_yaml_mounting("sound"),
    )
    (chdir / "roadmap" / "data.yaml").write_text(
        "track: data\n"
        "categories: []\n"
        "entries:\n"
        "  - id: foo\n"
        "    title: Foo\n"
        "    description: Foo does a thing.\n"
        "    status: under-consideration\n"
        "    categories: [missing-category]\n"
    )
    out_dir = chdir / "out"

    exit_code = main(["--out", str(out_dir)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "missing-category" in output
    assert not out_dir.exists()


def test_roadmap_write_failure_leaves_out_dir_without_roadmap_files(
    chdir: Path, monkeypatch: pytest.MonkeyPatch
):
    """A failure partway through writing the roadmap (here, a `SchemaError` from
    `dfo_docs.cli._load_schema_bytes`, raised after `roadmap.json` and every
    `roadmap/<track>.json` would already have been written) must still leave `out_dir`
    with none of the roadmap's files in it: `_write_roadmap` stages everything and
    moves it into `out_dir` only once every file has been written (see
    `dfo_docs.cli._write_roadmap` and `_publish_roadmap`)."""
    repo = _sound_repo(chdir)
    _write_registry(
        chdir,
        sources_yaml=_sources_yaml("sound", repo),
        hub_yaml=_hub_yaml_mounting("sound"),
    )
    out_dir = chdir / "out"

    real_load_schema_bytes = cli._load_schema_bytes

    def _raise_on_roadmap_schema(filename: str) -> bytes:
        if filename == cli._ROADMAP_INDEX_SCHEMA_FILE:
            raise cli.SchemaError(f"{filename} is missing")
        return real_load_schema_bytes(filename)

    monkeypatch.setattr(cli, "_load_schema_bytes", _raise_on_roadmap_schema)

    exit_code = main(["--out", str(out_dir)])

    assert exit_code == 1
    assert not (out_dir / "roadmap.json").exists()
    assert not (out_dir / "roadmap" / "data.json").exists()
    assert not (out_dir / "roadmap.schema.json").exists()
    assert not (out_dir / "roadmap-track.schema.json").exists()
    assert not out_dir.exists()


def test_corpus_failure_returns_2_having_published_the_roadmap(chdir: Path):
    """A corpus-half failure (nav drift here) must not hold back an otherwise sound
    roadmap: the roadmap publishes unconditionally and first, and only the corpus's
    own exit code moves to 2."""
    repo = _drifted_repo(chdir)
    _write_registry(
        chdir,
        sources_yaml=_sources_yaml("drifted", repo),
        hub_yaml=_hub_yaml_mounting("drifted"),
    )
    out_dir = chdir / "out"

    exit_code = main(["--out", str(out_dir)])

    assert exit_code == 2
    assert (out_dir / "roadmap.json").is_file()
    assert (out_dir / "roadmap" / "data.json").is_file()
    assert (out_dir / "roadmap.schema.json").is_file()
    assert (out_dir / "roadmap-track.schema.json").is_file()
    assert not (out_dir / "manifest.json").exists()


# --- a NormaliseError is reported cleanly, not as a traceback -----------------------


def test_normalise_error_is_reported_cleanly_not_as_a_traceback(
    chdir: Path, capsys: pytest.CaptureFixture
):
    repo = _repo_with_missing_transclusion(chdir)
    _write_registry(
        chdir,
        sources_yaml=_sources_yaml("broken-transclusion", repo),
        hub_yaml=_hub_yaml_mounting("broken-transclusion"),
    )

    exit_code = main(["--out", str(chdir / "out")])
    output = capsys.readouterr().err

    # A NormaliseError raised during the corpus half, with a sound roadmap already
    # published: 2, not 1.
    assert exit_code == 2
    assert output.startswith("error: ")
    assert "MISSING.md" in output


# --- asset copying -----------------------------------------------------------------


def test_source_assets_are_copied_into_corpus(chdir: Path):
    repo = _repo_with_image(chdir)
    _write_registry(
        chdir,
        sources_yaml=_sources_yaml("imaged", repo),
        hub_yaml=_hub_yaml_mounting("imaged"),
    )
    out_dir = chdir / "out"

    exit_code = main(["--out", str(out_dir)])

    assert exit_code == 0
    assert (out_dir / "corpus" / "imaged" / "diagram.png").read_bytes() == _PNG_BYTES


def test_hub_assets_are_copied_into_corpus(chdir: Path):
    repo = _sound_repo(chdir)
    _write_registry(
        chdir,
        sources_yaml=_sources_yaml("sound", repo),
        hub_yaml=_hub_yaml_mounting("sound"),
    )
    hub_content = chdir / "content" / "hub"
    (hub_content / "logo.png").write_bytes(_PNG_BYTES)
    (hub_content / "index.md").write_text("# Hub home\n\n![Logo](logo.png)\n")
    out_dir = chdir / "out"

    exit_code = main(["--out", str(out_dir)])

    assert exit_code == 0
    assert (out_dir / "corpus" / "hub" / "logo.png").read_bytes() == _PNG_BYTES


# --- kind: skill -------------------------------------------------------------------


def _skills_repo(path: Path, files: dict[str, str | bytes]) -> Path:
    """A real `git init` repo carrying the given files under `skills/`."""
    for name, content in files.items():
        file_path = path / "skills" / name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            file_path.write_bytes(content)
        else:
            file_path.write_text(content)
    _git(path, "init", "-q")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    _git(path, "branch", "-M", "main")
    return path


def _skill_sources_yaml(repo: Path) -> str:
    return (
        "sources:\n"
        "  - name: dfo-skills\n"
        f"    repo: {repo}\n"
        "    kind: skill\n"
        "    docs_dir: skills\n"
        "    internal_dir: internal/skills\n"
        "    path: skills\n"
        "    title: All skills\n"
    )


def test_skill_source_publishes_pages_assets_and_drift_warnings(chdir: Path, capsys):
    repo = _skills_repo(
        chdir / "skills-repo",
        {
            "alpha/SKILL.md": "---\nname: alpha\ndescription: Covers alpha.\n---\n",
            "alpha/references/flow-types.md": "# Flow types\n\n![Chart](chart.png)\n",
            "alpha/references/chart.png": _PNG_BYTES,
            "alpha/notes.md": "# Notes\n",
        },
    )
    _write_registry(
        chdir,
        sources_yaml=_skill_sources_yaml(repo),
        hub_yaml=_hub_yaml_mounting("dfo-skills"),
    )
    out_dir = chdir / "out"

    exit_code = main(["--out", str(out_dir)])

    assert exit_code == 0
    corpus = out_dir / "corpus" / "dfo-skills" / "alpha"
    assert (corpus / "SKILL.md").is_file()
    assert (corpus / "references" / "chart.png").read_bytes() == _PNG_BYTES
    manifest = json.loads((out_dir / "manifest.json").read_text())
    kinds = {page["id"]: page["kind"] for page in manifest["pages"]}
    assert kinds["dfo-skills/alpha"] == "skill"
    assert kinds["dfo-skills/alpha/references/flow-types"] == "page"
    report = capsys.readouterr().out
    assert "skills/alpha/notes.md" in report
    # The repo has no internal/skills, which the row names: one warning, and a build.
    assert report.count("[warning] 'dfo-skills': internal_dir 'internal/skills'") == 1


def test_internal_skill_publishes_its_pages_and_assets(chdir: Path, capsys):
    internal = chdir / "skills-repo" / "internal" / "skills" / "beta"
    (internal / "references").mkdir(parents=True)
    (internal / "SKILL.md").write_text(
        "---\nname: beta\ndescription: Covers beta.\n---\n"
    )
    (internal / "references" / "scope.md").write_text(
        "# Scope\n\n![Chart](chart.png)\n"
    )
    (internal / "references" / "chart.png").write_bytes(_PNG_BYTES)
    repo = _skills_repo(
        chdir / "skills-repo",
        {"alpha/SKILL.md": "---\nname: alpha\ndescription: Covers alpha.\n---\n"},
    )
    _write_registry(
        chdir,
        sources_yaml=_skill_sources_yaml(repo),
        hub_yaml=_hub_yaml_mounting("dfo-skills"),
    )
    out_dir = chdir / "out"

    exit_code = main(["--out", str(out_dir)])

    assert exit_code == 0
    corpus = out_dir / "corpus" / "dfo-skills"
    assert (corpus / "beta" / "references" / "chart.png").read_bytes() == _PNG_BYTES
    assert sorted(path.name for path in corpus.glob("*.zip")) == ["alpha.zip"]
    manifest = json.loads((out_dir / "manifest.json").read_text())
    paths = {page["id"]: page["path"] for page in manifest["pages"]}
    assert paths["dfo-skills/beta"] == "skills/beta"
    assert "internal_dir" not in capsys.readouterr().out


def test_skill_directory_without_skill_md_fails_the_corpus(chdir: Path, capsys):
    repo = _skills_repo(chdir / "skills-repo", {"stray/notes.md": "# Notes\n"})
    _write_registry(
        chdir,
        sources_yaml=_skill_sources_yaml(repo),
        hub_yaml=_hub_yaml_mounting("dfo-skills"),
    )
    out_dir = chdir / "out"

    exit_code = main(["--out", str(out_dir)])

    assert exit_code == 2
    assert "skills/stray has no SKILL.md" in capsys.readouterr().err
    assert not (out_dir / "manifest.json").exists()
