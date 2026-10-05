"""Guards are checks that turn silent corpus damage into a build failure.

Each check is a pure function that returns a list of `Finding`; nothing here calls
`sys.exit` or raises to stop the build. `guard_failed` is the single place that turns a
batch of findings into a pass/fail decision, so `cli.py` can run every check, report
every problem in one pass, and fail once at the end. `fetch.fetch_all` already uses the
same shape for a source repository's failures.

`check_directives` fails on a mkdocstrings `::: ` directive leaking into a carried
page. `check_uniqueness` fails on a duplicate page id, page path, `corpus_path`, or nav
node id, the one place the whole assembled manifest exists at once to check it.

Link and asset references are lychee's job. `build.yml` runs
`lychee --config lychee.toml` over the staged corpus before the publish step, offline,
excluding nothing, so it resolves every local target rather than the image subset a
guard here could classify without guessing.

`check_roadmap_track_ids`, `check_roadmap_reverse_index`, `check_roadmap_categories`,
and `check_roadmap_entry_ids` are the roadmap's own build guards, filling the gap
`dfo_docs.roadmap`'s module docstring names: three rules that span more than one
roadmap document, plus the reverse-index rule, which catches a stray track file the
index does not list. Each of these
takes `roadmap.load_roadmap`'s own return shape (`RoadmapTrackRef` and
`RoadmapTrackContent`) directly, rather than the published `RoadmapIndex` /
`RoadmapTrack` envelopes `cli.py` only builds after these pass. `check_roadmap_entry_ids`
and `check_roadmap_categories` are each written once against every track's entries at
once, which is what lets one rule catch both the within-file case (two entries in the
same track file, or one entry naming a category its own track omits) and the
across-file case (an id reused by a different track's file) without a second version
of either rule.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from dfo_docs.models import (
    Manifest,
    NavNode,
    Page,
    PageKind,
    RoadmapTrackRef,
    Sidecar,
    Source,
)
from dfo_docs.roadmap import RoadmapTrackContent
from dfo_docs.sidecar import nav_source_path

_FENCE_RE = re.compile(r"^\s*```")
_DIRECTIVE_PREFIX = "::: "
_ROADMAP_INDEX_STEM = "index"


class Severity(StrEnum):
    """How much a `Finding` matters. Only `ERROR` fails the build; see `guard_failed`."""

    WARNING = "warning"
    """Worth a human's attention but not worth blocking the build over."""

    ERROR = "error"
    """Fails the build."""


@dataclass(frozen=True)
class Finding:
    """One thing a guard noticed. `path` and `line` are context, not always present."""

    severity: Severity
    message: str
    path: str | None = None
    line: int | None = None


def check_nav_drift(sidecar: Sidecar, source: Source, repo_root: Path) -> list[Finding]:
    """Fail on a navigated file that does not exist; warn on one the nav omits.

    A source's sidecar can navigate a file that was renamed or deleted upstream.
    Without this check, that surfaces only as a bare `FileNotFoundError` once
    `manifest.build_pages` tries to read it. Running this before that point, per
    source, names the missing file while it can still be attributed to the source that
    caused it.

    Reports both directions. A file `sidecar.nav` points at that does not exist under
    `sidecar.docs_root` is a `Severity.ERROR`, since manifest.py would otherwise crash
    reading it. A file that exists under `sidecar.docs_root` but that no nav entry
    reaches is a `Severity.WARNING`, untidy rather than broken, since it may still be
    linked from another page's own prose.

    A file `source.exclude` held back is silent in both directions. It is absent from
    `sidecar.nav` by design, so warning that the nav does not reach it would report the
    registry's own decision back as drift on every build, and it is never read, so its
    disappearing upstream cannot crash anything here.

    `source` and `repo_root` name the finding. A fetch clones a source into a
    temporary directory that differs on every run and means nothing to the person who
    has to go fix it, so every reported path is relative to `repo_root` instead, and
    `source.repo` (`"owner/name"`) says which repository it belongs to.
    """
    navigated = {entry.file for entry in sidecar.nav}
    existing = {
        path.relative_to(sidecar.docs_root).as_posix()
        for path in sidecar.docs_root.rglob("*.md")
    } - set(sidecar.excluded)

    findings: list[Finding] = []
    for file in sorted(navigated - existing):
        repo_relative = nav_source_path(sidecar, repo_root, file)
        findings.append(
            Finding(
                Severity.ERROR,
                f"{sidecar.title!r} navigates {repo_relative!r}, which does not "
                f"exist in {source.repo}",
                path=repo_relative,
            )
        )
    for file in sorted(existing - navigated):
        repo_relative = nav_source_path(sidecar, repo_root, file)
        findings.append(
            Finding(
                Severity.WARNING,
                f"{sidecar.title!r} does not navigate {repo_relative!r}, which "
                f"exists in {source.repo}",
                path=repo_relative,
            )
        )
    return findings


