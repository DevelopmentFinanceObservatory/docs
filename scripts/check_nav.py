#!/usr/bin/env python3
"""Runs the nav-drift checks standalone, inside a source repository before opening a PR.

`dfo_docs.guards.check_nav_drift` is the same check `dfo_docs.cli` runs during the
aggregated build, once a source has already been fetched. This script runs it against
a local checkout directly instead, with no fetch, no git clone, and no network, so an
author can catch a stale nav entry (or a page the nav no longer reaches) before opening
a PR, rather than finding out days later from a failed dfo-docs build naming their
repository.

Pairs with `lychee --offline docs/`. Lychee checks whether links resolve, this checks
whether the nav itself is complete and accurate, and between them that is everything
`check_nav_drift` and a link checker can see without dfo-docs fetching anything.

Usage:
    python check_nav.py [REPO_ROOT]

REPO_ROOT defaults to the current directory, so the common case is running this from
the source repository's own root.
"""

from __future__ import annotations

import sys
from pathlib import Path

# dfo_docs lives under src/, not under scripts/ (see scripts/build.py's docstring for
# why). This script runs from wherever dfo-docs is checked out, against some *other*
# repository's working tree, so it needs the same sys.path insertion build.py does
# before it can import dfo_docs.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfo_docs.guards import check_nav_drift, guard_failed
from dfo_docs.models import Source
from dfo_docs.sidecar import SidecarError, load_sidecar


def main(argv: list[str] | None = None) -> int:
    """Check one repository's sidecar nav for drift. Returns the process exit code."""
    args = sys.argv[1:] if argv is None else argv
    repo_root = Path(args[0]).resolve() if args else Path.cwd()

    # No registry row exists for a repository that hasn't been added to dfo-docs yet
    # (or is being checked before it is), so this stands in a minimal one. Only
    # `name` and `repo` are required, and both only ever surface in error messages or
    # as a title fallback here.
    stub_source = Source(name=repo_root.name, repo=repo_root.name)

    try:
        sidecar = load_sidecar(repo_root, stub_source)
    except SidecarError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    findings = check_nav_drift(sidecar, stub_source, repo_root)

    if not findings:
        print(f"{sidecar.title!r}: nav is complete, no drift found")
        return 0

    for finding in findings:
        print(f"[{finding.severity.value}] {finding.message}")

    return 1 if guard_failed(findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
