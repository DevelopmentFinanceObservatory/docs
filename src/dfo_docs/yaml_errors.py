"""Render a PyYAML parse error consistently, wherever a YAML file is read.

registry.py, roadmap.py, sidecar.py, and skills.py each read a different YAML file into
their own domain-specific error (`RegistryError`, `RoadmapError`, `SidecarError`,
`SkillError`), but all four want to name exactly the same thing when PyYAML rejects
one, the parser's own problem and location, not the "<unicode string>" placeholder
PyYAML prints for a file it never saw a name for.
"""

from __future__ import annotations

import yaml


def describe_yaml_error(exc: yaml.YAMLError) -> str:
    """Render a YAML parse error's own problem and location."""
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or str(exc)
    if mark is not None:
        return f"{problem} (line {mark.line + 1}, column {mark.column + 1})"
    return problem
