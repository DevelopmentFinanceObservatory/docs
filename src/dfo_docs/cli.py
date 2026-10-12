"""Argument parsing and the run sequence executed by both `scripts/build.py` and
`dfo-docs-build`.

Runs the roadmap and the corpus as two independent artefacts, in that order. The
roadmap reads local files under `roadmap/` and fetches nothing, so every way the docs
build can fail is caused by something the roadmap does not touch; running it first and
publishing it unconditionally, ahead of `load_sources`, is what stops a broken
`sources.yaml` from blocking a roadmap update that has nothing to do with it. Load
`roadmap/index.yaml` and every `roadmap/<track>.yaml`, run the roadmap's own guards,
and, only if they pass, write `roadmap.json`, `roadmap/<track>.json`, and both roadmap
schemas to a staging area and move them into `--out` in one pass. Then load the
registry and hub, fetch every enabled `docs`- and `skill`-kind source, load each docs
source's sidecar or each skill source's skills and check it for drift, build the corpus and manifest into a staging area, run the
guards, and only then move the staged output into place. Runs from the repository
root; `sources.yaml`, `hub.yaml`, `roadmap/`, and `content/hub/` are all read relative
to the current directory, matching how the README tells someone to invoke this.

Two properties this preserves from the modules it wires together, one scoped per
artefact rather than to the whole run. Nothing publishes on failure, for either
artefact on its own: the roadmap is validated in full before a single file of it is
written, and the corpus and manifest are written to a staging directory and moved into
`--out` only once every corpus check has passed, regardless of whether the roadmap
half published this run. Neither half's failure touches what the other already wrote.
And one run reports every problem in each half it reaches. Nav-drift findings are
collected across every fetched source, and the guards run once against the whole
build, rather than either one stopping at the first thing it finds.

See `main` for the three-way exit code this split produces.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from dfo_docs.assets import copy_assets
from dfo_docs.fetch import FetchError, fetch_all
from dfo_docs.guards import (
    Finding,
    check_directives,
    check_nav_drift,
    check_roadmap_categories,
    check_roadmap_entry_ids,
    check_roadmap_reverse_index,
    check_roadmap_track_ids,
    check_uniqueness,
    guard_failed,
)
from dfo_docs.manifest import ManifestError, build_pages, write_manifest
from dfo_docs.models import (
    FETCHED_KINDS,
    ROADMAP_INDEX_SCHEMA_VERSION,
    ROADMAP_TRACK_SCHEMA_VERSION,
    SCHEMA_VERSION,
    Manifest,
    Page,
    RoadmapCategory,
    RoadmapEntry,
    RoadmapIndex,
    RoadmapTrack,
    RoadmapTrackRef,
    Sidecar,
    SourceKind,
)
from dfo_docs.normalise import NormaliseError
from dfo_docs.registry import RegistryError, enabled_sources, load_hub, load_sources
from dfo_docs.roadmap import RoadmapError, RoadmapTrackContent, load_roadmap
from dfo_docs.sidecar import SidecarError, load_sidecar
from dfo_docs.skills import (
    SkillError,
    check_internal_dir,
    check_skill_drift,
    load_skills,
    skill_roots,
)

_SOURCES_FILE = "sources.yaml"
_HUB_FILE = "hub.yaml"
_HUB_CONTENT_DIR = "content/hub"
_HUB_CORPUS_NAME = "hub"
_CORPUS_DIR = "corpus"
_MANIFEST_FILE = "manifest.json"
_SCHEMA_DEST_FILE = "manifest.schema.json"
_SCHEMA_PACKAGE_DIR = "schema"

_ROADMAP_DIR = "roadmap"
_ROADMAP_INDEX_FILE = "roadmap.json"
_ROADMAP_INDEX_SCHEMA_FILE = "roadmap.schema.json"
_ROADMAP_TRACK_SCHEMA_FILE = "roadmap-track.schema.json"


class SchemaError(RuntimeError):
    """A published schema is missing from the installed `dfo_docs` package.

    Every schema ships as package data under `dfo_docs/schema/`, loaded through
    `importlib.resources` rather than as a path relative to `--repo-root` or the
    current directory, so it resolves identically from a source checkout, an
    installed wheel, and any registry a caller points `--repo-root` at.
    """


def _load_schema_bytes(filename: str) -> bytes:
    traversable = resources.files("dfo_docs") / _SCHEMA_PACKAGE_DIR / filename
    try:
        return traversable.read_bytes()
    except FileNotFoundError as exc:
        raise SchemaError(
            f"{filename} is missing from the installed dfo_docs package; "
            "reinstall dfo-docs or check that pyproject.toml packages "
            f"{_SCHEMA_PACKAGE_DIR}/ as package data"
        ) from exc


def main(argv: Sequence[str] | None = None) -> int:
    """Run one build. Returns the process exit code.

    Three-way, because the roadmap and the corpus are two independent artefacts (see
    the module docstring) and either can publish while the other does not.

    0 if both the roadmap and the corpus published cleanly. 1 if the roadmap failed
    to load or its own guards found a `Severity.ERROR`, or if anything before the
    roadmap is even written failed outright; nothing is published at all. 2 if the
    roadmap published but the corpus half then failed: any finding is a
    `Severity.ERROR` (nav drift, a leaked directive, a duplicate id), or fetching or
    loading the registry failed outright.
    """
    args = _parse_args(argv)
    repo_root = args.repo_root or Path.cwd()

    try:
        return _run(args, repo_root=repo_root)
    except (
        RegistryError,
        FetchError,
        SidecarError,
        SkillError,
        ManifestError,
        NormaliseError,
        SchemaError,
        RoadmapError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace, *, repo_root: Path) -> int:
    """Publish the roadmap, then the corpus, each independently.

    A `RoadmapError` or a `SchemaError` raised while loading or writing the roadmap
    propagates straight to `main`'s catch-all and returns 1: nothing has been
    published yet at that point, on either half. Once the roadmap guards have passed
    and the roadmap itself is written, every exception the corpus half can raise is
    caught here instead, and returns 2, since the roadmap is already published and a
    corpus failure gets its own exit code, distinct from a roadmap-stage failure that
    published nothing.
    """
    roadmap_findings = _run_roadmap(repo_root=repo_root, out_dir=args.out)
    if guard_failed(roadmap_findings):
        return 1

    try:
        return _run_corpus(args, repo_root=repo_root)
    except (
        RegistryError,
        FetchError,
        SidecarError,
        SkillError,
        ManifestError,
        NormaliseError,
        SchemaError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _run_roadmap(*, repo_root: Path, out_dir: Path) -> list[Finding]:
    """Load, guard, and publish the roadmap. Returns the guards' own findings.

    Runs every roadmap guard before writing anything, so a `Severity.ERROR` finding
    here leaves `out_dir` exactly as it was. `load_roadmap` itself can raise
    `RoadmapError`, on a missing `roadmap/` directory or malformed YAML, which is not
    caught here; it propagates to `main`'s catch-all, since that too means nothing
    below has been written.
    """
    roadmap_dir = repo_root / _ROADMAP_DIR
    index, tracks = load_roadmap(roadmap_dir)

    findings: list[Finding] = []
    findings.extend(check_roadmap_track_ids(index, tracks))
    findings.extend(check_roadmap_reverse_index(roadmap_dir, index))
    findings.extend(check_roadmap_categories(tracks))
    findings.extend(check_roadmap_entry_ids(tracks))

    _report_roadmap(findings)
    if guard_failed(findings):
        return findings

    _write_roadmap(
        index,
        tracks,
        out_dir=out_dir,
        generated_at=_generated_at(),
        generator_commit=_generator_commit(),
    )
    print(f"Roadmap: published {len(index)} track(s) to {out_dir}.")
    return findings


def _write_roadmap(
    index: Sequence[RoadmapTrackRef],
    tracks: Mapping[str, RoadmapTrackContent],
    *,
    out_dir: Path,
    generated_at: str,
    generator_commit: str | None,
) -> None:
    """Write roadmap.json, one roadmap/<track>.json per index entry, and both roadmap
    schemas to a staging directory, then move all of them into `out_dir` in one pass.

    Mirrors `_publish`'s staging-then-move shape for the corpus half: everything here
    lands in a temporary directory first, so a `SchemaError` reading either roadmap
    schema, or any other failure partway through, leaves `out_dir` exactly as it was
    rather than with an index and some tracks published but not the rest (see the
    module docstring's "nothing publishes on failure" property).

    `generated_at` and `generator_commit` are computed once by the caller and reused
    identically across the index and every track document, rather than resolved
    again per document, so second-precision timestamps do not make one build look
    like several.
    """
    with tempfile.TemporaryDirectory(prefix="dfo_docs-roadmap-") as staging:
        staging_root = Path(staging)

        roadmap_index = RoadmapIndex(
            schema_version=ROADMAP_INDEX_SCHEMA_VERSION,
            generated_at=generated_at,
            generator_commit=generator_commit,
            tracks=tuple(index),
        )
        _write_json(
            _roadmap_index_json(roadmap_index), staging_root / _ROADMAP_INDEX_FILE
        )

        for ref in index:
            content = tracks[ref.id]
            track = RoadmapTrack(
                schema_version=ROADMAP_TRACK_SCHEMA_VERSION,
                generated_at=generated_at,
                generator_commit=generator_commit,
                track=content.track,
                categories=content.categories,
                entries=content.entries,
            )
            _write_json(_roadmap_track_json(track), staging_root / ref.file)

        (staging_root / _ROADMAP_INDEX_SCHEMA_FILE).write_bytes(
            _load_schema_bytes(_ROADMAP_INDEX_SCHEMA_FILE)
        )
        (staging_root / _ROADMAP_TRACK_SCHEMA_FILE).write_bytes(
            _load_schema_bytes(_ROADMAP_TRACK_SCHEMA_FILE)
        )

        _publish_roadmap(staging_root, out_dir=out_dir)


def _publish_roadmap(staging_root: Path, *, out_dir: Path) -> None:
    """Move the staged roadmap index, track documents, and both roadmap schemas into
    `out_dir`, replacing what was there.

    Nothing above this point in `_write_roadmap` has touched `out_dir`; every write
    lands in `staging_root`, discarded whole on failure. This is the only place a
    roadmap-write failure could still do damage, and it only runs once every roadmap
    file has been written successfully.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    track_dir = staging_root / _ROADMAP_DIR
    if track_dir.exists():
        dest_track_dir = out_dir / _ROADMAP_DIR
        if dest_track_dir.exists():
            shutil.rmtree(dest_track_dir)
        shutil.move(str(track_dir), str(dest_track_dir))

    shutil.move(
        str(staging_root / _ROADMAP_INDEX_FILE), str(out_dir / _ROADMAP_INDEX_FILE)
    )
    shutil.move(
        str(staging_root / _ROADMAP_INDEX_SCHEMA_FILE),
        str(out_dir / _ROADMAP_INDEX_SCHEMA_FILE),
    )
    shutil.move(
        str(staging_root / _ROADMAP_TRACK_SCHEMA_FILE),
        str(out_dir / _ROADMAP_TRACK_SCHEMA_FILE),
    )


def _write_json(payload: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _roadmap_index_json(index: RoadmapIndex) -> dict[str, object]:
    raw: dict[str, object] = {
        "schema_version": index.schema_version,
        "generated_at": index.generated_at,
        "generator_commit": index.generator_commit,
        "tracks": [_roadmap_track_ref_json(ref) for ref in index.tracks],
    }
    return {key: value for key, value in raw.items() if value is not None}


def _roadmap_track_ref_json(ref: RoadmapTrackRef) -> dict[str, object]:
    raw: dict[str, object] = {
        "id": ref.id,
        "label": ref.label,
        "description": ref.description,
        "file": ref.file,
    }
    return {key: value for key, value in raw.items() if value is not None}


def _roadmap_track_json(track: RoadmapTrack) -> dict[str, object]:
    raw: dict[str, object] = {
        "schema_version": track.schema_version,
        "generated_at": track.generated_at,
        "generator_commit": track.generator_commit,
        "track": track.track,
        "categories": [_roadmap_category_json(c) for c in track.categories],
        "entries": [_roadmap_entry_json(e) for e in track.entries],
    }
    return {key: value for key, value in raw.items() if value is not None}


def _roadmap_category_json(category: RoadmapCategory) -> dict[str, object]:
    return {"id": category.id, "label": category.label}


def _roadmap_entry_json(entry: RoadmapEntry) -> dict[str, object]:
    raw: dict[str, object] = {
        "id": entry.id,
        "title": entry.title,
        "description": entry.description,
        "categories": list(entry.categories) or None,
        "status": entry.status.value,
        "expected": entry.expected,
        "released_on": entry.released_on,
        "version": entry.version,
        "provenance": entry.provenance,
        "url": entry.url,
    }
    return {key: value for key, value in raw.items() if value is not None}


def _report_roadmap(findings: Sequence[Finding]) -> None:
    print("Roadmap findings:" if findings else "Roadmap findings: none")
    for finding in findings:
        location = f" ({finding.path})" if finding.path else ""
        print(f"  [{finding.severity.value}] {finding.message}{location}")


def _run_corpus(args: argparse.Namespace, *, repo_root: Path) -> int:
    """Publish the corpus and manifest.json. Returns 0 or 2; see `_run`."""
    sources = load_sources(repo_root / _SOURCES_FILE)
    hub = load_hub(repo_root / _HUB_FILE)
    disabled = {
        name: source.reason for name, source in sources.items() if not source.enabled
    }

    fetched_sources = {
        name: source
        for name, source in enabled_sources(sources).items()
        if source.kind in FETCHED_KINDS
    }

    with tempfile.TemporaryDirectory(prefix="dfo_docs-fetch-") as workdir:
        fetched = fetch_all(fetched_sources.values(), workdir=Path(workdir))

        findings: list[Finding] = []
        sidecars: dict[str, Sidecar] = {}
        for item in fetched:
            if item.source.kind is SourceKind.SKILL:
                findings.extend(check_internal_dir(item))
                findings.extend(check_skill_drift(item, load_skills(item)))
                continue
            sidecar = load_sidecar(item.repo_root, item.source)
            sidecars[item.source.name] = sidecar
            findings.extend(check_nav_drift(sidecar, item.source, item.repo_root))

        if guard_failed(findings):
            # A missing file would crash manifest.build_pages; stop here, before it is
            # ever called, so the report names every drifted source in one pass. The
            # roadmap has already published by the time this runs (see `_run`), so
            # this is a corpus-half failure: 2, not 1.
            _report(disabled=disabled, pages=(), findings=findings)
            return 2

        with tempfile.TemporaryDirectory(prefix="dfo_docs-stage-") as staging:
            # `staging_root` stands in for `--out` while the guards run. `Page.corpus_path`
            # is written as `corpus/<name>/<file>`, relative to wherever `corpus/` and
            # `manifest.json` sit side by side, which is `staging_root` here and `--out`
            # once published. `staging_corpus` is where build_pages physically writes.
            staging_root = Path(staging)
            staging_corpus = staging_root / _CORPUS_DIR
            staging_manifest = staging_root / _MANIFEST_FILE

            nav, pages = build_pages(
                sources,
                hub,
                fetched,
                repo_root=repo_root,
                hub_content_root=repo_root / _HUB_CONTENT_DIR,
                corpus_root=staging_corpus,
            )

            # One asset pass per fetched source, reusing the sidecar already loaded
            # above rather than reloading it (a skill source has none, and gets one
            # pass per root its skills are read from, each landing at the same corpus
            # directory its pages do), plus one for the hub's own content, which is
            # not itself a `Fetched` source and would otherwise never have its images
            # carried at all.
            for item in fetched:
                sidecar = sidecars.get(item.source.name)
                for root in (sidecar.docs_root,) if sidecar else skill_roots(item):
                    findings.extend(
                        copy_assets(
                            root,
                            staging_corpus / item.source.name,
                            source_name=item.source.name,
                        )
                    )
            findings.extend(
                copy_assets(
                    repo_root / _HUB_CONTENT_DIR,
                    staging_corpus / _HUB_CORPUS_NAME,
                    source_name=_HUB_CORPUS_NAME,
                )
            )

            manifest = Manifest(
                schema_version=SCHEMA_VERSION,
                generated_at=_generated_at(),
                generator_commit=_generator_commit(),
                nav=tuple(nav),
                pages=tuple(pages),
            )
            write_manifest(manifest, staging_manifest)
            (staging_root / _SCHEMA_DEST_FILE).write_bytes(
                _load_schema_bytes(_SCHEMA_DEST_FILE)
            )

            if not args.no_guards:
                findings.extend(
                    _run_guards(
                        manifest=manifest,
                        staging_root=staging_root,
                        staging_corpus=staging_corpus,
                    )
                )

            if not guard_failed(findings):
                _publish(staging_root, out_dir=args.out)

    _report(disabled=disabled, pages=pages, findings=findings)
    # The roadmap has already published by the time this line runs (see `_run`), so
    # a corpus-half failure here is 2, not 1: partial publish, not "nothing written".
    return 2 if guard_failed(findings) else 0


def _run_guards(
    *,
    manifest: Manifest,
    staging_root: Path,
    staging_corpus: Path,
) -> list[Finding]:
    findings: list[Finding] = []
    # check_directives resolves a page's corpus_path (e.g. "corpus/hub/index.md")
    # against staging_root, the directory corpus/ sits under, not staging_corpus,
    # which is corpus/ itself and would double that segment.
    findings.extend(check_directives(manifest.pages, corpus_root=staging_root))
    findings.extend(check_uniqueness(manifest))
    return findings


def _generated_at() -> str:
    """The current moment, UTC ISO 8601 with a `Z` suffix, second precision."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generator_commit() -> str | None:
    """dfo-docs's own checked-out commit, or `None` when git is unavailable.

    Resolved from the `dfo_docs` package's own location on disk via
    `importlib.resources`, the same way `_load_schema_bytes` finds package data, so
    this reports dfo-docs's checkout regardless of what `--repo-root` points at.
    `generator_commit` is provenance, omitted entirely from the published manifest
    (see `manifest.write_manifest`) rather than faked when it cannot be resolved, as
    is the case for an installed wheel with no git checkout around it; the build
    proceeds either way.
    """
    package_root = Path(str(resources.files("dfo_docs")))
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=package_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _publish(staging_root: Path, *, out_dir: Path) -> None:
    """Move the staged corpus, manifest, and schema into `out_dir`, replacing
    what was there.

    Nothing above this point in the corpus half has touched `out_dir`'s corpus,
    manifest, or manifest schema. Every corpus write up to here lands in a staging
    directory that is discarded on a corpus-half failure. This is the only place a
    failed corpus build could still do damage, and it only runs once every corpus
    finding has already been checked and none of them is an error. `out_dir` may
    already carry a freshly published roadmap by the time this runs (see `_run` and
    `_run_roadmap`): that publish is unconditional and independent of this one, and
    this function neither reads nor overwrites any of the roadmap paths.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    corpus_dest = out_dir / _CORPUS_DIR
    manifest_dest = out_dir / _MANIFEST_FILE
    schema_dest = out_dir / _SCHEMA_DEST_FILE

    if corpus_dest.exists():
        shutil.rmtree(corpus_dest)
    shutil.move(str(staging_root / _CORPUS_DIR), str(corpus_dest))
    shutil.move(str(staging_root / _MANIFEST_FILE), str(manifest_dest))
    shutil.move(str(staging_root / _SCHEMA_DEST_FILE), str(schema_dest))


def _report(
    *,
    disabled: Mapping[str, str | None],
    pages: Sequence[Page],
    findings: Sequence[Finding],
) -> None:
    print("dfo-docs build report")

    if disabled:
        print("\nDisabled sources:")
        for name, reason in disabled.items():
            print(f"  {name}: {reason or 'no reason given'}")

    if pages:
        counts = Counter(page.kind.value for page in pages)
        print("\nPages by kind:")
        for kind in sorted(counts):
            print(f"  {kind}: {counts[kind]}")
        print(f"  total: {len(pages)}")

    print("\nFindings:" if findings else "\nFindings: none")
    for finding in findings:
        location = f" ({finding.path})" if finding.path else ""
        print(f"  [{finding.severity.value}] {finding.message}{location}")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dfo-docs-build",
        description="Fetch, normalise, and publish the aggregated documentation corpus.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(),
        help=(
            "Directory to publish roadmap.json, roadmap/, both roadmap schemas, "
            "corpus/, manifest.json, and manifest.schema.json into (default: the "
            "current directory)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help=(
            "Directory holding sources.yaml, hub.yaml, roadmap/, and "
            "content/hub (default: the current directory). Point it at a copy to try "
            "a registry change without editing the real one."
        ),
    )
    parser.add_argument(
        "--no-guards",
        action="store_true",
        help=(
            "Skip the directive and uniqueness guards, for local iteration. The "
            "nav-drift check always runs regardless; it is not a guard you can opt out of."
        ),
    )
    return parser.parse_args(argv)
