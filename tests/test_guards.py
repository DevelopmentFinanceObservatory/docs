"""Tests for dfo_docs.guards: the nav-drift and roadmap checks."""

from __future__ import annotations

from pathlib import Path

from dfo_docs.guards import (
    check_nav_drift,
    check_roadmap_categories,
    check_roadmap_entry_ids,
    check_roadmap_reverse_index,
    check_roadmap_track_ids,
    guard_failed,
)
from dfo_docs.models import (
    EntryStatus,
    NavEntry,
    RoadmapCategory,
    RoadmapEntry,
    RoadmapTrackRef,
    Sidecar,
    Source,
)
from dfo_docs.roadmap import RoadmapTrackContent


def test_nav_drift_stays_silent_about_a_deliberately_excluded_file(tmp_path: Path):
    repo_root = tmp_path / "tossd-reader"
    docs_root = repo_root / "docs"
    (docs_root / "reference").mkdir(parents=True)
    (docs_root / "index.md").write_text("# Home\n")
    (docs_root / "reference" / "query.md").write_text("# Query\n")

    sidecar = Sidecar(
        path="tools/tossd-reader",
        title="TOSSD reader",
        description=None,
        nav=(NavEntry(file="index.md", title=None, breadcrumb=()),),
        docs_root=docs_root,
        excluded=("reference/query.md",),
    )
    source = Source(
        name="tossd-reader",
        repo="ONEcampaign/tossd-reader",
        exclude=("reference/*",),
    )

    assert check_nav_drift(sidecar, source, repo_root) == []


def test_nav_drift_still_warns_about_an_unnavigated_file_that_no_pattern_excludes(
    tmp_path: Path,
):
    repo_root = tmp_path / "tossd-reader"
    docs_root = repo_root / "docs"
    (docs_root / "reference").mkdir(parents=True)
    (docs_root / "index.md").write_text("# Home\n")
    (docs_root / "reference" / "query.md").write_text("# Query\n")
    (docs_root / "orphan.md").write_text("# Orphan\n")

    sidecar = Sidecar(
        path="tools/tossd-reader",
        title="TOSSD reader",
        description=None,
        nav=(NavEntry(file="index.md", title=None, breadcrumb=()),),
        docs_root=docs_root,
        excluded=("reference/query.md",),
    )
    source = Source(
        name="tossd-reader",
        repo="ONEcampaign/tossd-reader",
        exclude=("reference/*",),
    )

    findings = check_nav_drift(sidecar, source, repo_root)

    assert len(findings) == 1
    assert findings[0].path == "docs/orphan.md"


# --- roadmap guards: check_roadmap_track_ids, _reverse_index, _categories, _entry_ids


def _ref(*, id: str, file: str | None = None) -> RoadmapTrackRef:
    return RoadmapTrackRef(id=id, label=id.title(), file=file or f"roadmap/{id}.json")


def _entry(
    *,
    id: str,
    categories: tuple[str, ...] = (),
    status: EntryStatus = EntryStatus.UNDER_CONSIDERATION,
) -> RoadmapEntry:
    return RoadmapEntry(
        id=id,
        title="Title",
        description="Description.",
        status=status,
        categories=categories,
    )


def _track(
    *,
    track: str,
    categories: tuple[RoadmapCategory, ...] = (),
    entries: tuple[RoadmapEntry, ...] = (),
) -> RoadmapTrackContent:
    return RoadmapTrackContent(track=track, categories=categories, entries=entries)


def test_track_ids_agreeing_passes():
    index = (_ref(id="data"),)
    tracks = {"data": _track(track="data")}

    assert check_roadmap_track_ids(index, tracks) == []


def test_track_id_disagreeing_with_its_index_entry_fails():
    index = (_ref(id="data"),)
    tracks = {"data": _track(track="platform")}

    findings = check_roadmap_track_ids(index, tracks)

    assert guard_failed(findings)
    assert any("platform" in f.message for f in findings)


def test_reverse_index_stray_track_file_fails(tmp_path: Path):
    roadmap_dir = tmp_path / "roadmap"
    roadmap_dir.mkdir()
    (roadmap_dir / "index.yaml").write_text("- id: data\n  label: Data\n")
    (roadmap_dir / "data.yaml").write_text("track: data\n")
    (roadmap_dir / "platform.yaml").write_text("track: platform\n")

    findings = check_roadmap_reverse_index(roadmap_dir, (_ref(id="data"),))

    assert guard_failed(findings)
    assert any("platform.yaml" in f.message for f in findings)


def test_reverse_index_with_no_stray_file_passes(tmp_path: Path):
    roadmap_dir = tmp_path / "roadmap"
    roadmap_dir.mkdir()
    (roadmap_dir / "index.yaml").write_text("- id: data\n  label: Data\n")
    (roadmap_dir / "data.yaml").write_text("track: data\n")

    assert check_roadmap_reverse_index(roadmap_dir, (_ref(id="data"),)) == []


def test_entry_category_declared_by_its_own_track_passes():
    tracks = {
        "data": _track(
            track="data",
            categories=(RoadmapCategory(id="aid-oda", label="Aid & ODA"),),
            entries=(_entry(id="a", categories=("aid-oda",)),),
        )
    }

    assert check_roadmap_categories(tracks) == []


def test_entry_category_not_declared_by_its_own_track_fails():
    tracks = {
        "data": _track(
            track="data",
            categories=(),
            entries=(_entry(id="a", categories=("aid-oda",)),),
        )
    }

    findings = check_roadmap_categories(tracks)

    assert guard_failed(findings)
    assert any("aid-oda" in f.message for f in findings)


def test_entry_ids_unique_across_tracks_passes():
    tracks = {
        "data": _track(track="data", entries=(_entry(id="a"),)),
        "platform": _track(track="platform", entries=(_entry(id="b"),)),
    }

    assert check_roadmap_entry_ids(tracks) == []


def test_duplicate_entry_id_within_one_track_file_fails():
    tracks = {"data": _track(track="data", entries=(_entry(id="a"), _entry(id="a")))}

    findings = check_roadmap_entry_ids(tracks)

    assert guard_failed(findings)
    assert any("'a'" in f.message for f in findings)


def test_duplicate_entry_id_across_two_tracks_fails():
    tracks = {
        "data": _track(track="data", entries=(_entry(id="a"),)),
        "platform": _track(track="platform", entries=(_entry(id="a"),)),
    }

    findings = check_roadmap_entry_ids(tracks)

    assert guard_failed(findings)
    assert any("'a'" in f.message for f in findings)
