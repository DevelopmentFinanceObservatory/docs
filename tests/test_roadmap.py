"""Tests for dfo_docs.roadmap: loading and validating roadmap/index.yaml and
roadmap/<track>.yaml.
"""

from pathlib import Path

import pytest

from dfo_docs.models import EntryStatus
from dfo_docs.roadmap import RoadmapError, load_roadmap

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_track(
    tmp_path: Path,
    name: str,
    body: str,
    *,
    index_ids: tuple[str, ...] = ("data",),
) -> Path:
    """Write `roadmap/index.yaml` naming `index_ids` and `roadmap/<name>.yaml` holding
    `body`, and return the `roadmap/` directory.
    """
    roadmap_dir = tmp_path / "roadmap"
    roadmap_dir.mkdir()
    index_rows = "\n".join(
        f"- id: {track_id}\n  label: {track_id.title()}" for track_id in index_ids
    )
    (roadmap_dir / "index.yaml").write_text(index_rows + "\n")
    (roadmap_dir / f"{name}.yaml").write_text(body)
    return roadmap_dir


def test_load_roadmap_real_files():
    index, tracks = load_roadmap(REPO_ROOT / "roadmap")

    assert [ref.id for ref in index] == ["data", "platform", "ai-tools"]
    assert index[0].file == "roadmap/data.json"
    assert index[0].label == "Data"
    assert index[1].description is None

    assert set(tracks) == {"data", "platform", "ai-tools"}

    data = tracks["data"]
    assert data.track == "data"
    assert [category.id for category in data.categories] == [
        "aid-oda",
        "debt",
        "climate",
        "humanitarian",
    ]
    # data.yaml may carry more entries than these three real ones (see the
    # cross-track coverage checks below), but these three must still be among them.
    entries_by_id = {entry.id for entry in data.entries}
    assert entries_by_id >= {"mdb-flows", "south-south-cooperation", "crs-2025"}

    released = next(entry for entry in data.entries if entry.id == "crs-2025")
    assert released.status == EntryStatus.RELEASED
    assert released.released_on == "2026-06-12"
    assert released.version == "4.2.0"
    assert released.expected is None

    in_development = next(entry for entry in data.entries if entry.id == "mdb-flows")
    assert in_development.status == EntryStatus.IN_DEVELOPMENT
    assert in_development.expected == "2026-Q3"

    # platform.yaml and ai-tools.yaml declare a placeholder category vocabulary for
    # their owning team to replace; every label must say so plainly.
    for track_id in ("platform", "ai-tools"):
        assert tracks[track_id].categories
        for category in tracks[track_id].categories:
            assert category.label.startswith("Placeholder: ")

    # The three track files together must give the website team one worked example
    # of every case the published contract allows. These are asserted as properties
    # computed over the loaded tracks, rather than by naming placeholder ids, so
    # replacing a placeholder with a real entry that covers the same case keeps this
    # passing.
    all_entries = [entry for content in tracks.values() for entry in content.entries]

    assert {entry.status for entry in all_entries} == set(EntryStatus)

    released_entries = [
        entry for entry in all_entries if entry.status == EntryStatus.RELEASED
    ]
    assert any(entry.version is not None for entry in released_entries)
    assert any(entry.version is None for entry in released_entries)

    assert any(len(entry.categories) > 1 for entry in all_entries)
    assert any(len(entry.categories) == 0 for entry in all_entries)

    # Every entry whose title flags it as a placeholder must say so, plainly, in its
    # own description, so the labelling requirement is enforced by the suite rather
    # than caught only on review.
    placeholders = [
        entry for entry in all_entries if entry.title.startswith("Placeholder: ")
    ]
    assert placeholders
    for entry in placeholders:
        first_sentence = entry.description.split(". ", 1)[0].lower()
        assert "placeholder" in first_sentence, (
            f"entry {entry.id!r} is titled as a placeholder but its description's "
            "first sentence does not say so"
        )


def test_missing_roadmap_directory_rejected(tmp_path):
    with pytest.raises(RoadmapError, match="no such directory"):
        load_roadmap(tmp_path / "roadmap")


