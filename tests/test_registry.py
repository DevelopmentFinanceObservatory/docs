"""Tests for dfo_docs.registry: loading and validating sources.yaml and hub.yaml."""

from pathlib import Path

import pytest

from dfo_docs.models import SourceKind
from dfo_docs.registry import (
    RegistryError,
    enabled_sources,
    load_hub,
    load_sources,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_load_sources_valid():
    sources = load_sources(REPO_ROOT / "sources.yaml")

    assert sources["imf-reader"].repo == "ONEcampaign/imf-reader"
    assert sources["imf-reader"].path == "tools/imf-reader"
    assert sources["imf-reader"].ref == "main"

    assert sources["pydeflate"].kind == "external"
    assert sources["pydeflate"].url == "https://jm-rivera.github.io/pydeflate/"
    assert sources["pydeflate"].docs_dir is None


def test_disabled_rows_loaded_but_excluded():
    sources = load_sources(REPO_ROOT / "sources.yaml")

    assert set(sources) == {
        "bblocks_data_importers",
        "dcp-tools",
        "oda_reader",
        "imf-reader",
        "tossd-reader",
        "pydeflate",
        "resolvekit",
        "bblocks",
        "bblocks-projects",
        "dfo-apis",
        "dfo-ai",
        "dfo-skills",
    }

    assert sources["bblocks_data_importers"].enabled is False
    assert sources["bblocks_data_importers"].reason
    assert sources["bblocks"].enabled is False
    assert sources["bblocks"].reason
    assert sources["bblocks-projects"].enabled is False
    assert sources["bblocks-projects"].reason

    live = enabled_sources(sources)
    assert len(live) == 9  # six docs rows, one skill row, two external rows
    assert "bblocks_data_importers" not in live
    assert "bblocks" not in live
    assert "bblocks-projects" not in live
    assert "dfo-apis" in live
    assert "dfo-ai" in live
    assert "dfo-skills" in live


def test_duplicate_path_rejected(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        """
        sources:
          - name: a
            repo: org/a
            path: tools/dup
          - name: b
            repo: org/b
            path: tools/dup
        """
    )

    with pytest.raises(RegistryError, match="duplicate path"):
        load_sources(path)


def test_external_with_docs_dir_rejected(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        """
        sources:
          - name: a
            repo: org/a
            kind: external
            docs_dir: docs
            url: https://example.com/
        """
    )

    with pytest.raises(RegistryError, match="docs_dir"):
        load_sources(path)


def test_missing_required_field_rejected(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        """
        sources:
          - name: a
        """
    )

    with pytest.raises(RegistryError, match="repo"):
        load_sources(path)


def test_load_sources_malformed_yaml_names_the_file(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        """
        sources: []
          - not: valid
        """
    )

    with pytest.raises(RegistryError, match=r"sources\.yaml"):
        load_sources(path)


def test_load_hub_malformed_yaml_names_the_file(tmp_path):
    path = tmp_path / "hub.yaml"
    path.write_text(
        """
        nav: []
          - not: valid
        """
    )

    with pytest.raises(RegistryError, match=r"hub\.yaml"):
        load_hub(path)


def test_exclude_loads_as_a_tuple_of_patterns(tmp_path: Path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n"
        "  - name: tossd-reader\n"
        "    repo: ONEcampaign/tossd-reader\n"
        "    exclude:\n"
        "      - reference/*\n"
    )

    sources = load_sources(path)

    assert sources["tossd-reader"].exclude == ("reference/*",)


def test_exclude_defaults_to_empty(tmp_path: Path):
    path = tmp_path / "sources.yaml"
    path.write_text("sources:\n  - name: a\n    repo: ONEcampaign/a\n")

    assert load_sources(path)["a"].exclude == ()


def test_exclude_must_be_a_list_of_strings(tmp_path: Path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n  - name: a\n    repo: ONEcampaign/a\n    exclude: reference/*\n"
    )

    with pytest.raises(RegistryError, match="list of glob patterns"):
        load_sources(path)


def test_external_row_may_not_exclude(tmp_path: Path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n"
        "  - name: pydeflate\n"
        "    repo: jm-rivera/pydeflate\n"
        "    kind: external\n"
        "    url: https://example.invalid/\n"
        "    exclude:\n"
        "      - reference/*\n"
    )

    with pytest.raises(RegistryError, match="publishes no pages"):
        load_sources(path)


_SKILL_ROW = (
    "sources:\n"
    "  - name: dfo-skills\n"
    "    repo: ONEcampaign/dfo-skills\n"
    "    kind: skill\n"
    "    docs_dir: skills\n"
    "    path: skills\n"
    "    title: All skills\n"
)


def test_skill_row_loads_with_ref_defaulting_to_main(tmp_path: Path):
    path = tmp_path / "sources.yaml"
    path.write_text(_SKILL_ROW)

    source = load_sources(path)["dfo-skills"]

    assert source.kind is SourceKind.SKILL
    assert source.ref == "main"
    assert (source.docs_dir, source.path, source.title) == (
        "skills",
        "skills",
        "All skills",
    )


@pytest.mark.parametrize("field_name", ["docs_dir", "path", "title"])
def test_skill_row_requires_docs_dir_path_and_title(tmp_path: Path, field_name: str):
    path = tmp_path / "sources.yaml"
    lines = [
        line
        for line in _SKILL_ROW.splitlines(keepends=True)
        if not line.strip().startswith(f"{field_name}:")
    ]
    path.write_text("".join(lines))

    with pytest.raises(RegistryError, match=f"missing required field '{field_name}'"):
        load_sources(path)


def test_skill_row_may_not_exclude(tmp_path: Path):
    path = tmp_path / "sources.yaml"
    path.write_text(_SKILL_ROW + "    exclude:\n      - _template/*\n")

    with pytest.raises(RegistryError, match="may not carry exclude"):
        load_sources(path)
