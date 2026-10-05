"""Tests for dfo_docs.assets: copying a source's images into the corpus."""

from __future__ import annotations

from pathlib import Path

from dfo_docs.assets import _DEFAULT_MAX_ASSET_BYTES, copy_assets
from dfo_docs.guards import Severity


def test_normal_copy_preserves_relative_layout(tmp_path: Path):
    docs_root = tmp_path / "docs"
    dest_root = tmp_path / "dest"
    (docs_root / "assets" / "img").mkdir(parents=True)
    (docs_root / "assets" / "img" / "logo.png").write_bytes(b"fake-png-bytes")

    findings = copy_assets(docs_root, dest_root, source_name="imf-reader")

    assert findings == []
    copied = dest_root / "assets" / "img" / "logo.png"
    assert copied.is_file()
    assert copied.read_bytes() == b"fake-png-bytes"


def test_allowlisted_file_over_size_threshold_still_copies_and_warns(tmp_path: Path):
    docs_root = tmp_path / "docs"
    dest_root = tmp_path / "dest"
    docs_root.mkdir()
    big_file = docs_root / "huge.png"
    big_file.write_bytes(b"x" * (_DEFAULT_MAX_ASSET_BYTES + 1))

    findings = copy_assets(docs_root, dest_root, source_name="imf-reader")

    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert "huge.png" in findings[0].message
    assert str(_DEFAULT_MAX_ASSET_BYTES) in findings[0].message.replace(",", "")
    assert (dest_root / "huge.png").is_file()


def test_skipped_non_markdown_file_produces_warning_naming_suffix(tmp_path: Path):
    docs_root = tmp_path / "docs"
    dest_root = tmp_path / "dest"
    docs_root.mkdir()
    (docs_root / "notes.txt").write_text("not an image")

    findings = copy_assets(docs_root, dest_root, source_name="imf-reader")

    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert ".txt" in findings[0].message
    assert not (dest_root / "notes.txt").exists()


def test_symlink_resolving_outside_docs_root_is_skipped_as_error(tmp_path: Path):
    docs_root = tmp_path / "docs"
    dest_root = tmp_path / "dest"
    docs_root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"secret-bytes")
    (docs_root / "logo.png").symlink_to(outside)

    findings = copy_assets(docs_root, dest_root, source_name="imf-reader")

    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert "imf-reader" in findings[0].message
    assert "logo.png" in findings[0].message
    assert not (dest_root / "logo.png").exists()


def test_directory_symlink_cycle_does_not_hang(tmp_path: Path):
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    dest_root = tmp_path / "dest"
    nested = docs_root / "nested"
    nested.mkdir()
    (docs_root / "image.png").write_bytes(b"fake-png-bytes")
    # A directory symlink cycling back to an ancestor. Following it would recurse
    # forever; `copy_assets` must not follow it.
    (nested / "loop").symlink_to(docs_root, target_is_directory=True)

    findings = copy_assets(docs_root, dest_root, source_name="imf-reader")

    assert findings == []
    assert (dest_root / "image.png").is_file()


def test_markdown_is_left_alone(tmp_path: Path):
    docs_root = tmp_path / "docs"
    dest_root = tmp_path / "dest"
    docs_root.mkdir()
    (docs_root / "index.md").write_text("# Hello\n")

    findings = copy_assets(docs_root, dest_root, source_name="imf-reader")

    assert findings == []
    assert not (dest_root / "index.md").exists()
