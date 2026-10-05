"""Walk a `kind: skill` source's tree into the skills it publishes.

A skill is a directory under the source's docs root that holds a `SKILL.md`, whose YAML front
matter carries `name` and `description`, and optionally a `references/` directory of Markdown
files. `load_skills` returns one `Skill` per such directory, sorted by directory name, and
leaves out any directory whose name starts with `_`, which is how the authoring template stays
unpublished. `manifest.py` turns each skill into a `skill` page and each reference file into a
child page; `skill_page_text` writes the short header that opens each skill page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from dfo_docs.guards import Finding, Severity
from dfo_docs.models import Fetched
from dfo_docs.normalise import FRONTMATTER_RE
from dfo_docs.sidecar import resolve_contained, title_from_text
from dfo_docs.yaml_errors import describe_yaml_error

SKILL_FILE = "SKILL.md"
REFERENCES_DIR = "references"

# A sentence ends at `.`, `!` or `?` followed by whitespace or the end of the text, so `0.7%`
# and `e.g.,` do not end one.
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")
_H1_LINE_RE = re.compile(r"#(?!#)\s+\S")


class SkillError(ValueError):
    """A skill directory has no `SKILL.md`, or its front matter is missing or malformed."""


@dataclass(frozen=True)
class Reference:
    """One file in a skill's `references/` directory."""

    file: str
    """Docs-root-relative, for example `oda-measures/references/flow-types.md`."""
    title: str
    """The file's first H1, or a sentence-case title from its filename."""


@dataclass(frozen=True)
class Skill:
    """One published skill, read from its directory under the source's docs root."""

    directory: str
    name: str
    description: str
    references: tuple[Reference, ...]

    @property
    def file(self) -> str:
        """The docs-root-relative path of the skill's `SKILL.md`."""
        return f"{self.directory}/{SKILL_FILE}"


def load_skills(fetched: Fetched) -> tuple[Skill, ...]:
    """Read every skill under `fetched.docs_root`, sorted by directory name.

    The docs root, every skill directory, every `SKILL.md` and every reference file must
    resolve inside the checkout (the docs root inside the repository, the rest inside
    the docs root), checked before anything under it is read, so a committed symlink
    cannot publish a file from elsewhere on the build machine.

    Raises:
        SkillError: a path resolves outside its root, a directory not starting with `_`
            has no `SKILL.md`, or a `SKILL.md` has no front matter, front matter that
            does not parse, or no string `name` or `description`. The message names the
            path relative to the source repository.
    """
    docs_root = fetched.docs_root
    _contain(fetched, docs_root, root=fetched.repo_root)
    directories = sorted(
        path
        for path in docs_root.iterdir()
        if path.is_dir() and not path.name.startswith("_")
    )
    skills = []
    for directory in directories:
        _contain(fetched, directory, root=docs_root)
        skill_file = directory / SKILL_FILE
        if not skill_file.is_file():
            raise SkillError(
                f"{fetched.source.name!r}: {_repo_path(fetched, directory)} has no "
                f"{SKILL_FILE}"
            )
        _contain(fetched, skill_file, root=docs_root)
        name, description = _read_front_matter(fetched, skill_file)
        skills.append(
            Skill(
                directory=directory.name,
                name=name,
                description=description,
                references=_references(fetched, directory),
            )
        )
    return tuple(skills)


def check_skill_drift(fetched: Fetched, skills: tuple[Skill, ...]) -> list[Finding]:
    """Warn on each Markdown file under the docs root that no skill publishes.

    A skill publishes its `SKILL.md` and its `references/*.md`. Anything else, such as a
    Markdown file nested deeper under `references/` or one beside `SKILL.md`, is left out
    of the corpus, and this names it. Directories starting with `_` are skipped.
    """
    published = {skill.file for skill in skills}
    published.update(ref.file for skill in skills for ref in skill.references)
    findings = []
    for path in sorted(fetched.docs_root.rglob("*.md")):
        rel = path.relative_to(fetched.docs_root)
        if rel.parts[0].startswith("_") or rel.as_posix() in published:
            continue
        findings.append(
            Finding(
                Severity.WARNING,
                f"{fetched.source.name!r}: {rel.as_posix()} is not a SKILL.md or a "
                "references/*.md file, so no page publishes it",
                path=_repo_path(fetched, path),
            )
        )
    return findings


def skill_lead(description: str) -> str:
    """The description's first sentence, or the whole description if it has no sentence end."""
    text = " ".join(description.split())
    match = _SENTENCE_END_RE.search(text)
    return text[: match.end()] if match else text


def skill_page_text(text: str, skill: Skill, *, install_link: str) -> str:
    """`SKILL.md`'s text with the generated header inserted after its front matter.

    The header is an H1, the description's first sentence as a lead, and a line linking to
    `install_link`. When the body already opens with an H1, that H1 is kept and the lead
    follows it; otherwise the header opens with `# <name>`. Every skill page therefore
    opens with exactly one H1. The front matter and the rest of the body are unchanged.
    """
    match = FRONTMATTER_RE.match(text)
    front = text[: match.end()] if match else ""
    body = text[len(front) :].lstrip("\n")
    first_line, _, rest = body.partition("\n")
    if _H1_LINE_RE.match(first_line):
        title, rest = first_line, rest.lstrip("\n")
    else:
        title, rest = f"# {skill.name}", body
    install = (
        f"To load this skill in your own agent, see "
        f"[Use skills in your own agent]({install_link})."
    )
    header = "\n\n".join((title, skill_lead(skill.description), install))
    return f"{front}\n{header}\n\n{rest}"


def _read_front_matter(fetched: Fetched, skill_file: Path) -> tuple[str, str]:
    location = _repo_path(fetched, skill_file)
    match = FRONTMATTER_RE.match(skill_file.read_text())
    if match is None:
        raise SkillError(f"{location}: no YAML front matter")
    try:
        data = yaml.safe_load(match.group("body"))
    except yaml.YAMLError as exc:
        raise SkillError(f"{location}: {describe_yaml_error(exc)}") from exc
    if not isinstance(data, dict):
        raise SkillError(f"{location}: front matter is not a mapping")
    fields = []
    for key in ("name", "description"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SkillError(f"{location}: front matter has no {key!r}")
        fields.append(value.strip())
    name, description = fields
    return name, description


def _references(fetched: Fetched, directory: Path) -> tuple[Reference, ...]:
    references = []
    for path in sorted((directory / REFERENCES_DIR).glob("*.md")):
        _contain(fetched, path, root=fetched.docs_root)
        references.append(
            Reference(
                file=path.relative_to(fetched.docs_root).as_posix(),
                title=title_from_text(path.read_text(), path.stem),
            )
        )
    return tuple(references)


def _contain(fetched: Fetched, path: Path, *, root: Path) -> None:
    resolve_contained(
        path,
        root=root,
        error=f"{fetched.source.name!r}: {_repo_path(fetched, path)}",
        error_type=SkillError,
    )


def _repo_path(fetched: Fetched, path: Path) -> str:
    return PurePosixPath(path.relative_to(fetched.repo_root)).as_posix()
