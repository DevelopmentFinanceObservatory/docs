"""Walk a `kind: skill` source's tree into the skills it publishes.

A skill is a directory that holds a `SKILL.md`, whose YAML front matter carries `name` and
`description`, and optionally a `references/` directory of Markdown files. A source has one or
two roots of such directories: its docs root, whose skills are offered for install, and its
`internal_dir`, whose skills are published and not offered. `load_skills` returns one `Skill`
per directory under either root and leaves out any directory whose name starts with `_`. A
`categories.yaml` in the docs root, when there is one, files skills under `sources` or under a
domain, and sets the order they come back in. `manifest.py` turns each skill into a `skill`
page and each reference file into a child page, and groups the nav by category;
`skill_page_text` writes the short header that opens each skill page. A skill from the docs
root ships: `write_skill_bundle` zips its source files for download, and its header links to
the zip.
"""

from __future__ import annotations

import re
import zipfile
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
CATEGORIES_FILE = "categories.yaml"
_SOURCES_KEY = "sources"
_DOMAINS_KEY = "domains"

# A sentence ends at `.`, `!` or `?` followed by whitespace or the end of the text, so `0.7%`
# and `e.g.,` do not end one.
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")
_H1_LINE_RE = re.compile(r"#(?!#)\s+\S")
# Every bundle entry carries this timestamp (the earliest a zip can hold) and this mode (a
# regular file, `rw-r--r--`), so a bundle's bytes depend only on the files it holds.
_BUNDLE_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_BUNDLE_MODE = 0o100644
_ZIP_CREATED_ON_UNIX = 3


class SkillError(ValueError):
    """A skill directory has no `SKILL.md`, its front matter is missing or malformed, or
    `categories.yaml` cannot be read."""


@dataclass(frozen=True)
class Reference:
    """One file in a skill's `references/` directory."""

    file: str
    """Relative to the skill's root, for example `oda-measures/references/flow-types.md`."""
    title: str
    """The file's first H1, or a sentence-case title from its filename."""


@dataclass(frozen=True)
class Skill:
    """One published skill, read from its directory under one of the source's roots."""

    directory: str
    name: str
    description: str
    references: tuple[Reference, ...]
    root: Path
    """The directory the skill's own directory sits in: the source's docs root or its
    `internal_dir`. `file` and each reference's `file` are relative to it."""
    ships: bool
    """Whether the skill is offered for install, which is whether `root` is the docs root."""
    category: tuple[str, ...] = ()
    """The headings `categories.yaml` files the skill under, outermost first: `("sources",)`
    or `("domains", "sovereign-debt")`. Empty when the file leaves the skill out."""

    @property
    def file(self) -> str:
        """The path of the skill's `SKILL.md`, relative to `root`."""
        return f"{self.directory}/{SKILL_FILE}"


def skill_roots(fetched: Fetched) -> tuple[Path, ...]:
    """The directories `load_skills` reads skills from: the docs root, then the source's
    `internal_dir` when the row names one and the checkout has it."""
    internal_root = _internal_root(fetched)
    if internal_root is None or not internal_root.is_dir():
        return (fetched.docs_root,)
    return (fetched.docs_root, internal_root)


def check_internal_dir(fetched: Fetched) -> list[Finding]:
    """Warn when the source's row names an `internal_dir` the checkout lacks.

    The build then reads the docs root alone, so a skill expected under `internal_dir`
    gets no page.
    """
    internal_root = _internal_root(fetched)
    if internal_root is None or internal_root.is_dir():
        return []
    return [
        Finding(
            Severity.WARNING,
            f"{fetched.source.name!r}: internal_dir {fetched.source.internal_dir!r} is "
            "not in the checkout, so no skill is read from it",
            path=fetched.source.internal_dir,
        )
    ]


def load_skills(fetched: Fetched) -> tuple[Skill, ...]:
    """Read every skill under the source's roots, which `skill_roots` names.

    Skills that `categories.yaml` leaves out come first, sorted by directory name, and the
    rest follow in the file's order, so each category's skills sit together. Without the
    file every skill is left out, and the order is by directory name.

    Each root, every skill directory, every `SKILL.md` and every reference file must
    resolve inside the checkout (a root inside the repository, the rest inside their
    root), checked before anything under it is read, so a committed symlink cannot
    publish a file from elsewhere on the build machine.

    Raises:
        SkillError: a path resolves outside its root, a directory not starting with `_`
            has no `SKILL.md`, two roots hold a directory of the same name, a `SKILL.md`
            has no front matter, front matter that does not parse, or no string `name`
            or `description`, or `categories.yaml` does not parse, is not the shape
            `_read_categories` reads, or lists a skill twice. The message names the path
            relative to the source repository.
    """
    for root in skill_roots(fetched):
        _contain(fetched, root, root=fetched.repo_root)
    categories = _read_categories(fetched)
    skills: dict[str, Skill] = {}
    for root in skill_roots(fetched):
        for directory in root.iterdir():
            if not directory.is_dir() or directory.name.startswith("_"):
                continue
            if directory.name in skills:
                first = skills[directory.name].root / directory.name
                raise SkillError(
                    f"{fetched.source.name!r}: {_repo_path(fetched, first)} and "
                    f"{_repo_path(fetched, directory)} are both skill "
                    f"{directory.name!r}"
                )
            _contain(fetched, directory, root=root)
            skill_file = directory / SKILL_FILE
            if not skill_file.is_file():
                raise SkillError(
                    f"{fetched.source.name!r}: {_repo_path(fetched, directory)} has no "
                    f"{SKILL_FILE}"
                )
            _contain(fetched, skill_file, root=root)
            name, description = _read_front_matter(fetched, skill_file)
            skills[directory.name] = Skill(
                directory=directory.name,
                name=name,
                description=description,
                references=_references(fetched, directory, root=root),
                root=root,
                ships=root == fetched.docs_root,
                category=categories.get(directory.name, ()),
            )
    position = {name: index for index, name in enumerate(categories)}
    return tuple(
        sorted(
            skills.values(),
            key=lambda skill: (position.get(skill.directory, -1), skill.directory),
        )
    )


