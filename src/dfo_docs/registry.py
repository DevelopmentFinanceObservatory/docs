"""Load and validate sources.yaml and hub.yaml.

sources.yaml populates a dict of `Source` keyed by name. hub.yaml populates a `HubNode` tree that
`manifest.build_pages` walks into the published nav tree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from dfo_docs.models import FETCHED_KINDS, HubNode, Source, SourceKind
from dfo_docs.yaml_errors import describe_yaml_error

_REQUIRED_SOURCE_FIELDS = ("name", "repo")
# A skill row has no sidecar to supply these, so the row itself must.
_REQUIRED_SKILL_FIELDS = ("docs_dir", "path", "title")


class RegistryError(ValueError):
    """sources.yaml or hub.yaml failed to load or validate."""


def load_sources(path: Path) -> dict[str, Source]:
    """Load, validate, and index sources.yaml by name.

    Every row is returned, enabled or not, so a disabled row can still be reported by name. Raises
    RegistryError on a missing required field, a duplicate name, a duplicate path, an external
    row carrying a docs_dir, an external or skill row carrying exclude, or a row that is not
    a skill row carrying internal_dir.
    """
    raw = _read_yaml(path)
    rows = raw.get("sources", [])
    sources: dict[str, Source] = {}
    paths_seen: dict[str, str] = {}

    for row in rows:
        source = _parse_source(row)
        if source.name in sources:
            raise RegistryError(f"duplicate source name: {source.name!r}")
        if source.path is not None:
            if source.path in paths_seen:
                raise RegistryError(
                    f"duplicate path {source.path!r}: claimed by "
                    f"{paths_seen[source.path]!r} and {source.name!r}"
                )
            paths_seen[source.path] = source.name
        sources[source.name] = source

    return sources


def enabled_sources(sources: dict[str, Source]) -> dict[str, Source]:
    """Return only the rows the build should act on."""
    return {name: source for name, source in sources.items() if source.enabled}


def load_hub(path: Path) -> HubNode:
    """Load hub.yaml into its root HubNode.

    The root's own `title` is the hub's site title; its `children` are the hub's own nav plus the
    tree the registered sources mount into.
    """
    raw = _read_yaml(path)
    children = tuple(_parse_hub_node(child) for child in raw.get("nav", []))
    return HubNode(title=raw.get("title"), children=children)


def _parse_source(row: dict[str, Any]) -> Source:
    for field_name in _REQUIRED_SOURCE_FIELDS:
        if field_name not in row:
            raise RegistryError(
                f"source row missing required field {field_name!r}: {row!r}"
            )

    kind = SourceKind(row.get("kind", SourceKind.DOCS))
    docs_dir = row.get("docs_dir", "docs" if kind is SourceKind.DOCS else None)

    if kind is SourceKind.EXTERNAL and docs_dir is not None:
        raise RegistryError(f"external source {row['name']!r} may not carry docs_dir")
    if kind is SourceKind.SKILL:
        for field_name in _REQUIRED_SKILL_FIELDS:
            if field_name not in row:
                raise RegistryError(
                    f"skill source {row['name']!r} missing required field {field_name!r}"
                )

    exclude = row.get("exclude", [])
    if not isinstance(exclude, list) or not all(isinstance(p, str) for p in exclude):
        raise RegistryError(
            f"source {row['name']!r}: exclude must be a list of glob patterns"
        )
    if exclude and kind is SourceKind.EXTERNAL:
        raise RegistryError(
            f"external source {row['name']!r} may not carry exclude; it publishes no pages"
        )
    if exclude and kind is SourceKind.SKILL:
        raise RegistryError(
            f"skill source {row['name']!r} may not carry exclude; a skill directory "
            "whose name starts with '_' is already left out"
        )

    internal_dir = row.get("internal_dir")
    if internal_dir is not None and kind is not SourceKind.SKILL:
        raise RegistryError(
            f"source {row['name']!r} may not carry internal_dir; only a skill source "
            "reads a second directory"
        )
    if internal_dir is not None and not isinstance(internal_dir, str):
        raise RegistryError(
            f"skill source {row['name']!r}: internal_dir must be a path"
        )

    return Source(
        name=row["name"],
        repo=row["repo"],
        kind=kind,
        ref=row.get("ref", "main" if kind in FETCHED_KINDS else None),
        commit=row.get("commit"),
        docs_dir=docs_dir,
        path=row.get("path"),
        url=row.get("url"),
        title=row.get("title"),
        enabled=row.get("enabled", True),
        reason=row.get("reason"),
        exclude=tuple(exclude),
        internal_dir=internal_dir,
    )


def _parse_hub_node(row: dict[str, Any]) -> HubNode:
    children = tuple(_parse_hub_node(child) for child in row.get("children", []))
    return HubNode(
        title=row.get("title"),
        page=row.get("page"),
        mount=row.get("mount"),
        external=row.get("external"),
        children=children,
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text()
    except FileNotFoundError as exc:
        raise RegistryError(f"{path}: file not found") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RegistryError(f"{path}: {describe_yaml_error(exc)}") from exc

    if not isinstance(data, dict):
        raise RegistryError(f"{path}: expected a mapping at the top level")
    return data
