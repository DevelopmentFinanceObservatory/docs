"""Tests for dfo_docs.sidecar: locating and parsing the docs sidecar shapes.

Fixtures under `tests/fixtures/sidecars/` are copies of the seven live ONEcampaign sidecars
(shape 1) plus small hand-written ones for the flat `mkdocs.yml` (shape 2), `zensical.toml`
(shape 3), and the plain new-repository sidecar (shape 4).
"""

import re
from pathlib import Path

import pytest

from dfo_docs.models import Source
from dfo_docs.sidecar import SidecarError, find_sidecar, load_sidecar

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sidecars"


def _source(name: str, **overrides) -> Source:
    return Source(name=name, repo=f"ONEcampaign/{name}", **overrides)


def test_shape1_nested_mkdocs_resolves_docs_root_and_three_segment_path():
    repo_root = FIXTURES / "bblocks_data_importers"

    sidecar = load_sidecar(repo_root, _source("bblocks_data_importers"))

    assert sidecar.path == "tools/bblocks/data-importers"
    assert sidecar.docs_root == repo_root / "docs" / "docs"
    assert sidecar.description is None


def test_shape1_path_shaped_site_name_falls_back_to_source_title():
    sidecar = load_sidecar(
        FIXTURES / "bblocks_data_importers",
        _source("bblocks_data_importers", title="Data importers"),
    )

    # site_name is "tools/bblocks/data-importers", which carries a "/", so it must not
    # become the title unchanged; the registry's bridge title wins instead.
    assert sidecar.title == "Data importers"


def test_shape1_path_shaped_site_name_and_no_source_title_falls_back_to_source_name():
    sidecar = load_sidecar(
        FIXTURES / "bblocks_data_importers", _source("bblocks_data_importers")
    )

    # No source.title is set either, so the last-resort fallback is the source's own name.
    assert sidecar.title == "bblocks_data_importers"


def test_bare_entry_resolved_from_h1():
    sidecar = load_sidecar(
        FIXTURES / "bblocks_data_importers", _source("bblocks_data_importers")
    )

    top_level = {entry.file: entry for entry in sidecar.nav if entry.breadcrumb == ()}
    assert top_level["index.md"].title == "Data importers for the bblocks suite"


def test_bare_entry_with_no_h1_resolved_from_filename():
    sidecar = load_sidecar(
        FIXTURES / "bblocks_data_importers", _source("bblocks_data_importers")
    )

    by_file = {entry.file: entry for entry in sidecar.nav}
    assert by_file["importers/index.md"].title == "Index"


def test_nested_group_produces_breadcrumb():
    sidecar = load_sidecar(
        FIXTURES / "bblocks_data_importers", _source("bblocks_data_importers")
    )

    by_file = {entry.file: entry for entry in sidecar.nav}
    weo = by_file["importers/weo.md"]
    assert weo.title == "World Economic Outlook"
    assert weo.breadcrumb == ("Available data importers",)

    # top-level entries are not nested under anything.
    assert by_file["getting-started.md"].breadcrumb == ()


def test_nav_walk_is_ordered_and_complete():
    sidecar = load_sidecar(
        FIXTURES / "bblocks_data_importers", _source("bblocks_data_importers")
    )

    assert [entry.file for entry in sidecar.nav] == [
        "index.md",
        "getting-started.md",
        "design-philosophy.md",
        "importers/index.md",
        "importers/weo.md",
        "importers/world-bank.md",
        "importers/ids.md",
        "importers/ghed.md",
        "importers/unaids.md",
        "importers/hdr.md",
        "importers/wfp.md",
        "importers/baci.md",
        "changelog.md",
    ]


def test_shape1_two_segment_path_and_site_description():
    repo_root = FIXTURES / "imf-reader"

    sidecar = load_sidecar(repo_root, _source("imf-reader", title="IMF reader"))

    assert sidecar.path == "tools/imf-reader"
    assert sidecar.description == "Python package for accessing IMF data"
    assert (
        sidecar.title == "IMF reader"
    )  # site_name carries "/", falls back to source.title
    assert sidecar.docs_root == repo_root / "docs" / "docs"


def test_titled_entry_title_is_not_overridden_by_its_own_h1():
    sidecar = load_sidecar(FIXTURES / "imf-reader", _source("imf-reader"))

    home = next(entry for entry in sidecar.nav if entry.file == "index.md")
    assert home.title == "Home"


def test_shape2_flat_mkdocs_extra_dfo_path_wins_over_site_name():
    repo_root = FIXTURES / "flat_mkdocs"

    sidecar = load_sidecar(repo_root, _source("pydeflate"))

    assert sidecar.path == "tools/pydeflate"  # not "pydeflate", the site_name
    assert sidecar.title == "pydeflate"
    assert sidecar.docs_root == repo_root / "docs"