def check_skill_drift(fetched: Fetched, skills: tuple[Skill, ...]) -> list[Finding]:
    """Warn on each Markdown file under the source's roots that no skill publishes.

    A skill publishes its `SKILL.md` and its `references/*.md`. Anything else, such as a
    Markdown file nested deeper under `references/` or one beside `SKILL.md`, is left out
    of the corpus, and this names it. Directories starting with `_` are skipped.
    """
    published = {skill.root / skill.file for skill in skills}
    published.update(
        skill.root / reference.file
        for skill in skills
        for reference in skill.references
    )
    findings = []
    for root in skill_roots(fetched):
        for path in sorted(root.rglob("*.md")):
            rel = path.relative_to(root)
            if rel.parts[0].startswith("_") or path in published:
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


def write_skill_bundle(skill: Skill, *, dest_dir: Path) -> Path:
    """Zip the skill's source files into `dest_dir/<directory>.zip` and return that path.

    The zip holds `<directory>/SKILL.md` and `<directory>/references/<file>.md`, each the
    file under the skill's root byte for byte. Entries are stored uncompressed in sorted
    order with one fixed timestamp and mode, so the same files always give the same bytes.
    """
    files = sorted((skill.file, *(reference.file for reference in skill.references)))
    path = dest_dir / f"{skill.directory}.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as bundle:
        for file in files:
            entry = zipfile.ZipInfo(file, date_time=_BUNDLE_TIMESTAMP)
            entry.create_system = _ZIP_CREATED_ON_UNIX
            entry.external_attr = _BUNDLE_MODE << 16
            bundle.writestr(entry, (skill.root / file).read_bytes())
    return path


def skill_page_text(
    text: str, skill: Skill, *, install_link: str, bundle_link: str | None
) -> str:
    """`SKILL.md`'s text with the generated header inserted after its front matter.

    The header is an H1, the description's first sentence as a lead, and, when
    `bundle_link` is given, a line linking to `install_link` and to the skill's zip at
    `bundle_link`. A skill with no bundle cannot be loaded in another agent, so its header
    stops at the lead. When the body already opens with an H1, that H1 is kept and the
    lead follows it; otherwise the header opens with `# <name>`. Every skill page therefore
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
    header = [title, skill_lead(skill.description)]
    if bundle_link is not None:
        header.append(
            f"To load this skill in your own agent, see "
            f"[Use skills in your own agent]({install_link}). "
            f"[Download this skill as a zip]({bundle_link})."
        )
    return f"{front}\n{'\n\n'.join(header)}\n\n{rest}"


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


def _read_categories(fetched: Fetched) -> dict[str, tuple[str, ...]]:
    """Each skill directory `categories.yaml` files, mapped to its category, in file order.

    The file's `sources` key holds a list of skill directories, and its `domains` key maps
    each domain's name to one. Any other key files nothing, and so does a missing file. A
    name with no skill directory is carried and matches nothing.
    """
    path = fetched.docs_root / CATEGORIES_FILE
    _contain(fetched, path, root=fetched.docs_root)
    if not path.is_file():
        return {}
    location = _repo_path(fetched, path)
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise SkillError(f"{location}: {describe_yaml_error(exc)}") from exc
    if not isinstance(data, dict):
        raise SkillError(f"{location}: not a mapping")
    domains = data.get(_DOMAINS_KEY, {})
    if not isinstance(domains, dict):
        raise SkillError(f"{location}: {_DOMAINS_KEY!r} is not a mapping")
    lists = {(_SOURCES_KEY,): data.get(_SOURCES_KEY, [])}
    lists.update(
        {(_DOMAINS_KEY, str(domain)): names for domain, names in domains.items()}
    )
    categories: dict[str, tuple[str, ...]] = {}
    for category, names in lists.items():
        if not isinstance(names, list) or not all(
            isinstance(name, str) for name in names
        ):
            raise SkillError(
                f"{location}: {'/'.join(category)!r} is not a list of skill names"
            )
        for name in names:
            if name in categories:
                raise SkillError(f"{location}: {name!r} is listed more than once")
            categories[name] = category
    return categories


def _references(
    fetched: Fetched, directory: Path, *, root: Path
) -> tuple[Reference, ...]:
    references = []
    for path in sorted((directory / REFERENCES_DIR).glob("*.md")):
        _contain(fetched, path, root=root)
        references.append(
            Reference(
                file=path.relative_to(root).as_posix(),
                title=title_from_text(path.read_text(), path.stem),
            )
        )
    return tuple(references)


def _internal_root(fetched: Fetched) -> Path | None:
    internal_dir = fetched.source.internal_dir
    return None if internal_dir is None else fetched.repo_root / internal_dir


def _contain(fetched: Fetched, path: Path, *, root: Path) -> None:
    resolve_contained(
        path,
        root=root,
        error=f"{fetched.source.name!r}: {_repo_path(fetched, path)}",
        error_type=SkillError,
    )


def _repo_path(fetched: Fetched, path: Path) -> str:
    return PurePosixPath(path.relative_to(fetched.repo_root)).as_posix()
