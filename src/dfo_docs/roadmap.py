"""Load and validate roadmap/index.yaml and roadmap/<track>.yaml.

Follows `registry.load_sources` for shape: `yaml.safe_load`, `describe_yaml_error` for
a parse failure, and a domain-specific error naming the file and the offending field.

Validation here is structural rather than `jsonschema`-based, since `jsonschema` is a
dev-only dependency; the emitted artefacts are checked against the published schemas
in tests/test_schema.py. Three rules the published schemas cannot express on their own
because they span more than one document -- a track named in the index having a
document whose own `track` agrees, a category an entry names being declared in its own
track, and entry ids being unique across all tracks together -- are build guards
(`dfo_docs.guards`).

Mirrors `manifest.build_pages`'s split between content and envelope: this module
returns each document's own content, and leaves the run's shared envelope fields
(`schema_version`, `generated_at`, `generator_commit`), identical across the index and
every track, for `cli.py` to add once, at emission.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from dfo_docs.models import EntryStatus, RoadmapCategory, RoadmapEntry, RoadmapTrackRef
from dfo_docs.yaml_errors import describe_yaml_error

_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_EXPECTED_RE = re.compile(r"^[0-9]{4}-Q[1-4]$")
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_ENTRY_ID_MAX_LENGTH = 64
_PROVENANCE_RE = re.compile(r"^provenance/[A-Za-z0-9]+$")

_INDEX_FILE = "index.yaml"
_INDEX_REQUIRED_FIELDS = ("id", "label")
_TRACK_REQUIRED_FIELDS = ("track", "categories", "entries")
_CATEGORY_REQUIRED_FIELDS = ("id", "label")
_ENTRY_REQUIRED_FIELDS = ("id", "title", "description", "status")


class RoadmapError(ValueError):
    """roadmap/index.yaml or a roadmap/<track>.yaml failed to load or validate."""


@dataclass(frozen=True)
class RoadmapTrackContent:
    """One track's own content, read from roadmap/<id>.yaml.

    Carries everything `cli.py` needs to emit that track's published document except
    the run's shared envelope fields (`schema_version`, `generated_at`,
    `generator_commit`), which are identical across the index and every track and are
    added once, at emission, rather than read here.
    """

    track: str
    categories: tuple[RoadmapCategory, ...]
    entries: tuple[RoadmapEntry, ...]


def load_roadmap(
    roadmap_dir: Path,
) -> tuple[tuple[RoadmapTrackRef, ...], dict[str, RoadmapTrackContent]]:
    """Load and structurally validate every file under `roadmap_dir`.

    Returns `(index, tracks)`. `index` is roadmap/index.yaml's ordered list of tracks,
    in tab display order with the first as the default tab; each entry's `file` is
    derived as `roadmap/<id>.json` rather than read from the source file. `tracks`
    maps each track's id to its own `RoadmapTrackContent`, read from
    `roadmap/<id>.yaml`.

    Raises RoadmapError, naming the file and the offending field, when `roadmap_dir`
    itself does not exist, on malformed YAML, a missing required field, an `id` that
    is not lowercase-hyphen (or, for an entry id, exceeds 64 characters), a `status`
    outside the four-value enum, an `expected` that is not `YYYY-QN`, a `released_on`
    that is not an ISO 8601 date, a `provenance` that is not a provenance dcid, a `url`
    that is not https://, or a status/field combination the published track schema's conditional rules forbid: a
    `released` entry must carry `released_on` and must not carry `expected`; any other
    entry must carry none of `released_on`, `version` and `provenance`; a `planned` or
    `in-development` entry must carry `expected`.
    """
    if not roadmap_dir.is_dir():
        raise RoadmapError(f"{roadmap_dir}: no such directory")

    index = _load_index(roadmap_dir / _INDEX_FILE)
    tracks = {
        track_ref.id: _load_track(roadmap_dir / f"{track_ref.id}.yaml")
        for track_ref in index
    }
    return index, tracks


def _load_index(path: Path) -> tuple[RoadmapTrackRef, ...]:
    raw = _read_yaml_list(path)
    if not raw:
        raise RoadmapError(f"{path}: expected at least one track")

    seen_ids: set[str] = set()
    refs: list[RoadmapTrackRef] = []
    for row in raw:
        if not isinstance(row, dict):
            raise RoadmapError(
                f"{path}: expected a mapping for each track, got {row!r}"
            )
        for field_name in _INDEX_REQUIRED_FIELDS:
            if field_name not in row:
                raise RoadmapError(
                    f"{path}: track missing required field {field_name!r}: {row!r}"
                )

        track_id = row["id"]
        _validate_id(path, "id", track_id)
        if track_id in seen_ids:
            raise RoadmapError(f"{path}: duplicate track id {track_id!r}")
        seen_ids.add(track_id)

        refs.append(
            RoadmapTrackRef(
                id=track_id,
                label=row["label"],
                file=f"roadmap/{track_id}.json",
                description=row.get("description"),
            )
        )
    return tuple(refs)


def _load_track(path: Path) -> RoadmapTrackContent:
    raw = _read_yaml_mapping(path)
    for field_name in _TRACK_REQUIRED_FIELDS:
        if field_name not in raw:
            raise RoadmapError(f"{path}: missing required field {field_name!r}")

    track_id = raw["track"]
    _validate_id(path, "track", track_id)

    categories_raw = raw["categories"]
    if not isinstance(categories_raw, list):
        raise RoadmapError(f"{path}: categories must be a list")
    categories = tuple(_parse_category(path, row) for row in categories_raw)

    entries_raw = raw["entries"]
    if not isinstance(entries_raw, list):
        raise RoadmapError(f"{path}: entries must be a list")
    entries = tuple(_parse_entry(path, row) for row in entries_raw)

    return RoadmapTrackContent(track=track_id, categories=categories, entries=entries)


def _parse_category(path: Path, row: Any) -> RoadmapCategory:
    if not isinstance(row, dict):
        raise RoadmapError(f"{path}: expected a mapping for each category, got {row!r}")
    for field_name in _CATEGORY_REQUIRED_FIELDS:
        if field_name not in row:
            raise RoadmapError(
                f"{path}: category missing required field {field_name!r}: {row!r}"
            )
    _validate_id(path, "categories[].id", row["id"])
    return RoadmapCategory(id=row["id"], label=row["label"])


def _parse_entry(path: Path, row: Any) -> RoadmapEntry:
    if not isinstance(row, dict):
        raise RoadmapError(f"{path}: expected a mapping for each entry, got {row!r}")
    for field_name in _ENTRY_REQUIRED_FIELDS:
        if field_name not in row:
            raise RoadmapError(
                f"{path}: entry missing required field {field_name!r}: {row!r}"
            )

    entry_id = row["id"]
    _validate_id(path, "entries[].id", entry_id, max_length=_ENTRY_ID_MAX_LENGTH)

    status_raw = row["status"]
    try:
        status = EntryStatus(status_raw)
    except ValueError as exc:
        allowed = [member.value for member in EntryStatus]
        raise RoadmapError(
            f"{path}: entry {entry_id!r} has status {status_raw!r}, "
            f"not one of {allowed}"
        ) from exc

    expected = row.get("expected")
    if expected is not None and not _EXPECTED_RE.match(str(expected)):
        raise RoadmapError(
            f"{path}: entry {entry_id!r} has expected {expected!r}, "
            "which does not match YYYY-QN"
        )

    released_on = row.get("released_on")
    if released_on is not None and not _DATE_RE.match(str(released_on)):
        raise RoadmapError(
            f"{path}: entry {entry_id!r} has released_on {released_on!r}, "
            "which is not an ISO 8601 date"
        )

    version = row.get("version")

    provenance = row.get("provenance")
    if provenance is not None and not _PROVENANCE_RE.match(str(provenance)):
        raise RoadmapError(
            f"{path}: entry {entry_id!r} has provenance {provenance!r}, "
            "which is not a provenance dcid such as provenance/OECDDAC1"
        )

    url = row.get("url")
    if url is not None and not str(url).startswith("https://"):
        raise RoadmapError(
            f"{path}: entry {entry_id!r} has url {url!r}, which is not an https:// URL"
        )

    if status is EntryStatus.RELEASED:
        if released_on is None:
            raise RoadmapError(
                f"{path}: entry {entry_id!r} is released and must carry released_on"
            )
        if expected is not None:
            raise RoadmapError(
                f"{path}: entry {entry_id!r} is released and must not carry expected"
            )
    else:
        if released_on is not None:
            raise RoadmapError(
                f"{path}: entry {entry_id!r} is {status.value} and must not carry "
                "released_on"
            )
        if version is not None:
            raise RoadmapError(
                f"{path}: entry {entry_id!r} is {status.value} and must not carry "
                "version"
            )
        if provenance is not None:
            raise RoadmapError(
                f"{path}: entry {entry_id!r} is {status.value} and must not carry "
                "provenance"
            )
        if (
            status in (EntryStatus.PLANNED, EntryStatus.IN_DEVELOPMENT)
            and expected is None
        ):
            raise RoadmapError(
                f"{path}: entry {entry_id!r} is {status.value} and must carry expected"
            )

    categories = tuple(row.get("categories", []))

    return RoadmapEntry(
        id=entry_id,
        title=row["title"],
        description=row["description"],
        status=status,
        categories=categories,
        expected=expected,
        released_on=released_on,
        version=version,
        provenance=provenance,
        url=url,
    )


def _validate_id(
    path: Path, field_name: str, value: Any, *, max_length: int | None = None
) -> None:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise RoadmapError(f"{path}: {field_name} {value!r} is not lowercase-hyphen")
    if max_length is not None and len(value) > max_length:
        raise RoadmapError(
            f"{path}: {field_name} {value!r} exceeds {max_length} characters"
        )


def _read_yaml_list(path: Path) -> list[Any]:
    data = _read_yaml(path)
    if not isinstance(data, list):
        raise RoadmapError(f"{path}: expected a list at the top level")
    return data


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        raise RoadmapError(f"{path}: expected a mapping at the top level")
    return data


def _read_yaml(path: Path) -> Any:
    try:
        text = path.read_text()
    except FileNotFoundError as exc:
        raise RoadmapError(f"{path}: file not found") from exc

    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RoadmapError(f"{path}: {describe_yaml_error(exc)}") from exc