def test_shape3_zensical_toml():
    repo_root = FIXTURES / "zensical"

    sidecar = load_sidecar(repo_root, _source("resolvekit"))

    assert sidecar.docs_root == repo_root / "docs"
    assert sidecar.description.startswith("Resolve messy place")
    by_file = {entry.file: entry for entry in sidecar.nav}
    assert by_file["getting-started/install.md"].breadcrumb == ("Getting started",)
    assert by_file["roadmap.md"].title == "Roadmap"  # bare, no H1, de-kebabed


def test_shape4_plain_sidecar_no_site_name():
    repo_root = FIXTURES / "plain"

    sidecar = load_sidecar(repo_root, _source("new-package"))

    assert sidecar.path == "tools/new-package"
    assert sidecar.title == "new-package"
    assert sidecar.docs_root == repo_root / "docs"
    assert [entry.file for entry in sidecar.nav] == ["index.md", "getting-started.md"]


def test_find_sidecar_missing_raises():
    with pytest.raises(SidecarError, match="no sidecar found"):
        find_sidecar(FIXTURES)  # the sidecars directory itself carries no sidecar


def test_malformed_nav_entry_raises(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "mkdocs.yml").write_text(
        "site_name: broken\nnav:\n  - one: two\n    three: four\n"
    )

    with pytest.raises(SidecarError, match="unrecognised nav entry"):
        load_sidecar(tmp_path, _source("broken"))


def test_malformed_yaml_sidecar_names_the_file(tmp_path):
    (tmp_path / "mkdocs.yml").write_text("site_name: broken\nnav: []\n  - bad\n")

    with pytest.raises(SidecarError, match=re.escape("mkdocs.yml")):
        load_sidecar(tmp_path, _source("broken"))


def test_malformed_toml_sidecar_names_the_file(tmp_path):
    (tmp_path / "zensical.toml").write_text('[project\ntitle = "broken"\n')

    with pytest.raises(SidecarError, match=re.escape("zensical.toml")):
        load_sidecar(tmp_path, _source("broken"))


def test_docs_dir_escaping_repo_root_rejected(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "mkdocs.yml").write_text(
        "site_name: escaping\ndocs_dir: ../secret\nnav: []\n"
    )
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "index.md").write_text("# Secret\n")

    with pytest.raises(SidecarError, match=r"docs_dir"):
        load_sidecar(repo_root, _source("escaping"))


def test_nav_entry_escaping_docs_root_rejected(tmp_path):
    repo_root = tmp_path / "repo"
    docs = repo_root / "docs"
    docs.mkdir(parents=True)
    (repo_root / "mkdocs.yml").write_text(
        "site_name: escaping\nnav:\n  - ../outside.md\n"
    )
    (repo_root / "outside.md").write_text("# Outside\n")

    with pytest.raises(SidecarError, match=r"nav entry"):
        load_sidecar(repo_root, _source("escaping"))


def test_nav_entry_symlink_escaping_docs_root_rejected(tmp_path):
    repo_root = tmp_path / "repo"
    docs = repo_root / "docs"
    docs.mkdir(parents=True)
    (repo_root / "mkdocs.yml").write_text("site_name: escaping\nnav:\n  - link.md\n")

    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "evil.md"
    target.write_text("# Evil\n")
    (docs / "link.md").symlink_to(target)

    with pytest.raises(SidecarError, match=r"nav entry"):
        load_sidecar(repo_root, _source("escaping"))


def test_docs_dir_symlink_escaping_repo_root_rejected(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "mkdocs.yml").write_text("site_name: escaping\nnav: []\n")

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "index.md").write_text("# Outside\n")
    (repo_root / "docs").symlink_to(outside)

    with pytest.raises(SidecarError, match=r"docs_dir"):
        load_sidecar(repo_root, _source("escaping"))


def test_source_path_mismatch_against_sidecar_rejected():
    with pytest.raises(
        SidecarError, match=r"tools/wrong.*tools/bblocks/data-importers"
    ):
        load_sidecar(
            FIXTURES / "bblocks_data_importers",
            _source("bblocks_data_importers", path="tools/wrong"),
        )


def test_source_path_matching_sidecar_accepted():
    sidecar = load_sidecar(
        FIXTURES / "bblocks_data_importers",
        _source("bblocks_data_importers", path="tools/bblocks/data-importers"),
    )

    assert sidecar.path == "tools/bblocks/data-importers"


# --- Source.exclude ------------------------------------------------------------


def test_exclude_holds_a_section_out_of_nav_and_records_it():
    sidecar = load_sidecar(
        FIXTURES / "bblocks_data_importers",
        _source("bblocks_data_importers", exclude=("importers/*",)),
    )

    files = [entry.file for entry in sidecar.nav]
    assert files == [
        "index.md",
        "getting-started.md",
        "design-philosophy.md",
        "changelog.md",
    ]
    assert sidecar.excluded == (
        "importers/index.md",
        "importers/weo.md",
        "importers/world-bank.md",
        "importers/ids.md",
        "importers/ghed.md",
        "importers/unaids.md",
        "importers/hdr.md",
        "importers/wfp.md",
        "importers/baci.md",
    )


