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
    assert data.categories
    for track in tracks.values():
        assert track.categories
        assert track.entries
        assert all(
            not category.label.startswith("Placeholder:")
            for category in track.categories
        )
        assert all(
            not entry.title.startswith("Placeholder:") for entry in track.entries
        )

    all_entries = [entry for content in tracks.values() for entry in content.entries]
    assert {entry.status for entry in all_entries} == set(EntryStatus)


def test_load_roadmap_contract_examples(tmp_path):
    """Optional contract shapes belong in fixtures, independent of public scope."""
    roadmap_dir = _write_track(
        tmp_path,
        "data",
        """
        track: data
        categories:
          - id: aid
            label: Aid
          - id: debt
            label: Debt
        entries:
          - id: released-version
            title: Versioned dataset
            description: A versioned dataset release.
            categories: [aid, debt]
            status: released
            released_on: "2026-01-01"
            version: "1.0.0"
          - id: released-unversioned
            title: Dataset
            description: A dataset release.
            status: released
            released_on: "2026-01-01"
          - id: developing
            title: Dataset in development
            description: An additional dataset.
            status: in-development
            expected: "2026-Q4"
          - id: planned
            title: Planned dataset
            description: An additional dataset.
            status: planned
            expected: "2027-Q1"
          - id: considered
            title: Candidate dataset
            description: An additional dataset.
            status: under-consideration
        """,
    )
    _, tracks = load_roadmap(roadmap_dir)
    all_entries = list(tracks["data"].entries)
    assert {entry.status for entry in all_entries} == set(EntryStatus)

    released_entries = [
        entry for entry in all_entries if entry.status == EntryStatus.RELEASED
    ]
    assert any(entry.version is not None for entry in released_entries)
    assert any(entry.version is None for entry in released_entries)

    assert any(len(entry.categories) > 1 for entry in all_entries)
    assert any(len(entry.categories) == 0 for entry in all_entries)


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


def test_released_entry_carries_provenance(tmp_path):
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
            provenance: provenance/OECDDAC1
        """,
    )

    _, tracks = load_roadmap(roadmap_dir)

    assert tracks["data"].entries[0].provenance == "provenance/OECDDAC1"


def test_non_released_entry_may_not_carry_provenance(tmp_path):
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
            provenance: provenance/OECDDAC1
        """,
    )

    with pytest.raises(RoadmapError, match="must not carry provenance"):
        load_roadmap(roadmap_dir)


@pytest.mark.parametrize(
    "provenance", ["OECDDAC1", "provenance/", "provenance/OECD DAC1"]
)
def test_provenance_must_be_a_provenance_dcid(tmp_path, provenance):
    roadmap_dir = _write_track(
        tmp_path,
        "data",
        f"""
        track: data
        categories: []
        entries:
          - id: an-entry
            title: An Entry
            description: Something.
            status: released
            released_on: "2026-01-01"
            provenance: "{provenance}"
        """,
    )

    with pytest.raises(RoadmapError, match="is not a provenance dcid"):
        load_roadmap(roadmap_dir)


def test_entry_carries_url(tmp_path):
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
            url: https://example.org/data
        """,
    )

    _, tracks = load_roadmap(roadmap_dir)

    assert tracks["data"].entries[0].url == "https://example.org/data"


@pytest.mark.parametrize("url", ["http://example.org/data", "example.org/data"])
def test_url_must_be_https(tmp_path, url):
    roadmap_dir = _write_track(
        tmp_path,
        "data",
        f"""
        track: data
        categories: []
        entries:
          - id: an-entry
            title: An Entry
            description: Something.
            status: under-consideration
            url: "{url}"
        """,
    )

    with pytest.raises(RoadmapError, match="is not an https:// URL"):
        load_roadmap(roadmap_dir)
