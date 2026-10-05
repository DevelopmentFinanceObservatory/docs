"""Copy a source's assets into the corpus alongside its markdown.

`manifest.build_pages` writes each nav-named markdown file to
`corpus/<source>/<file>`, where `<file>` is relative to the sidecar's `docs_root`.
`copy_assets` walks that same `docs_root` and copies every other file worth
publishing (images) to the matching relative location under `dest_root`, so a
page's own relative reference to an image still resolves once both land in the
corpus.

Markdown is left alone here; `manifest.py` already reads, normalises, and writes
it. Everything else that is not an image is reported and skipped rather than
copied, which is how the allowlist widens later, on evidence rather than
guesswork.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from dfo_docs.guards import Finding, Severity

# Images only. The corpus commits to carrying exactly these suffixes; anything else in
# a source's docs tree is skipped with a warning naming it.
IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif", ".ico"}
)

# The design promises images beside pages and one `assets/` folder per package, and
# nothing wider is evidenced. Fonts are theme chrome whose CSS this build excludes.

# Over this, an image still copies, with a warning naming its source. Nothing fails a
# build over a large image.
_DEFAULT_MAX_ASSET_BYTES = 1_000_000

# SVG can carry script, and it runs when a browser navigates directly to the
# asset's public URL (an <img> reference alone would not execute it, but that is
# not why this is safe). It is accepted anyway because the corpus origin has no
# authenticated surface: the worst case is defacement, not credential theft.


def copy_assets(docs_root: Path, dest_root: Path, *, source_name: str) -> list[Finding]:
    """Copy every allowlisted asset under `docs_root` to the same relative path under `dest_root`.

    Walks `docs_root`, skipping markdown (left for `manifest.py`) and never
    descending into a symlinked directory, so a committed symlink cycle in a
    source's docs tree cannot hang the build. Every other file is checked
    against the image allowlist; a suffix outside it is skipped and reported as
    a `Severity.WARNING` naming the suffix, since the allowlist widens later on
    that evidence rather than on guesswork.

    An allowlisted file's path is resolved once, and the resolved path is
    required to stay under `docs_root` (also resolved once), following the same
    `Path.is_relative_to` pattern `normalise.expand_transclusion` uses rather
    than a string-prefix comparison. A file that resolves outside is skipped and
    reported as a `Severity.ERROR` naming `source_name` and the path. Only the
    already-resolved path drives the copy, never a path re-derived afterwards.

    A copied file over `guards._DEFAULT_MAX_ASSET_BYTES` (1MB) still copies, but
    produces a `Severity.WARNING`. Parent directories under `dest_root` are
    created only where a file actually lands.

    Args:
        docs_root: The source's own docs root, as `Sidecar.docs_root` resolves it.
        dest_root: Where assets land, matching the corpus layout for that source's
            markdown (`corpus_root / source.name`, or `corpus_root / "hub"`).
        source_name: Named in every containment-failure finding.

    Returns:
        One `Finding` per skipped, oversized, or contained-failure file. Empty
        when every file copied cleanly.
    """
    findings: list[Finding] = []
    resolved_root = docs_root.resolve()

    for candidate in _walk_files(docs_root):
        rel = candidate.relative_to(docs_root)
        suffix = candidate.suffix.lower()

        if suffix == ".md":
            continue

        if suffix not in IMAGE_SUFFIXES:
            findings.append(
                Finding(
                    Severity.WARNING,
                    f"{source_name!r}: skipping {rel.as_posix()!r}, suffix "
                    f"{suffix or '(none)'!r} is not in the image allowlist",
                    path=rel.as_posix(),
                )
            )
            continue

        resolved = candidate.resolve()
        if not resolved.is_relative_to(resolved_root):
            findings.append(
                Finding(
                    Severity.ERROR,
                    f"{source_name!r}: asset {rel.as_posix()!r} resolves outside "
                    f"its docs root ({resolved})",
                    path=rel.as_posix(),
                )
            )
            continue

        size = resolved.stat().st_size
        if size > _DEFAULT_MAX_ASSET_BYTES:
            findings.append(
                Finding(
                    Severity.WARNING,
                    f"{source_name!r}: {rel.as_posix()!r} is {size:,} bytes, over "
                    f"the {_DEFAULT_MAX_ASSET_BYTES:,} byte asset guard threshold",
                    path=rel.as_posix(),
                )
            )

        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(resolved, dest)

    return findings


def _walk_files(docs_root: Path) -> list[Path]:
    """Every file under `docs_root`, in a stable order, without following a directory symlink.

    `os.walk`'s default `followlinks=False` already skips descending into a
    symlinked directory, which is what keeps a committed symlink cycle from
    hanging this walk before any per-file check in `copy_assets` runs.
    """
    files: list[Path] = []
    for current_dir, dirnames, filenames in os.walk(docs_root):
        dirnames.sort()
        files.extend(Path(current_dir) / filename for filename in sorted(filenames))
    return files
