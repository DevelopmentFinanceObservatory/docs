"""Tests for dfo_docs.normalise: admonitions, fence tags, links, transclusion, and HTML
comments."""

import re
from pathlib import Path

import pytest

from dfo_docs.normalise import (
    NormaliseError,
    convert_admonitions,
    expand_transclusion,
    normalise_fence_tags,
    normalise_links,
    normalise_markdown,
    strip_html_comments,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "markdown"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_indented_admonition_with_title_converts():
    result = convert_admonitions(_read("indented_titled.md"))

    assert "!!!" not in result
    assert "> [!WARNING]" in result
    assert (
        "> **Heads up.** SDR and WEO order their date arguments differently." in result
    )
    # The heading that follows the admonition is untouched.
    assert "## What just happened" in result


def test_indented_admonition_without_title_converts():
    result = convert_admonitions(_read("indented_untitled.md"))

    assert "!!!" not in result
    assert "> [!NOTE]" in result
    assert (
        "> This package was published as `bblocks-datacommons-tools` until version 0.1.1, "
        "and imported" in result
    )
    # No title, so no bold lead sentence is fabricated.
    assert "**" not in result.split("> [!NOTE]")[1].split("\n\n")[0]


def test_unindented_admonition_folds_title_and_stops_at_paragraph_boundary():
    """The rule this settles on: the unindented body is the single contiguous run of

    non-blank lines immediately following the marker, stopping at the first blank line, heading,
    fence open, or end of file. Applied here to the real oda_reader DAC1 case.
    """
    result = convert_admonitions(_read("unindented_titled.md"))

    assert "!!!" not in result
    lines = result.split("\n")
    alert_start = lines.index("> [!WARNING]")
    # The alert body ends at the blank line before the next heading; the heading and the
    # paragraph after it are untouched, not folded into the alert.
    assert lines[alert_start + 1] == (
        "> **Heads up.** DAC1 is a zipped CSV, so `as_iterator=True` leaves peak memory "
        "unchanged. It reads the whole"
    )
    assert lines[alert_start + 5] == (
        "> what you accumulate chunk-by-chunk afterward is bounded."
    )
    assert lines[alert_start + 6] == ""
    assert lines[alert_start + 7] == "## DAC2b Bulk Download"


def test_admonition_inside_fence_is_not_converted():
    result = convert_admonitions(_read("admonition_in_fence.md"))

    # The literal example inside the fence survives untouched.
    assert '!!! warning "Heads up"' in result
    assert "must not be converted" in result
    # The real admonition outside the fence still converts.
    assert "> [!NOTE]" in result
    assert "> **Real one.** This one is outside the fence and should convert." in result


def test_fence_tags_py_becomes_python():
    result = normalise_fence_tags(_read("fence_tags.md"))

    assert "```py\n" not in result
    assert "```python\n" in result
    assert '```python title="Fetch data with labels"' in result
    # Other languages are untouched.
    assert "```bash" in result


def test_links_dialect_rewritten_others_untouched():
    result = normalise_links(_read("links_dialect.md"))

    assert "[earlier](getting-started.md#resolve-ambiguous-places)" in result
    assert "[`custom_mapping`](resolve-places.md#custom-mapping)" in result
    assert "[the changelog](changelog.md)" in result
    # The plain dialect needs no change.
    assert "[Caching](caching.md)" in result
    assert "../getting-started/" not in result
    assert "../resolve-places/" not in result


DIR_LINKS = FIXTURES / "dir_links"


def test_dir_link_from_normal_page_drops_one_up_segment():
    page_path = DIR_LINKS / "guides" / "setup.md"

    result = normalise_links(
        page_path.read_text(), page_path=page_path, docs_root=DIR_LINKS
    )

    assert "[earlier](getting-started.md)" in result


def test_dir_link_from_nested_index_keeps_its_up_segment():
    """From `guides/index.md`, `../getting-started/` must become `../getting-started.md`.

    A directory index renders one level shallower than a normal page, so it consumes
    one fewer `../` than a normal page's identical-looking link does.
    """
    page_path = DIR_LINKS / "guides" / "index.md"

    result = normalise_links(
        page_path.read_text(), page_path=page_path, docs_root=DIR_LINKS
    )

    assert "[earlier](../getting-started.md)" in result


def test_dir_link_from_index_does_not_silently_hit_a_same_named_sibling():
    """The wrong-target failure mode: `guides/getting-started.md` exists too.

    Without the index-aware depth rule, the rewrite drops the same one `../` it would
    for a normal page and produces `getting-started.md`, which resolves inside
    `guides/` to the decoy file instead of `../getting-started.md` beside it. Because a
    same-named sibling exists here, this failure is silent: lychee finds a file at the
    (wrong) target and never reports it.
    """
    page_path = DIR_LINKS / "guides" / "index.md"
    assert (DIR_LINKS / "guides" / "getting-started.md").is_file()
    assert (DIR_LINKS / "getting-started.md").is_file()

    result = normalise_links(
        page_path.read_text(), page_path=page_path, docs_root=DIR_LINKS
    )

    assert "[earlier](../getting-started.md)" in result
    assert "[earlier](getting-started.md)" not in result


def test_dir_link_depth_rule_holds_at_a_deeper_nesting():
    page_path = DIR_LINKS / "a" / "b" / "index.md"

    result = normalise_links(
        page_path.read_text(), page_path=page_path, docs_root=DIR_LINKS
    )

    assert "[deep](../../x.md)" in result


def test_dir_link_from_root_index_that_escapes_the_subtree_is_left_unrewritten():
    """A `../` link from a root-level `index.md` has nowhere left to go.

    Rewriting it would need more `../` segments than the page's own directory depth
    (zero, at the docs root) allows, so it is left as-is for the link checker.
    """
    page_path = DIR_LINKS / "index.md"

    result = normalise_links(
        page_path.read_text(), page_path=page_path, docs_root=DIR_LINKS
    )

    assert "[escaping](../elsewhere/)" in result


def test_dir_link_falls_back_to_normal_page_behaviour_without_docs_root():
    """Without `docs_root`, an index page is treated like a normal page (today's rule)."""
    page_path = DIR_LINKS / "guides" / "index.md"

    result = normalise_links(page_path.read_text(), page_path=page_path)

    assert "[earlier](getting-started.md)" in result


def test_extensionless_sibling_rewritten_when_target_file_exists():
    page_path = FIXTURES / "extensionless_siblings" / "index.md"

    result = normalise_links(page_path.read_text(), page_path=page_path)

    assert "[World Economic Outlook](./weo.md)" in result
    assert "[Debt Sustainability Analysis](./dsa.md)" in result
    assert "[World Bank](./world-bank.md)" in result
    assert "[International Debt Statistics](./ids.md)" in result
    assert "[Global Health Expenditure Database](./ghed.md)" in result
    assert "[UNAIDS](./unaids.md)" in result
    assert "[World Food Programme](./wfp.md)" in result


def test_extensionless_sibling_left_alone_when_target_file_is_missing():
    """`./hdi` has no `hdi.md` next to it (the real file is `hdr.md`), so it is a broken

    link in the source repository and must stay untouched so a link checker reports it.
    """
    page_path = FIXTURES / "extensionless_siblings" / "index.md"

    result = normalise_links(page_path.read_text(), page_path=page_path)

    assert "[Human Development Report](./hdi)" in result


def test_scheme_less_external_link_is_not_caught_by_the_sibling_rule():
    page_path = FIXTURES / "extensionless_siblings" / "index.md"

    result = normalise_links(page_path.read_text(), page_path=page_path)

    assert "[Comtrade database](comtrade.un.org)" in result


def test_extensionless_sibling_rule_does_not_fire_without_a_page_path():
    page_path = FIXTURES / "extensionless_siblings" / "index.md"

    result = normalise_links(page_path.read_text())

    assert "[World Economic Outlook](./weo)" in result


# --- Links into an excluded page -------------------------------------------------


def test_link_into_excluded_page_rewritten_to_docs_url(tmp_path):
    docs_root = tmp_path / "docs"
    (docs_root / "reference").mkdir(parents=True)
    page_path = docs_root / "index.md"
    text = "See [Query](reference/query.md) for details.\n"

    result = normalise_links(
        text,
        page_path=page_path,
        docs_root=docs_root,
        source_name="tossd-reader",
        excluded=("reference/query.md",),
        docs_url="https://onecampaign.github.io/tossd-reader/latest/",
    )

    assert (
        "[Query](https://onecampaign.github.io/tossd-reader/latest/reference/query/)"
        in result
    )


def test_link_into_excluded_page_from_nested_page_preserves_fragment(tmp_path):
    docs_root = tmp_path / "docs"
    (docs_root / "about").mkdir(parents=True)
    (docs_root / "reference").mkdir(parents=True)
    page_path = docs_root / "about" / "reconcile.md"
    text = "See [Verbs](../reference/verbs.md#reconcile-in-practice) for the list.\n"

    result = normalise_links(
        text,
        page_path=page_path,
        docs_root=docs_root,
        source_name="tossd-reader",
        excluded=("reference/verbs.md",),
        docs_url="https://onecampaign.github.io/tossd-reader/latest/",
    )

    assert (
        "[Verbs](https://onecampaign.github.io/tossd-reader/latest/"
        "reference/verbs/#reconcile-in-practice)" in result
    )


def test_link_to_a_page_not_excluded_is_left_untouched(tmp_path):
    docs_root = tmp_path / "docs"
    (docs_root / "reference").mkdir(parents=True)
    page_path = docs_root / "index.md"
    text = "See [Helpers](reference/helpers.md) and [Query](reference/query.md).\n"

    result = normalise_links(
        text,
        page_path=page_path,
        docs_root=docs_root,
        source_name="tossd-reader",
        excluded=("reference/query.md",),
        docs_url="https://onecampaign.github.io/tossd-reader/latest/",
    )

    # Only the excluded target is rewritten; the sibling reference page stays a
    # corpus-relative link because it is not in `excluded`.
    assert "[Helpers](reference/helpers.md)" in result
    assert "reference/query.md" not in result


def test_link_into_excluded_page_without_docs_url_raises(tmp_path):
    docs_root = tmp_path / "docs"
    (docs_root / "reference").mkdir(parents=True)
    page_path = docs_root / "index.md"
    text = "See [Query](reference/query.md) for details.\n"

    with pytest.raises(
        NormaliseError, match=r"tossd-reader.*index\.md.*reference/query\.md"
    ):
        normalise_links(
            text,
            page_path=page_path,
            docs_root=docs_root,
            source_name="tossd-reader",
            excluded=("reference/query.md",),
            docs_url=None,
        )


def test_normalise_markdown_threads_exclusion_context_through(tmp_path):
    repo_root = tmp_path
    docs_root = tmp_path / "docs"
    (docs_root / "reference").mkdir(parents=True)
    page_path = docs_root / "index.md"
    text = "See [Query](reference/query.md) for details.\n"

    result = normalise_markdown(
        text,
        repo_root=repo_root,
        page_path=page_path,
        docs_root=docs_root,
        source_name="tossd-reader",
        excluded=("reference/query.md",),
        docs_url="https://onecampaign.github.io/tossd-reader/latest/",
    )

    assert (
        "[Query](https://onecampaign.github.io/tossd-reader/latest/reference/query/)"
        in result
    )


def test_transclusion_expands_against_repo_root():
    repo_root = FIXTURES / "transclusion" / "repo"
    text = (repo_root / "docs" / "page.md").read_text()

    result = expand_transclusion(text, repo_root=repo_root)

    assert "Open a pull request against `main`." in result
    assert "--8<--" not in result


def test_transclusion_missing_target_raises(tmp_path):
    (tmp_path / "docs").mkdir()
    page = tmp_path / "docs" / "page.md"
    page.write_text('--8<-- "MISSING.md"\n')

    with pytest.raises(NormaliseError, match=re.escape("MISSING.md")):
        expand_transclusion(page.read_text(), repo_root=tmp_path)


def test_transclusion_inside_fence_left_alone():
    text = '```text\n--8<-- "example.md"\n```\n'

    result = expand_transclusion(text, repo_root=Path("/does/not/matter"))

    assert result == text


def test_normalise_markdown_runs_all_transforms_in_order(tmp_path):
    repo_root = tmp_path
    (repo_root / "CONTRIBUTING.md").write_text("Send a pull request.\n")
    text = (
        '--8<-- "CONTRIBUTING.md"\n'
        "\n"
        '!!! note "Heads up"\n'
        "    See [earlier](../getting-started/#anchor) for background.\n"
        "\n"
        "```py\n"
        "print(1)\n"
        "```\n"
    )

    result = normalise_markdown(text, repo_root=repo_root)

    assert "Send a pull request." in result
    assert "> [!NOTE]" in result
    assert "getting-started.md#anchor" in result
    assert "```python" in result


def test_normalise_markdown_passes_docs_root_through_to_the_dir_link_rewrite(tmp_path):
    repo_root = tmp_path
    docs_root = tmp_path / "docs"
    (docs_root / "guides").mkdir(parents=True)
    page_path = docs_root / "guides" / "index.md"
    text = "See [earlier](../getting-started/) for background.\n"

    result = normalise_markdown(
        text, repo_root=repo_root, page_path=page_path, docs_root=docs_root
    )

    assert "[earlier](../getting-started.md)" in result


def test_transclusion_target_outside_repo_root_raises(tmp_path):
    """A `../` target must not read a file the source repository does not own.

    Transclusion targets come from fetched third-party markdown and the expansion is
    published to a public corpus, so an escaping path would leak a build-host file.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (tmp_path / "secret.txt").write_text("sensitive")

    with pytest.raises(NormaliseError, match="resolves outside"):
        expand_transclusion('--8<-- "../secret.txt"', repo_root=repo_root)


def test_transclusion_absolute_target_raises(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    with pytest.raises(NormaliseError, match="resolves outside"):
        expand_transclusion('--8<-- "/etc/hosts"', repo_root=repo_root)


def test_whole_line_comment_between_blank_lines_leaves_one_blank_line():
    text = "Para one.\n\n<!-- note -->\n\nPara two.\n"

    assert strip_html_comments(text) == "Para one.\n\nPara two.\n"


def test_whole_line_comment_between_text_lines_keeps_the_paragraphs_apart():
    # CommonMark ends "Intro." at the comment's HTML block, so "More." is a new
    # paragraph. Dropping the line outright would merge the two.
    text = "Intro.\n<!-- TODO: check this -->\nMore.\n"

    assert strip_html_comments(text) == "Intro.\n\nMore.\n"


def test_multi_line_comment_between_text_lines_leaves_one_blank_line():
    text = "Before.\n<!--\nA note\nover lines.\n-->\nAfter.\n"

    assert strip_html_comments(text) == "Before.\n\nAfter.\n"


def test_whole_line_comment_inside_a_blockquote_leaves_a_quoted_blank_line():
    text = "> First.\n> <!-- note -->\n> Second.\n"

    assert strip_html_comments(text) == "> First.\n>\n> Second.\n"


def test_comment_opening_the_page_drops_the_blank_line_after_it():
    text = "<!-- note -->\n\n# Title\n"

    assert strip_html_comments(text) == "# Title\n"


def test_mid_line_comment_takes_the_whitespace_before_it():
    text = "- The Tools reference lists every argument. <!-- TODO: link it. -->\n"

    assert strip_html_comments(text) == "- The Tools reference lists every argument.\n"


def test_mid_line_comment_between_words_leaves_one_space():
    assert strip_html_comments("text <!-- x --> more\n") == "text more\n"


def test_comment_touching_the_next_word_keeps_the_space_before_it():
    assert strip_html_comments("Use the <!-- x -->API now.\n") == "Use the API now.\n"


def test_multi_line_comment_touching_the_next_word_keeps_the_space_before_it():
    text = "Some text <!--\nnote\n-->more text\n"

    assert strip_html_comments(text) == "Some text more text\n"


def test_comment_ending_the_text_takes_the_whitespace_before_it():
    assert strip_html_comments("text <!-- x -->") == "text"


def test_comment_in_a_table_cell_leaves_the_cell_valid():
    text = (
        "| Code | Meaning |\n"
        "| ---- | ------- |\n"
        "| `429` | Too many requests. <!-- TODO: thresholds. --> |\n"
    )

    result = strip_html_comments(text)

    assert result.splitlines()[2] == "| `429` | Too many requests. |"


def test_two_comments_on_one_line_are_both_dropped():
    text = "One <!-- a --> two <!-- b --> three.\n"

    assert strip_html_comments(text) == "One two three.\n"


def test_indented_line_opening_comment_keeps_the_following_text_indented():
    text = "1. Step.\n\n    <!-- prettier-ignore -->\n    !!! warning\n"

    assert strip_html_comments(text) == "1. Step.\n\n    !!! warning\n"


def test_comment_opening_a_quoted_line_keeps_the_marker_and_the_text():
    text = "> <!-- note --> Body.\n"

    assert strip_html_comments(text) == "> Body.\n"


def test_comment_across_quoted_lines_is_dropped_whole():
    text = "> Text <!-- a\n> b --> more.\n"

    assert strip_html_comments(text) == "> Text more.\n"


def test_dropping_a_comment_ending_a_blockquote_leaves_no_empty_quote_line():
    text = "> [!NOTE]\n> Body.\n>\n> <!-- TODO: verify. -->\n\n## Next\n"

    assert strip_html_comments(text) == "> [!NOTE]\n> Body.\n\n## Next\n"


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("```html\n<!-- markup comment -->\n```\n", id="backtick-fence"),
        pytest.param("~~~html\n<!-- keep -->\n~~~\n", id="tilde-fence"),
        pytest.param(
            "````markdown\n```html\n<!-- keep -->\n```\n````\n", id="nested-fence"
        ),
        pytest.param("    <!-- indented code -->\n", id="indented-code"),
        pytest.param(
            "Write ``<!-- TODO -->`` to leave a note, or `<!--` alone.\n",
            id="code-span",
        ),
        pytest.param(
            "The opener is `<!--` and the closer is -->.\n", id="opener-in-code-span"
        ),
        pytest.param("\\<!-- escaped --> is text.\n", id="escaped-opener"),
    ],
)
def test_comment_text_inside_code_or_escaped_is_kept(text):
    assert strip_html_comments(text) == text


def test_unclosed_comment_inside_a_tilde_fence_is_code():
    text = "~~~html\n<!-- open\n~~~\n"

    assert strip_html_comments(text) == text


def test_backtick_fence_info_with_a_backtick_is_inline_code():
    # "```foo```" cannot open a fence, so the first comment is prose and the second is
    # inside a real fence.
    text = "```foo``` is code <!-- x -->\n\n```html\n<!-- keep -->\n```\n"

    assert (
        strip_html_comments(text)
        == "```foo``` is code\n\n```html\n<!-- keep -->\n```\n"
    )


def test_unclosed_backtick_in_a_heading_does_not_hide_a_comment():
    text = "# A ` tick\nText <!-- x --> more ` end\n"

    assert strip_html_comments(text) == "# A ` tick\nText more ` end\n"


def test_unclosed_backtick_in_a_list_item_does_not_hide_a_comment():
    text = "- a `b\n- <!-- x --> c`\n"

    assert strip_html_comments(text) == "- a `b\n- c`\n"


def test_comment_opened_outside_a_fence_runs_across_it():
    text = "Before.\n<!--\n```python\nprint(1)\n```\n-->\nAfter.\n"

    assert strip_html_comments(text) == "Before.\n\nAfter.\n"


def test_front_matter_is_left_alone_and_the_body_is_stripped():
    text = "---\ntitle: A <!-- not markdown -->\n---\n\nBody. <!-- note -->\n"

    assert (
        strip_html_comments(text)
        == "---\ntitle: A <!-- not markdown -->\n---\n\nBody.\n"
    )


def test_unclosed_comment_raises_quoting_it():
    text = "Fine.\n\nThen <!-- this never closes.\n"

    with pytest.raises(
        NormaliseError, match=re.escape("'guide.md': HTML comment '<!-- this never")
    ):
        strip_html_comments(text, page="'guide.md'")


def test_unclosed_comment_block_raises():
    with pytest.raises(NormaliseError, match="never closes"):
        strip_html_comments("Fine.\n\n<!-- open\n\nMore.\n")


def test_unclosed_comment_quote_stops_at_sixty_characters():
    text = "<!-- " + "x" * 100 + "\n"

    with pytest.raises(NormaliseError) as raised:
        strip_html_comments(text)

    assert repr("<!-- " + "x" * 55) in str(raised.value)


def test_comment_text_also_in_a_code_span_of_the_same_block_raises():
    text = "Write `<!-- x -->` like this: <!-- x -->\n"

    with pytest.raises(NormaliseError, match=r"'guide\.md'.*'<!-- x -->'.*code"):
        strip_html_comments(text, page="'guide.md'")


def test_comment_text_in_a_code_span_of_another_block_is_fine():
    text = "Write `<!-- x -->` like this.\n\nNote. <!-- x -->\n"

    assert strip_html_comments(text) == "Write `<!-- x -->` like this.\n\nNote.\n"


def test_unterminated_comment_through_normalise_markdown_names_source_and_file(
    tmp_path,
):
    docs_root = tmp_path / "docs"

    with pytest.raises(NormaliseError, match=re.escape("'dfo-apis': 'how/page.md'")):
        normalise_markdown(
            "<!-- open\n",
            repo_root=tmp_path,
            page_path=docs_root / "how" / "page.md",
            docs_root=docs_root,
            source_name="dfo-apis",
        )


def test_normalise_markdown_strips_a_comment_from_transcluded_text(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text("Release notes. <!-- TODO: date -->\n")
    text = '# Changes\n\n--8<-- "CHANGELOG.md"\n'

    result = normalise_markdown(text, repo_root=tmp_path)

    assert result.rstrip("\n") == "# Changes\n\nRelease notes."


def test_normalise_markdown_strips_a_comment_from_an_admonition_body(tmp_path):
    text = "!!! note\n\n    Body.\n\n    <!-- TODO: verify. -->\n\n## Next\n"

    result = normalise_markdown(text, repo_root=tmp_path)

    assert result == "> [!NOTE]\n> Body.\n\n## Next\n"


def test_comment_inside_a_raw_html_block_is_removed():
    text = "Before.\n\n<div>\n<!-- TODO: fill in -->\n<p>Kept.</p>\n</div>\n\nAfter.\n"

    assert (
        strip_html_comments(text)
        == "Before.\n\n<div>\n<p>Kept.</p>\n</div>\n\nAfter.\n"
    )


def test_unclosed_comment_inside_a_raw_html_block_raises():
    with pytest.raises(NormaliseError, match="never closes"):
        strip_html_comments("<div>\n<!-- open\n</div>\n")


@pytest.mark.parametrize("tag", ["script", "style", "textarea"])
def test_comment_text_inside_a_raw_text_element_stays(tag):
    text = f"<{tag}>\n<!-- not a comment here\n</{tag}>\n"

    assert strip_html_comments(text) == text
