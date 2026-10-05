"""Tests for dfo_docs.fetch: sparse checkout, provenance, and error collection.

Fixture repositories are real `git init` repos under `tmp_path`, committed to and cloned
from a local path, so these tests exercise real git without touching the network.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from dfo_docs.fetch import FetchError, fetch_all, fetch_source, last_modified
from dfo_docs.models import Source, SourceKind

COMMIT_DATE = "2026-08-14T16:43:28+00:00"


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
    """A bare-bones git repo, initialised and on branch `main`, with no commits yet."""
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    return repo


def _commit_all(repo: Path, message: str, *, date: str = COMMIT_DATE) -> str:
    """Stage and commit everything in `repo` at a fixed date, returning the SHA."""
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


def _docs_source(repo: Path, **overrides) -> Source:
    fields = {
        "name": "sample",
        "repo": str(repo),
        "ref": "main",
        "docs_dir": "docs",
    }
    fields.update(overrides)
    return Source(**fields)


def test_fetch_source_success(tmp_path):
    repo = _make_repo(tmp_path, "sample")
    (repo / "mkdocs.yml").write_text("site_name: Sample\n")
    (repo / "docs").mkdir()
    (repo / "docs" / "index.md").write_text("# Sample\n")
    _commit_all(repo, "init")

    source = _docs_source(repo)
    fetched = fetch_source(source, workdir=tmp_path / "work")

    assert fetched.source is source
    assert fetched.docs_root == fetched.repo_root / "docs"
    assert (fetched.docs_root / "index.md").exists()
    assert (fetched.repo_root / "mkdocs.yml").exists()
    assert len(fetched.commit) == 40


def test_fetch_source_empty_docs_dir_raises(tmp_path):
    repo = _make_repo(tmp_path, "empty-docs")
    (repo / "mkdocs.yml").write_text("site_name: Empty\n")
    (repo / "docs").mkdir()
    (repo / "docs" / ".gitkeep").write_text("")
    (repo / "other.txt").write_text("keep the repo non-empty\n")
    _commit_all(repo, "init")

    source = _docs_source(repo, name="empty-docs")
    with pytest.raises(ValueError, match="no Markdown"):
        fetch_source(source, workdir=tmp_path / "work")


def test_fetch_source_missing_docs_dir_raises(tmp_path):
    repo = _make_repo(tmp_path, "no-docs")
    (repo / "mkdocs.yml").write_text("site_name: NoDocs\n")
    (repo / "README.md").write_text("# no docs dir here\n")
    _commit_all(repo, "init")

    source = _docs_source(repo, name="no-docs")
    with pytest.raises(ValueError, match="does not exist"):
        fetch_source(source, workdir=tmp_path / "work")


def test_fetch_all_collects_every_failure(tmp_path):
    good_repo = _make_repo(tmp_path, "good")
    (good_repo / "docs").mkdir()
    (good_repo / "docs" / "index.md").write_text("# Good\n")
    _commit_all(good_repo, "init")

    bad_repo_a = _make_repo(tmp_path, "bad-a")
    (bad_repo_a / "README.md").write_text("no docs dir\n")
    _commit_all(bad_repo_a, "init")

    bad_repo_b = _make_repo(tmp_path, "bad-b")
    (bad_repo_b / "docs").mkdir()
    (bad_repo_b / "docs" / ".gitkeep").write_text("")
    (bad_repo_b / "other.txt").write_text("keep the repo non-empty\n")
    _commit_all(bad_repo_b, "init")

    sources = [
        _docs_source(good_repo, name="good"),
        _docs_source(bad_repo_a, name="bad-a"),
        _docs_source(bad_repo_b, name="bad-b"),
    ]

    with pytest.raises(FetchError) as excinfo:
        fetch_all(sources, workdir=tmp_path / "work")

    assert set(excinfo.value.failures) == {"bad-a", "bad-b"}
    assert "does not exist" in excinfo.value.failures["bad-a"]
    assert "no Markdown" in excinfo.value.failures["bad-b"]


def test_fetch_source_honours_pinned_commit_over_ref(tmp_path):
    repo = _make_repo(tmp_path, "pinned")
    (repo / "docs").mkdir()
    (repo / "docs" / "index.md").write_text("v1\n")
    first_commit = _commit_all(repo, "v1")

    (repo / "docs" / "index.md").write_text("v2\n")
    _commit_all(repo, "v2", date="2026-08-15T09:00:00+00:00")

    source = _docs_source(repo, name="pinned", ref="main", commit=first_commit)
    fetched = fetch_source(source, workdir=tmp_path / "work")

    assert fetched.commit == first_commit
    assert (fetched.docs_root / "index.md").read_text() == "v1\n"


def test_last_modified_returns_committed_date(tmp_path):
    repo = _make_repo(tmp_path, "dated")
    (repo / "docs").mkdir()
    (repo / "docs" / "index.md").write_text("# Dated\n")
    _commit_all(repo, "init", date=COMMIT_DATE)

    source = _docs_source(repo, name="dated")
    fetched = fetch_source(source, workdir=tmp_path / "work")

    assert last_modified(fetched.repo_root, "docs/index.md") == "2026-08-14T16:43:28Z"


def test_fetch_source_clones_a_skill_source(tmp_path):
    repo = _make_repo(tmp_path, "skills-repo")
    (repo / "skills" / "alpha").mkdir(parents=True)
    (repo / "skills" / "alpha" / "SKILL.md").write_text("---\nname: alpha\n---\n")
    _commit_all(repo, "init")

    source = _docs_source(repo, kind=SourceKind.SKILL, docs_dir="skills")
    fetched = fetch_source(source, workdir=tmp_path / "work")

    assert (fetched.docs_root / "alpha" / "SKILL.md").exists()


def test_fetch_source_rejects_an_external_source(tmp_path):
    source = Source(
        name="pkg", repo="org/pkg", kind=SourceKind.EXTERNAL, ref=None, docs_dir=None
    )
    with pytest.raises(ValueError, match="not a fetched source"):
        fetch_source(source, workdir=tmp_path / "work")