def test_malformed_index_yaml_names_the_file(tmp_path):
    roadmap_dir = tmp_path / "roadmap"
    roadmap_dir.mkdir()
    (roadmap_dir / "index.yaml").write_text(
        """
        - id: data
          label: Data
        - not: valid
          - nesting
        """
    )

    with pytest.raises(RoadmapError, match=r"index\.yaml"):
        load_roadmap(roadmap_dir)


def test_malformed_track_yaml_names_the_file(tmp_path):
    roadmap_dir = _write_track(
        tmp_path,
        "data",
        """
        track: data
        categories: []
          - not: valid
        entries: []
        """,
    )

    with pytest.raises(RoadmapError, match=r"data\.yaml"):
        load_roadmap(roadmap_dir)


def test_missing_required_field_on_entry_rejected(tmp_path):
    roadmap_dir = _write_track(
        tmp_path,
        "data",
        """
        track: data
        categories: []
        entries:
          - id: an-entry
            title: An Entry
            status: under-consideration
        """,
    )

    with pytest.raises(RoadmapError, match="description"):
        load_roadmap(roadmap_dir)


def test_bad_entry_id_pattern_rejected(tmp_path):
    roadmap_dir = _write_track(
        tmp_path,
        "data",
        """
        track: data
        categories: []
        entries:
          - id: Not_Lowercase
            title: An Entry
            description: Something.
            status: under-consideration
        """,
    )

    with pytest.raises(RoadmapError, match="not lowercase-hyphen"):
        load_roadmap(roadmap_dir)


def test_status_outside_enum_rejected(tmp_path):
    roadmap_dir = _write_track(
        tmp_path,
        "data",
        """
        track: data
        categories: []
        entries:
          - id: an-entry
            title: An Entry
            description: Something.
            status: shipped
        """,
    )

    with pytest.raises(RoadmapError, match="status"):
        load_roadmap(roadmap_dir)


def test_malformed_expected_rejected(tmp_path):
    roadmap_dir = _write_track(
        tmp_path,
        "data",
        """
        track: data
        categories: []
        entries:
          - id: an-entry
            title: An Entry
            description: Something.
            status: planned
            expected: "2026-04"
        """,
    )

    with pytest.raises(RoadmapError, match="expected"):
        load_roadmap(roadmap_dir)


def test_released_entry_carrying_expected_rejected(tmp_path):
    roadmap_dir = _write_track(
        tmp_path,
        "data",
        """
        track: data
        categories: []
        entries:
          - id: an-entry
            title: An Entry
            description: Something.
            status: released
            released_on: "2026-01-01"
            expected: "2026-Q1"
        """,
    )

    with pytest.raises(RoadmapError, match="must not carry expected"):
        load_roadmap(roadmap_dir)


def test_planned_entry_missing_expected_rejected(tmp_path):
    roadmap_dir = _write_track(
        tmp_path,
        "data",
        """
        track: data
        categories: []
        entries:
          - id: an-entry
            title: An Entry
            description: Something.
            status: planned
        """,
    )

    with pytest.raises(RoadmapError, match="must carry expected"):
        load_roadmap(roadmap_dir)


def test_released_entry_missing_released_on_rejected(tmp_path):
    roadmap_dir = _write_track(
        tmp_path,
        "data",
        """
        track: data
        categories: []
        entries:
          - id: an-entry
            title: An Entry
            description: Something.
            status: released
        """,
    )

    with pytest.raises(RoadmapError, match="must carry released_on"):
        load_roadmap(roadmap_dir)


def test_non_released_entry_may_not_carry_released_on(tmp_path):
    roadmap_dir = _write_track(
        tmp_path,
        "data",
        """
        track: data
        categories: []
        entries:
          - id: an-entry
            title: An Entry
            description: Something.
            status: under-consideration
            released_on: "2026-01-01"
        """,
    )

    with pytest.raises(RoadmapError, match="must not carry released_on"):
        load_roadmap(roadmap_dir)


def test_non_released_entry_may_not_carry_version(tmp_path):
    roadmap_dir = _write_track(
        tmp_path,
        "data",
        """
        track: data
        categories: []
        entries:
          - id: an-entry
            title: An Entry
            description: Something.
            status: under-consideration
            version: "1.0.0"
        """,
    )

    with pytest.raises(RoadmapError, match="must not carry version"):
        load_roadmap(roadmap_dir)