def check_directives(pages: Sequence[Page], *, corpus_root: Path) -> list[Finding]:
    """Fail on any carried page containing a line beginning `"::: "`.

    That is mkdocstrings syntax; a page whose content comes from introspecting
    installed Python does not render from its own text, and a repository doing that
    belongs in the self-published tier rather than the aggregated one.

    Only "carried" pages are checked (`kind != PageKind.EXTERNAL` and `corpus_path`
    set), since an external page has no corpus file to read. Each `page.corpus_path`
    is read from disk under `corpus_root`. A `::: ` line inside a fenced code block is
    not flagged.
    """
    findings: list[Finding] = []

    for page in pages:
        if page.kind is PageKind.EXTERNAL or page.corpus_path is None:
            continue

        file_path = corpus_root / page.corpus_path
        text = file_path.read_text()

        in_fence = False
        for lineno, line in enumerate(text.split("\n"), start=1):
            if _FENCE_RE.match(line):
                in_fence = not in_fence
                continue
            if not in_fence and line.startswith(_DIRECTIVE_PREFIX):
                findings.append(
                    Finding(
                        Severity.ERROR,
                        f"mkdocstrings directive found in a carried page: "
                        f"{file_path}:{lineno}",
                        path=str(file_path),
                        line=lineno,
                    )
                )

    return findings


def check_uniqueness(manifest: Manifest) -> list[Finding]:
    """Fail on any duplicate page id, page path, `corpus_path`, or nav node id.

    This is the one place the whole assembled manifest exists at once, so it is the
    only place a true collision guarantee can be made; `Source.path`'s sidecar
    assertion (see `sidecar.load_sidecar`) is a consistency check on one row at a
    time and cannot substitute for it. Each duplicate is reported once, naming both
    claimants.

    The hub home page's path is the empty string, and it is legal exactly once, the
    same as any other path; it is not special-cased away, it simply is not flagged
    unless something else also claims it.
    """
    findings: list[Finding] = []
    findings.extend(
        _uniqueness_findings(
            "page id",
            ((page.id, _describe_page(page)) for page in manifest.pages),
        )
    )
    findings.extend(
        _uniqueness_findings(
            "page path",
            ((page.path, _describe_page(page)) for page in manifest.pages),
        )
    )
    findings.extend(
        _uniqueness_findings(
            "corpus_path",
            (
                (page.corpus_path, _describe_page(page))
                for page in manifest.pages
                if page.corpus_path is not None
            ),
        )
    )
    findings.extend(_uniqueness_findings("nav node id", _nav_node_claims(manifest.nav)))
    return findings


def _describe_page(page: Page) -> str:
    return f"page {page.id!r} at {page.path!r}"


def _nav_node_claims(nodes: Sequence[NavNode]) -> list[tuple[str, str]]:
    claims: list[tuple[str, str]] = []
    for node in nodes:
        claims.append((node.id, f"nav node {node.title!r} ({node.kind.value})"))
        claims.extend(_nav_node_claims(node.children))
    return claims


def _uniqueness_findings(
    label: str, claims: Iterable[tuple[str, str]]
) -> list[Finding]:
    claimants: dict[str, list[str]] = {}
    for value, descriptor in claims:
        claimants.setdefault(value, []).append(descriptor)
    return [
        Finding(
            Severity.ERROR,
            f"duplicate {label} {value!r}: {' and '.join(descriptors)}",
        )
        for value, descriptors in claimants.items()
        if len(descriptors) > 1
    ]


