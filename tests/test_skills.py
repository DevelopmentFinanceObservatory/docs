"""Tests for dfo_docs.skills: walking a skill tree, the drift check, and the header."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from dfo_docs.guards import Severity
from dfo_docs.models import Fetched, Source, SourceKind
from dfo_docs.skills import (
    Skill,
    SkillError,
    check_internal_dir,
    check_skill_drift,
    load_skills,
    skill_lead,
    skill_page_text,
    write_skill_bundle,
)

# The seven published skill descriptions, as YAML parses them, and the lead each gives.
REAL_DESCRIPTIONS = [
    (
        "dfo-faq",
        "Answers meta questions about the DFO platform itself, not substantive development-finance analysis. Covers what datasets and sources DFO draws on, how often they're updated, what time period the data covers, how DFO differs from browsing the OECD DAC website directly, where citations come from, how reliable the figures are, what happens when a question falls outside DFO's scope, data privacy and what logging in does, and how to report a bug or inaccurate answer. Use when the user asks about the tool itself rather than asking it to analyze data. Do not use for choosing which dataset to query for a specific analysis (use oda-data-sources instead), or for any question that wants an actual ODA figure, comparison, or calculation.",
        "Answers meta questions about the DFO platform itself, not substantive development-finance analysis.",
    ),
    (
        "oda-channels",
        "Covers how ODA is channelled — the distinction between bilateral and multilateral ODA, what earmarked (bi-multi) funding is, and how imputed multilateral contributions are estimated. Use this skill when the user asks about the structure of ODA flows, the difference between bilateral and multilateral aid, what bi-multi or earmarked funding means, how to estimate a donor's total contribution to a sector including through multilaterals, or which channel classification applies to a specific flow. Do not use for questions about which dataset to query (use oda-data-sources) or which flow type or price basis to apply (use oda-measures).",
        "Covers how ODA is channelled — the distinction between bilateral and multilateral ODA, what earmarked (bi-multi) funding is, and how imputed multilateral contributions are estimated.",
    ),
    (
        "oda-concepts",
        "Covers the core definitions, measures, and classifications used in ODA analysis: the 0.7% ODA/GNI target and how it is calculated, the grant equivalent methodology, Core ODA, donor groupings (DAC members, DAC associates, non-DAC, and EU Institutions), sector groupings by CRS purpose code, and key indicators for assessing donor prioritisation. Use when the user asks what a measure means, how to calculate it, which donors to include in an analysis, how sectors are defined, or how to interpret a donor's ODA effort. Do not use for policy marker analysis or for bilateral/multilateral channel analysis (use oda-channels instead).",
        "Covers the core definitions, measures, and classifications used in ODA analysis: the 0.7% ODA/GNI target and how it is calculated, the grant equivalent methodology, Core ODA, donor groupings (DAC members, DAC associates, non-DAC, and EU Institutions), sector groupings by CRS purpose code, and key indicators for assessing donor prioritisation.",
    ),
    (
        "oda-data-sources",
        "Covers which OECD DAC dataset to use for a given analysis: the CRS, the DAC aggregate tables (DAC1, DAC2a, DAC3a, DAC4, DAC5), CRS Grant Equivalents, and the Multisystem dataset, what each covers, and how to choose between them. Use when the user asks which dataset to query for a specific analysis, what a dataset covers or does not cover, how CRS differs from DAC1, why CRS totals do not match DAC1 totals, or which dataset supports a required breakdown (sector, recipient, channel, grant equivalents, or multilateral outflows). Do not use for questions about which flow type or price basis to apply (use oda-measures) or how ODA is channelled (use oda-channels).",
        "Covers which OECD DAC dataset to use for a given analysis: the CRS, the DAC aggregate tables (DAC1, DAC2a, DAC3a, DAC4, DAC5), CRS Grant Equivalents, and the Multisystem dataset, what each covers, and how to choose between them.",
    ),
    (
        "oda-measures",
        "Covers how ODA is measured and reported by the OECD DAC, including which flow type to use (gross disbursements, net disbursements, grant equivalents, or commitments), whether to use current or constant prices, and how grants, concessional loans, and private sector instruments are counted. Use when a question involves choosing a measure, comparing ODA figures across years, explaining what a specific ODA figure represents, or assessing how a financing instrument is counted in ODA. Do not use for questions about which sectors or countries ODA is allocated to (use the CRS purpose codes or recipient lists instead).",
        "Covers how ODA is measured and reported by the OECD DAC, including which flow type to use (gross disbursements, net disbursements, grant equivalents, or commitments), whether to use current or constant prices, and how grants, concessional loans, and private sector instruments are counted.",
    ),
    (
        "oda-routing",
        'Detects when a request matches the attached ODA skills (oda-measures, oda-channels, oda-data-sources, oda-concepts) and routes to the skills the ask needs. Uses the user\'s phrasing (e.g., "gross vs net disbursements," "grant equivalent," "bilateral vs multilateral," "bi-multi/earmarked," "CRS dataset," "Core ODA," "DAC members"). Do not use for substantive ODA analysis; use this only to choose which ODA skills to load.',
        "Detects when a request matches the attached ODA skills (oda-measures, oda-channels, oda-data-sources, oda-concepts) and routes to the skills the ask needs.",
    ),
    (
        "policy-markers",
        "Covers OECD DAC policy markers used to classify bilateral ODA in the Creditor Reporting System (CRS). Use when the user asks what a policy marker is, which markers exist, how to score an activity, how to interpret gender or climate marker data, or how to analyse ODA by policy objective. Also use when the user asks whether policy marker analysis is appropriate for a given question.",
        "Covers OECD DAC policy markers used to classify bilateral ODA in the Creditor Reporting System (CRS).",
    ),
]


@pytest.mark.parametrize(("name", "description", "lead"), REAL_DESCRIPTIONS)
def test_lead_is_the_first_sentence_of_each_real_description(
    name: str, description: str, lead: str
):
    assert skill_lead(description) == lead, name


def test_lead_is_the_whole_description_without_a_sentence_end():
    assert skill_lead("Covers 0.7% targets and e.g.,commas") == (
        "Covers 0.7% targets and e.g.,commas"
    )


def test_lead_joins_a_description_broken_across_lines():
    assert skill_lead("Covers one\nthing. Then more.") == "Covers one thing."


def _fetched(tmp_path: Path, *, internal_dir: str | None = None) -> Fetched:
    repo_root = tmp_path / "repo"
    docs_root = repo_root / "skills"
    docs_root.mkdir(parents=True)
    source = Source(
        name="dfo-skills",
        repo="DevelopmentFinanceObservatory/skills",
        kind=SourceKind.SKILL,
        docs_dir="skills",
        path="skills",
        title="All skills",
        internal_dir=internal_dir,
    )
    return Fetched(
        source=source, repo_root=repo_root, docs_root=docs_root, commit="0" * 40
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _skill_md(name: str, description: str = "Covers a thing. More.") -> str:
    return f"---\nname: {name}\ndescription: >-\n  {description}\n---\n\n## Overview\n"


def test_load_skills_sorts_by_directory_and_skips_underscore_directories(tmp_path):
    fetched = _fetched(tmp_path)
    _write(fetched.docs_root / "zeta" / "SKILL.md", _skill_md("zeta"))
    _write(fetched.docs_root / "alpha" / "SKILL.md", _skill_md("alpha"))
    _write(fetched.docs_root / "_template" / "SKILL.md", "no front matter\n")

    skills = load_skills(fetched)

    assert [skill.directory for skill in skills] == ["alpha", "zeta"]
    assert skills[0].name == "alpha"
    assert skills[0].description == "Covers a thing. More."
    assert skills[0].file == "alpha/SKILL.md"
    assert skills[0].category == ()


def test_load_skills_files_skills_by_category_in_file_order(tmp_path):
    fetched = _fetched(tmp_path)
    for name in ("alpha", "beta", "gamma", "zeta"):
        _write(fetched.docs_root / name / "SKILL.md", _skill_md(name))
    _write(
        fetched.docs_root / "categories.yaml",
        "sources:\n  - zeta\n  - no-such-skill\n"
        "domains:\n  debt:\n    - gamma\n  aid: []\n"
        "uncategorised:\n  - beta\n",
    )

    skills = load_skills(fetched)

    assert [(skill.directory, skill.category) for skill in skills] == [
        ("alpha", ()),
        ("beta", ()),
        ("zeta", ("sources",)),
        ("gamma", ("domains", "debt")),
    ]


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("sources: [alpha\n", id="invalid-yaml"),
        pytest.param("- alpha\n", id="top-level-list"),
        pytest.param("domains:\n  - aid\n", id="domains-as-a-list"),
        pytest.param("sources:\n", id="null-list"),
        pytest.param("domains:\n  aid:\n    - 7\n", id="entry-not-a-string"),
        pytest.param(
            "sources:\n  - alpha\ndomains:\n  aid:\n    - alpha\n",
            id="skill-listed-twice",
        ),
    ],
)
def test_bad_categories_file_fails_naming_it(tmp_path, text: str):
    fetched = _fetched(tmp_path)
    _write(fetched.docs_root / "alpha" / "SKILL.md", _skill_md("alpha"))
    _write(fetched.docs_root / "categories.yaml", text)

    with pytest.raises(SkillError, match=r"skills/categories\.yaml"):
        load_skills(fetched)


def test_load_skills_reads_sorted_references_with_titles(tmp_path):
    fetched = _fetched(tmp_path)
    skill_dir = fetched.docs_root / "alpha"
    _write(skill_dir / "SKILL.md", _skill_md("alpha"))
    _write(skill_dir / "references" / "price-basis.md", "# Price basis\n\nText.\n")
    _write(skill_dir / "references" / "flow-types.md", "## Only an H2\n")

    (skill,) = load_skills(fetched)

    assert [(ref.file, ref.title) for ref in skill.references] == [
        ("alpha/references/flow-types.md", "Flow types"),
        ("alpha/references/price-basis.md", "Price basis"),
    ]


def test_directory_without_skill_md_fails_naming_it(tmp_path):
    fetched = _fetched(tmp_path)
    _write(fetched.docs_root / "stray" / "notes.md", "# Notes\n")

    with pytest.raises(SkillError, match=r"skills/stray has no SKILL\.md"):
        load_skills(fetched)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("## Overview\n", "no YAML front matter"),
        ("---\nname: [unclosed\n---\n", r"skills/alpha/SKILL\.md: "),
        ("---\n- a list\n---\n", "not a mapping"),
        ("---\ndescription: Covers.\n---\n", "no 'name'"),
        ("---\nname: alpha\n---\n", "no 'description'"),
    ],
)
def test_bad_front_matter_fails_naming_the_file(tmp_path, text: str, message: str):
    fetched = _fetched(tmp_path)
    _write(fetched.docs_root / "alpha" / "SKILL.md", text)

    with pytest.raises(SkillError, match=message) as info:
        load_skills(fetched)
    assert "skills/alpha/SKILL.md" in str(info.value)


def _outside_file(tmp_path: Path) -> Path:
    secret = tmp_path / "outside" / "secret.md"
    _write(secret, "---\nname: secret\ndescription: Leaked.\n---\n# Secret\n")
    return secret


def test_contained_tree_loads(tmp_path):
    """Control for the two symlink cases below: the same tree with real files loads."""
    fetched = _fetched(tmp_path)
    skill_dir = fetched.docs_root / "alpha"
    _write(skill_dir / "SKILL.md", _skill_md("alpha"))
    _write(skill_dir / "references" / "leak.md", "# Leak\n")

    (skill,) = load_skills(fetched)

    assert [ref.file for ref in skill.references] == ["alpha/references/leak.md"]


def test_reference_symlinked_outside_the_docs_root_fails(tmp_path):
    fetched = _fetched(tmp_path)
    skill_dir = fetched.docs_root / "alpha"
    _write(skill_dir / "SKILL.md", _skill_md("alpha"))
    (skill_dir / "references").mkdir()
    (skill_dir / "references" / "leak.md").symlink_to(_outside_file(tmp_path))

    with pytest.raises(SkillError, match="resolves outside") as info:
        load_skills(fetched)
    assert "skills/alpha/references/leak.md" in str(info.value)


def test_skill_directory_symlinked_outside_the_docs_root_fails(tmp_path):
    fetched = _fetched(tmp_path)
    outside = _outside_file(tmp_path).parent
    (outside / "SKILL.md").write_text(_skill_md("evil"))
    (fetched.docs_root / "evil").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SkillError, match="resolves outside") as info:
        load_skills(fetched)
    assert "skills/evil" in str(info.value)


def test_drift_warns_on_markdown_no_skill_publishes(tmp_path):
    fetched = _fetched(tmp_path)
    skill_dir = fetched.docs_root / "alpha"
    _write(skill_dir / "SKILL.md", _skill_md("alpha"))
    _write(skill_dir / "references" / "kept.md", "# Kept\n")
    _write(skill_dir / "references" / "deep" / "nested.md", "# Nested\n")
    _write(skill_dir / "notes.md", "# Notes\n")
    _write(fetched.docs_root / "README.md", "# Skills\n")
    _write(fetched.docs_root / "_template" / "SKILL.md", _skill_md("_template"))

    findings = check_skill_drift(fetched, load_skills(fetched))

    assert {finding.severity for finding in findings} == {Severity.WARNING}
    assert [finding.path for finding in findings] == [
        "skills/README.md",
        "skills/alpha/notes.md",
        "skills/alpha/references/deep/nested.md",
    ]


_SKILL = Skill(
    directory="alpha",
    name="alpha",
    description="Covers a thing. Use when asked.",
    references=(),
    root=Path("skills"),
    ships=True,
)
_INSTALL_LINK = "../../hub/skills/use-in-your-agent.md"
_INSTALL = (
    "To load this skill in your own agent, see "
    "[Use skills in your own agent](../../hub/skills/use-in-your-agent.md). "
    "[Download this skill as a zip](../alpha.zip)."
)


def test_header_generates_an_h1_when_the_body_has_none():
    text = "---\nname: alpha\n---\n\n## Overview\n\nBody.\n"

    result = skill_page_text(
        text, _SKILL, install_link=_INSTALL_LINK, bundle_link="../alpha.zip"
    )

    assert result == (
        "---\nname: alpha\n---\n\n# alpha\n\nCovers a thing.\n\n"
        f"{_INSTALL}\n\n## Overview\n\nBody.\n"
    )


def test_header_keeps_the_bodys_own_h1_first():
    text = "---\nname: alpha\n---\n\n# Alpha skill\n\n## Overview\n"

    result = skill_page_text(
        text, _SKILL, install_link=_INSTALL_LINK, bundle_link="../alpha.zip"
    )

    assert result == (
        "---\nname: alpha\n---\n\n# Alpha skill\n\nCovers a thing.\n\n"
        f"{_INSTALL}\n\n## Overview\n"
    )
    assert result.count("\n# ") == 1


def test_header_stops_at_the_lead_without_a_bundle():
    text = "---\nname: alpha\n---\n\n## Overview\n\nBody.\n"

    result = skill_page_text(text, _SKILL, install_link=_INSTALL_LINK, bundle_link=None)

    assert result == (
        "---\nname: alpha\n---\n\n# alpha\n\nCovers a thing.\n\n## Overview\n\nBody.\n"
    )


def test_bundle_holds_the_skill_files_and_its_bytes_depend_only_on_them(tmp_path):
    fetched = _fetched(tmp_path)
    skill_dir = fetched.docs_root / "alpha"
    sources = {
        "alpha/SKILL.md": _skill_md("alpha").encode(),
        "alpha/references/b.md": b"# B\r\n",
        "alpha/references/a.md": b"# A\n",
    }
    for name, content in sources.items():
        (fetched.docs_root / name).parent.mkdir(parents=True, exist_ok=True)
        (fetched.docs_root / name).write_bytes(content)
    _write(skill_dir / "attachments.yaml", "datasets: []\n")
    _write(skill_dir / "notes.md", "# Notes\n")
    (skill,) = load_skills(fetched)

    first = write_skill_bundle(skill, dest_dir=tmp_path / "first")
    for name in sources:
        os.utime(fetched.docs_root / name, (1_000_000_000, 1_000_000_000))
        (fetched.docs_root / name).chmod(0o600)
    second = write_skill_bundle(skill, dest_dir=tmp_path / "second")

    assert first == tmp_path / "first" / "alpha.zip"
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as bundle:
        assert bundle.namelist() == [
            "alpha/SKILL.md",
            "alpha/references/a.md",
            "alpha/references/b.md",
        ]
        assert {name: bundle.read(name) for name in bundle.namelist()} == sources
        assert {info.compress_type for info in bundle.infolist()} == {
            zipfile.ZIP_STORED
        }


def test_load_skills_reads_both_roots_and_only_the_docs_root_ships(tmp_path):
    fetched = _fetched(tmp_path, internal_dir="internal/skills")
    internal = fetched.repo_root / "internal" / "skills"
    _write(fetched.docs_root / "beta" / "SKILL.md", _skill_md("beta"))
    _write(fetched.docs_root / "zeta" / "SKILL.md", _skill_md("zeta"))
    _write(fetched.docs_root / "categories.yaml", "sources:\n  - zeta\n")
    _write(internal / "alpha" / "SKILL.md", _skill_md("alpha"))
    _write(internal / "alpha" / "references" / "scope.md", "# Scope\n")
    _write(internal / "alpha" / "notes.md", "# Notes\n")

    skills = load_skills(fetched)

    assert [(skill.directory, skill.root, skill.ships) for skill in skills] == [
        ("alpha", internal, False),
        ("beta", fetched.docs_root, True),
        ("zeta", fetched.docs_root, True),
    ]
    # A file is addressed from its own root, so its page lands where it would have
    # from the docs root.
    assert skills[0].file == "alpha/SKILL.md"
    assert [ref.file for ref in skills[0].references] == ["alpha/references/scope.md"]
    assert [finding.path for finding in check_skill_drift(fetched, skills)] == [
        "internal/skills/alpha/notes.md"
    ]
    assert check_internal_dir(fetched) == []


def test_skill_directory_in_both_roots_fails_naming_both(tmp_path):
    fetched = _fetched(tmp_path, internal_dir="internal/skills")
    _write(fetched.docs_root / "alpha" / "SKILL.md", _skill_md("alpha"))
    _write(
        fetched.repo_root / "internal" / "skills" / "alpha" / "SKILL.md",
        _skill_md("alpha"),
    )

    with pytest.raises(SkillError) as info:
        load_skills(fetched)
    assert "skills/alpha and internal/skills/alpha" in str(info.value)


def test_internal_dir_missing_from_the_checkout_warns_once_and_loads(tmp_path):
    fetched = _fetched(tmp_path, internal_dir="internal/skills")
    _write(fetched.docs_root / "alpha" / "SKILL.md", _skill_md("alpha"))

    (finding,) = check_internal_dir(fetched)
    skills = load_skills(fetched)

    assert finding.severity is Severity.WARNING
    assert finding.path == "internal/skills"
    assert [(skill.directory, skill.ships) for skill in skills] == [("alpha", True)]
    assert check_skill_drift(fetched, skills) == []


def test_internal_dir_symlinked_outside_the_repository_fails(tmp_path):
    fetched = _fetched(tmp_path, internal_dir="internal/skills")
    _write(fetched.docs_root / "alpha" / "SKILL.md", _skill_md("alpha"))
    outside = tmp_path / "elsewhere"
    _write(outside / "evil" / "SKILL.md", _skill_md("evil"))
    (fetched.repo_root / "internal").mkdir()
    (fetched.repo_root / "internal" / "skills").symlink_to(
        outside, target_is_directory=True
    )

    with pytest.raises(SkillError, match="resolves outside"):
        load_skills(fetched)
