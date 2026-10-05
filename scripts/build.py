#!/usr/bin/env python3
"""Entry point: `python scripts/build.py`.

The package lives at `src/dfo_docs/`, not under `scripts/`, so that it is importable from an
installed environment (`pip install -e .`) without path surgery. This script exists so the "works
from a fresh clone with no install step" promise holds literally, which means it has to put
`src/` on `sys.path` itself before it can import dfo_docs.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The repository's src/ directory, not scripts/, is where dfo_docs/ lives. See the module
# docstring.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

try:
    from dfo_docs.cli import main
except ImportError as exc:
    raise SystemExit(
        f"cannot import dfo_docs from {Path(__file__).resolve().parent.parent / 'src'}. "
        f"Run this script from a checkout of the repository, or install it with "
        f"`uv pip install -e .` and run `dfo-docs-build`. ({exc})"
    ) from exc


if __name__ == "__main__":
    raise SystemExit(main())