def check_roadmap_track_ids(
    index: Sequence[RoadmapTrackRef],
    tracks: Mapping[str, RoadmapTrackContent],
) -> list[Finding]:
    """Fail when an index-listed track's own document disagrees on its id.

    `roadmap.load_roadmap` keys `tracks` by the index's own track id, read from
    `roadmap/index.yaml`, rather than by the id each document declares in its own
    `track` field, so a document whose `track` does not match the index entry that
    points at it loads without error and would otherwise publish silently under the
    wrong id. This is the one place both are read together to catch that.
    """
    findings: list[Finding] = []
    for ref in index:
        content = tracks.get(ref.id)
        if content is None or content.track == ref.id:
            continue
        findings.append(
            Finding(
                Severity.ERROR,
                f"roadmap/index.yaml lists track {ref.id!r} at {ref.file!r}, but "
                f"that document's own track field is {content.track!r}",
                path=ref.file,
            )
        )
    return findings


def check_roadmap_reverse_index(
    roadmap_dir: Path, index: Sequence[RoadmapTrackRef]
) -> list[Finding]:
    """Fail on a roadmap/<id>.yaml file on disk that roadmap/index.yaml omits.

    `load_roadmap` only ever reads a file the index names, so a track file left
    behind by a rename, or a new one added before its own index row, would
    otherwise sit on disk, unread and unpublished, with no error at all. Every
    `.yaml` file directly under `roadmap_dir` other than `index.yaml` itself is
    expected to have a matching index entry.
    """
    index_ids = {ref.id for ref in index}
    on_disk_ids = {
        path.stem
        for path in roadmap_dir.glob("*.yaml")
        if path.stem != _ROADMAP_INDEX_STEM
    }
    return [
        Finding(
            Severity.ERROR,
            f"roadmap/{track_id}.yaml exists on disk, but roadmap/index.yaml does "
            "not list it",
            path=f"roadmap/{track_id}.yaml",
        )
        for track_id in sorted(on_disk_ids - index_ids)
    ]


def check_roadmap_categories(
    tracks: Mapping[str, RoadmapTrackContent],
) -> list[Finding]:
    """Fail on an entry naming a category its own track does not declare.

    A track document's own `categories` array is validated on its own already; what
    no single-document schema can express is that a value inside an
    `entries[].categories` is drawn from that same document's own `categories` list,
    since that is a same-document consistency check rather than a fixed value set.
    Checked once per track's own entries against that track's own categories, since
    an entry names no other track's vocabulary.
    """
    findings: list[Finding] = []
    for content in tracks.values():
        declared = {category.id for category in content.categories}
        for entry in content.entries:
            for category_id in entry.categories:
                if category_id in declared:
                    continue
                findings.append(
                    Finding(
                        Severity.ERROR,
                        f"entry {entry.id!r} in roadmap/{content.track}.yaml names "
                        f"category {category_id!r}, which that track does not "
                        "declare in its own categories",
                        path=f"roadmap/{content.track}.yaml",
                    )
                )
    return findings


def check_roadmap_entry_ids(
    tracks: Mapping[str, RoadmapTrackContent],
) -> list[Finding]:
    """Fail on an entry id used more than once anywhere in the roadmap.

    The site's vote store keys on an entry's id alone, so an item that moves from
    one track to another must keep that id, unscoped to any one track. Collecting
    every track's entries into one set of claims before checking uniqueness, rather
    than checking one track's own file at a time, is what catches both a duplicate
    hard-coded twice inside a single track's file and one reused across two
    different teams' files, with the one rule this reuses from `check_uniqueness`.
    """
    claims = (
        (entry.id, f"roadmap/{content.track}.yaml")
        for content in tracks.values()
        for entry in content.entries
    )
    return _uniqueness_findings("roadmap entry id", claims)


def guard_failed(findings: Iterable[Finding]) -> bool:
    """Return whether any finding is severe enough to fail the build.

    Only `Severity.ERROR` fails; `INFO` and `WARNING` do not. Call this once against
    the combined findings from every check, so the build fails at most once per run no
    matter how many checks found something.
    """
    return any(finding.severity is Severity.ERROR for finding in findings)