def test_exclude_drops_the_group_breadcrumb_with_its_last_entry():
    sidecar = load_sidecar(
        FIXTURES / "bblocks_data_importers",
        _source("bblocks_data_importers", exclude=("importers/*",)),
    )

    # "Available data importers" exists only as a breadcrumb on the entries beneath it, so
    # excluding all of them leaves manifest.build_pages nothing to build a group node from.
    assert all(entry.breadcrumb == () for entry in sidecar.nav)


def test_exclude_can_name_a_single_page():
    sidecar = load_sidecar(
        FIXTURES / "bblocks_data_importers",
        _source("bblocks_data_importers", exclude=("changelog.md",)),
    )

    assert "changelog.md" not in [entry.file for entry in sidecar.nav]
    assert sidecar.excluded == ("changelog.md",)
    assert any(entry.file == "importers/weo.md" for entry in sidecar.nav)


def test_exclude_pattern_matching_nothing_is_an_error():
    with pytest.raises(SidecarError, match=r"'reference/\*'.*match no nav entry"):
        load_sidecar(
            FIXTURES / "bblocks_data_importers",
            _source("bblocks_data_importers", exclude=("reference/*",)),
        )


def test_exclude_reports_every_unused_pattern_not_just_the_first():
    with pytest.raises(SidecarError, match=r"'reference/\*'.*'api/\*'"):
        load_sidecar(
            FIXTURES / "bblocks_data_importers",
            _source(
                "bblocks_data_importers",
                exclude=("reference/*", "changelog.md", "api/*"),
            ),
        )


def test_no_exclude_leaves_nav_whole():
    sidecar = load_sidecar(
        FIXTURES / "bblocks_data_importers", _source("bblocks_data_importers")
    )

    assert len(sidecar.nav) == 13
    assert sidecar.excluded == ()


# --- Sidecar.docs_url -----------------------------------------------------------


def test_docs_url_read_from_extra_dfo(tmp_path):
    repo_root = tmp_path / "repo"
    docs = repo_root / "docs"
    docs.mkdir(parents=True)
    (docs / "index.md").write_text("# Home\n")
    (repo_root / "mkdocs.yml").write_text(
        "site_name: has-docs-url\n"
        "nav:\n"
        "  - index.md\n"
        "extra:\n"
        "  dfo:\n"
        "    docs_url: https://example.github.io/has-docs-url/latest/\n"
    )

    sidecar = load_sidecar(repo_root, _source("has-docs-url"))

    assert sidecar.docs_url == "https://example.github.io/has-docs-url/latest/"


def test_docs_url_absent_is_legal():
    sidecar = load_sidecar(
        FIXTURES / "bblocks_data_importers", _source("bblocks_data_importers")
    )

    assert sidecar.docs_url is None


def test_docs_url_has_no_fallback_to_site_url(tmp_path):
    """`site_url` sits at the top level for the source's own generator; it must never
    stand in for `extra.dfo.docs_url`, whose whole reason for existing is that the two
    can point at different places (a versioned base vs. a bare repository root)."""
    repo_root = tmp_path / "repo"
    docs = repo_root / "docs"
    docs.mkdir(parents=True)
    (docs / "index.md").write_text("# Home\n")
    (repo_root / "mkdocs.yml").write_text(
        "site_name: no-docs-url\n"
        "site_url: https://example.github.io/no-docs-url/\n"
        "nav:\n"
        "  - index.md\n"
    )

    sidecar = load_sidecar(repo_root, _source("no-docs-url"))

    assert sidecar.docs_url is None


def test_sidecar_with_no_nav_is_an_error(tmp_path):
    repo_root = tmp_path / "empty-nav"
    (repo_root / "docs").mkdir(parents=True)
    (repo_root / "mkdocs.yml").write_text("path: tools/empty\ntitle: Empty\n")

    with pytest.raises(SidecarError, match="declares no nav"):
        load_sidecar(repo_root, _source("empty-nav"))


def test_zensical_nav_scoped_into_a_subtable_is_an_error(tmp_path):
    """The shape tossd-reader shipped: a `nav` array written after a `[project.<table>]`
    header, which TOML scopes into that table rather than into `[project]`."""
    repo_root = tmp_path / "scoped-nav"
    (repo_root / "docs").mkdir(parents=True)
    (repo_root / "docs" / "index.md").write_text("# Home\n")
    (repo_root / "zensical.toml").write_text(
        '[project]\nsite_name = "scoped-nav"\n\n'
        '[project.extra.version]\nprovider = "mike"\n\n'
        'nav = ["index.md"]\n'
    )

    with pytest.raises(
        SidecarError, match=r"declares no nav.*scoped it into that table"
    ):
        load_sidecar(repo_root, _source("scoped-nav"))
