"""Tests for dfo_docs.docsync.adapter: blocks, the push transform, and the baseline gate.

The fixtures under tests/docsync/fixtures/ are recorded Google Drive behaviour:

- `sampler.source.md` is a source page holding every construct the corpus uses, and
  `sampler.baseline.md` is Google's export after `to_doc_markdown(sampler.source.md)`
  was uploaded as a new Doc.
- `pages/<page>.source.md` is a hub page and `pages/<page>.baseline.md` the export of
  its `to_doc_markdown` upload; `pages/<page>.raw-export.md` is the export of the raw
  source uploaded unchanged.
- `probe/` holds the hand-written Doc-form upload (`sampler.doc.md`) and its exports.

Exports carry trailing whitespace that means something (a two-space hard break), so
these files must not pass through whitespace-trimming hooks.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from dfo_docs.docsync.adapter import (
    BaselineMismatchError,
    BlockError,
    Dialect,
    align_baseline,
    content_key,
    editor_text,
    export_content_key,
    lead_label,
    normalise,
    parse_blocks,
    rendered_text,
    to_doc_markdown,
)
from dfo_docs.docsync.blocks import Block, Kind

FIXTURES = Path(__file__).parent / "fixtures"
PAGES = ("get-data", "use-in-your-agent")


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def _source(text: str) -> tuple[Block, ...]:
    return parse_blocks(text, dialect=Dialect.SOURCE)


def _export(text: str) -> tuple[Block, ...]:
    return parse_blocks(text, dialect=Dialect.EXPORT)


def _find(blocks: tuple[Block, ...], text: str) -> Block:
    return next(block for block in blocks if block.text == text)


# The gate on recorded exports


def test_sampler_baseline_aligns_with_its_source() -> None:
    pairs = align_baseline(
        page="sampler",
        source=_read("sampler.source.md"),
        baseline=_read("sampler.baseline.md"),
    )

    # Every kind but a rule, which no recorded page holds.
    kinds = {pair.source.kind for pair in pairs}
    assert kinds == set(Kind) - {Kind.RULE}
    assert all(pair.source.family == pair.baseline.family for pair in pairs)


@pytest.mark.parametrize("page", PAGES)
def test_page_baseline_aligns_with_its_source(page: str) -> None:
    pairs = align_baseline(
        page=page,
        source=_read(f"pages/{page}.source.md"),
        baseline=_read(f"pages/{page}.baseline.md"),
    )

    assert len(pairs) > 20


def test_gate_refuses_an_export_of_the_raw_source() -> None:
    # Uploaded without the push transform, the front matter came back as a rule
    # and a heading.
    with pytest.raises(BaselineMismatchError) as caught:
        align_baseline(
            page="hub/get-started/get-data",
            source=_read("pages/get-data.source.md"),
            baseline=_read("pages/get-data.raw-export.md"),
        )

    error = caught.value
    assert error.index == 0
    assert error.source is not None
    assert error.source.kind is Kind.DESCRIPTION
    assert error.baseline is not None
    assert error.baseline.kind is Kind.RULE
    message = str(error)
    assert message.startswith("hub/get-started/get-data: block 0 ")
    assert "source description 'Search the DFO on /data" in message
    assert "baseline rule '' (line 1)" in message


def test_gate_names_a_text_mismatch() -> None:
    source = "# Title\n\nOne paragraph.\n"
    baseline = "# Title\n\nAn edited paragraph."

    with pytest.raises(BaselineMismatchError) as caught:
        align_baseline(page="hub/x", source=source, baseline=baseline)

    assert caught.value.index == 1
    assert str(caught.value) == (
        "hub/x: block 1 differs between the source and the Doc baseline:"
        " source paragraph 'One paragraph.' (line 3),"
        " baseline paragraph 'An edited paragraph.' (line 3)"
    )


def test_gate_prints_normalised_text_on_both_sides() -> None:
    source = "# Title\n\nSee [the guide](guide.md).\n"
    baseline = "# Title\n\nSee [the new guide](./guide.md)\\."

    with pytest.raises(BaselineMismatchError) as caught:
        align_baseline(page="hub/x", source=source, baseline=baseline)

    assert "source paragraph 'See [the guide](guide.md).'" in str(caught.value)
    assert "baseline paragraph 'See [the new guide](guide.md)\\\\.'" in str(
        caught.value
    )


@pytest.mark.parametrize(
    ("source", "exported"),
    [
        # Google escapes punctuation the source writes bare.
        ("The year ends 1960. Then more.", r"The year ends 1960\. Then more."),
        (
            "spec_id, Chat + Canvas, oda-* skills",
            r"spec\_id, Chat \+ Canvas, oda-\* skills",
        ),
        ("apis#981, Value = 0", r"apis\#981, Value \= 0"),
        ("(item 8)", r"(item 8\)"),
        # A source that escapes, or writes an entity, where Google shows the character.
        (r"Use \* as a wildcard.", r"Use \* as a wildcard."),
        ("Tom &amp; Jerry.", "Tom & Jerry."),
        ("Tom &amp; Jerry.", r"Tom \& Jerry."),
    ],
)
def test_gate_compares_rendered_text(source: str, exported: str) -> None:
    align_baseline(page="p", source=f"# T\n\n{source}\n", baseline=f"# T\n\n{exported}")


def test_gate_refuses_text_that_renders_differently() -> None:
    # A bare `*` pair is emphasis; an escaped one is literal.
    with pytest.raises(BaselineMismatchError):
        align_baseline(page="p", source="# T\n\n2*3*4\n", baseline=r"# T\n\n2\*3\*4")


def test_author_note_compares_in_its_doc_form() -> None:
    # sampler.baseline.md, line 14: an author note's `<dfo-site>`, uploaded escaped.
    source = "# T\n\n<!-- and <dfo-site>. -->\n"
    baseline = "# T\n\n**Author note:** and \\<dfo-site\\>."

    align_baseline(page="p", source=source, baseline=baseline)


def test_content_key_holds_kind_depth_heading_level_and_fence_info() -> None:
    page = "# T\n\n## Section\n\nText.\n\n```sh\nls\n```\n"

    assert export_content_key(page) == export_content_key(
        page.replace("Text.", r"Text\.")
    )
    for edited in (
        page.replace("## Section", "### Section"),
        page.replace("Text.", "- Text."),
        page.replace("Text.", "> Text."),
        page + "\n---\n",
        page.replace("```sh", "```python"),
    ):
        assert export_content_key(edited) != export_content_key(page)
    heading = _export(page)[1]
    assert content_key(heading, dialect=Dialect.EXPORT) == (
        "heading",
        0,
        2,
        "Section",
        "",
    )
    assert content_key(_export(page)[-1], dialect=Dialect.EXPORT)[-1] == "sh"


def test_rendered_text_of_a_fence_is_its_code() -> None:
    (fence,) = _source("```sh\necho hi\\.\n```\n")
    assert rendered_text(fence, dialect=Dialect.SOURCE) == "echo hi\\.\n"


def test_rule_is_a_block() -> None:
    blocks = _source("Text.\n\n---\n\n- item\n\n  ***\n")

    rules = [block for block in blocks if block.kind is Kind.RULE]
    assert [(rule.lines, rule.prefix, rule.depth) for rule in rules] == [
        ((2, 3), "", 0),
        ((6, 7), "  ", 1),
    ]


# editor_text: what a Doc edit writes into the source


@pytest.mark.parametrize(
    ("exported", "spliced"),
    [
        # An escape that only stops nothing is dropped.
        (r"The year ends 1960\. Then more.", "The year ends 1960. Then more."),
        (r"spec\_id and oda-\* skills", "spec_id and oda-* skills"),
        # An escape that keeps text literal stays: an opener keeps its escape.
        (r"Replace \<host\> in the URL.", r"Replace \<host> in the URL."),
        (r"Multiply 2\*3\*4 here.", r"Multiply 2\*3*4 here."),
        (r"\# not a heading", r"\# not a heading"),
        (r"\- not a list", r"\- not a list"),
        # Code spans are left alone.
        (r"`a\_b` and c\_d", r"`a\_b` and c_d"),
    ],
)
def test_editor_text_keeps_only_the_escapes_rendering_needs(
    exported: str, spliced: str
) -> None:
    assert editor_text(exported, markdown=True) == spliced


def test_editor_text_keeps_the_escapes_the_text_around_it_needs() -> None:
    # Inside a bold header cell's `**` a typed `*` keeps its escape, and so does a
    # `#` that ends a heading.
    assert editor_text(r"Task \*", markdown=True) == "Task *"
    assert editor_text(r"Task \*", markdown=True, around=("**", "**")) == r"Task \*"
    assert editor_text(r"copy a \#", markdown=True, around=("## ", "")) == r"copy a \#"


def test_editor_text_straightens_curly_quotes_outside_code() -> None:
    exported = "\u201cno sign-in\u201d isn\u2019t `\u2018x\u2019`"

    assert editor_text(exported, markdown=True) == '"no sign-in" isn\'t `\u2018x\u2019`'


def test_editor_text_of_plain_text_drops_every_escape() -> None:
    assert editor_text(r"see \<dfo-site\> and 2\*3\*4", markdown=False) == (
        "see <dfo-site> and 2*3*4"
    )


def test_gate_names_a_missing_block() -> None:
    with pytest.raises(BaselineMismatchError) as caught:
        align_baseline(page="hub/x", source="# Title\n\nText.\n", baseline="# Title")

    assert caught.value.index == 1
    assert caught.value.baseline is None
    assert "baseline <no block>" in str(caught.value)


def test_gate_compares_fences_exactly() -> None:
    source = "```bash\necho hi\n```\n"

    align_baseline(page="p", source=source, baseline="```sh\necho hi\n```")
    with pytest.raises(BaselineMismatchError):
        align_baseline(page="p", source=source, baseline="```\necho hi\\.\n```")


# normalise: one test per rule, with the export text Google produced


def test_normalise_keeps_escapes() -> None:
    # sampler.baseline.md, line 5: rendering reads the escape, so normalise keeps it.
    assert (
        normalise(r"The year ends 1960\. Then more.")
        == r"The year ends 1960\. Then more."
    )


def test_normalise_strips_the_scheme_google_adds_to_a_root_relative_link() -> None:
    # sampler.baseline.md, line 5: `[site link](/data)`
    assert normalise("a [site link](http:///data).") == "a [site link](/data)."


def test_normalise_strips_the_dot_slash_the_push_transform_adds() -> None:
    # sampler.baseline.md, line 5: `[bare link](what-a-skill-is.md)` uploaded as `./`
    assert normalise("a [bare link](./what-a-skill-is.md)") == (
        "a [bare link](what-a-skill-is.md)"
    )
    assert normalise("[up](../x.md)") == "[up](../x.md)"


def test_normalise_unlinks_a_bare_url_google_linked() -> None:
    # sampler.baseline.md, line 7
    exported = (
        r"A bare URL [https\://docs.one.org/methodologies/]"
        "(https://docs.one.org/methodologies/) and more."
    )
    assert normalise(r"[https\://x/a\_b](https://x/a_b)") == "https://x/a_b"
    assert (
        normalise(exported)
        == "A bare URL https://docs.one.org/methodologies/ and more."
    )
    assert normalise("[the site](https://one.org)") == "[the site](https://one.org)"


def test_normalise_unlinks_a_bare_address_google_linked() -> None:
    # sampler.baseline.md, line 7
    exported = "an address [data@one.org](mailto:data@one.org)."
    assert normalise(exported) == "an address data@one.org."
    assert normalise(r"[a\_b@one.org](mailto:a_b@one.org)") == "a_b@one.org"
    assert normalise("[write](mailto:a@one.org)") == "[write](mailto:a@one.org)"


def test_normalise_moves_a_code_span_trailing_space_back_inside() -> None:
    # sampler.baseline.md, line 7: `Bearer ` followed by the token
    exported = "header reads `Bearer`  followed by the token."
    assert normalise(exported) == "header reads `Bearer ` followed by the token."
    assert normalise("`a` b") == "`a` b"


def test_normalise_leaves_code_spans_alone() -> None:
    assert normalise("`[x](./y.md)` and [x](./y.md)") == "`[x](./y.md)` and [x](y.md)"


def test_normalise_drops_trailing_hard_break_spaces() -> None:
    assert normalise("An inserted paragraph.  ") == "An inserted paragraph."


# The export dialect


def test_export_splits_paragraphs_joined_by_a_hard_break() -> None:
    # probe/sampler.edited.md: a paragraph added with Enter in the Doc.
    blocks = _export("Then much more.  \nAn inserted paragraph.")

    assert [(block.kind, block.text) for block in blocks] == [
        (Kind.PARAGRAPH, "Then much more."),
        (Kind.PARAGRAPH, "An inserted paragraph."),
    ]


def test_leaves_after_a_hard_break_continue_the_one_before() -> None:
    text = "# T\n\nOne  \ntwo  \nthree.\n\nFour.\n"

    for blocks in (_source(text), _export(text)):
        assert [(block.text, block.after_break) for block in blocks] == [
            ("T", False),
            ("One", False),
            ("two", True),
            ("three.", True),
            ("Four.", False),
        ]


@pytest.mark.parametrize("heading", ["#", "##", "## "])
def test_an_emptied_export_heading_is_no_block(heading: str) -> None:
    blocks = _export(f"# T\n\n{heading}\n\nText.")

    assert [(block.kind, block.text) for block in blocks] == [
        (Kind.HEADING, "T"),
        (Kind.PARAGRAPH, "Text."),
    ]


def test_export_reads_merged_blockquotes_as_separate_leaves() -> None:
    # probe/sampler.export.md: the Tip and Note callouts came back as one quote.
    blocks = _export(
        "> **Tip:** Under the sentence.  \n>   \n> **Note:** First.  \n>   \n"
        "> Second.  \n> \n\n> - A list  \n> - Item\n\n>   \n"
        "> **Author note:** TODO: check 60\\.  \n> \n"
    )

    assert [(block.kind, block.text) for block in blocks] == [
        (Kind.CALLOUT, "Tip"),
        (Kind.CALLOUT_PARAGRAPH, "Under the sentence."),
        (Kind.CALLOUT, "Note"),
        (Kind.CALLOUT_PARAGRAPH, "First."),
        (Kind.BLOCKQUOTE, "Second."),
        (Kind.LIST_ITEM, "A list"),
        (Kind.LIST_ITEM, "Item"),
        (Kind.AUTHOR_NOTE, "TODO: check 60\\."),
    ]


def test_export_reads_doc_form_leads() -> None:
    blocks = _export(
        "**Description:** Search the DFO.\n\n# Title\n\n**Tab: For one project**\n\n"
        "**Author note:** TODO: a note."
    )

    assert [(block.kind, block.text) for block in blocks] == [
        (Kind.DESCRIPTION, "Search the DFO."),
        (Kind.HEADING, "Title"),
        (Kind.TAB_LABEL, "For one project"),
        (Kind.AUTHOR_NOTE, "TODO: a note."),
    ]


def test_export_reads_the_first_description_lead_wherever_it_stands() -> None:
    blocks = _export(
        "A line typed above.\n\n**Description:** Search the DFO.\n\n# Title\n\n"
        "**Description:** page text."
    )

    assert [(block.kind, block.text) for block in blocks] == [
        (Kind.PARAGRAPH, "A line typed above."),
        (Kind.DESCRIPTION, "Search the DFO."),
        (Kind.HEADING, "Title"),
        (Kind.PARAGRAPH, "**Description:** page text."),
    ]


def test_lead_label_names_the_first_lead_from_an_offset() -> None:
    assert lead_label("**Author note:** a", start=0) == "Author note"
    assert lead_label("**Author note:** a", start=1) is None
    assert lead_label("Text. **Note:** a **Tab: b**", start=1) == "Note"
    assert lead_label("Text **Tab: For one project**", start=1) == "Tab"
    assert lead_label("A **bold:** word and **Notes:** here", start=0) is None


def test_export_reads_a_bare_lead_as_an_empty_block() -> None:
    blocks = _export("**Description:**\n\n# Title\n\n- Item.\n\n  **Author note:**")

    assert [(block.kind, block.text) for block in blocks] == [
        (Kind.DESCRIPTION, ""),
        (Kind.HEADING, "Title"),
        (Kind.LIST_ITEM, "Item."),
        (Kind.AUTHOR_NOTE, ""),
    ]


def test_probe_export_aligns_with_the_doc_form_it_was_uploaded_from() -> None:
    uploaded = _export(_read("probe/sampler.doc.md"))
    exported = _export(_read("probe/sampler.export.md"))

    assert [block.family for block in exported] == [block.family for block in uploaded]
    differing = [
        (ours, theirs)
        for ours, theirs in zip(uploaded, exported, strict=True)
        if rendered_text(theirs, dialect=Dialect.EXPORT)
        != rendered_text(ours, dialect=Dialect.EXPORT)
    ]
    # Only the bare relative targets differ: Google wrote `x.md` as `http://x.md`,
    # which is why the push transform writes them as `./x.md`.
    assert len(differing) == 2
    assert all(
        "](http://what-a-skill-is.md)" in theirs.text
        or "](http://get-started/" in theirs.text
        for _, theirs in differing
    )
    assert all(
        rendered_text(
            replace(theirs, text=theirs.text.replace("](http://", "](")),
            dialect=Dialect.EXPORT,
        )
        == rendered_text(ours, dialect=Dialect.EXPORT)
        for ours, theirs in differing
    )


def test_probe_replace_exports_the_same_blocks_as_create() -> None:
    assert _export(_read("probe/sampler.baseline.md")) == _export(
        _read("probe/sampler.export.md")
    )


def test_export_refuses_raw_html() -> None:
    with pytest.raises(BlockError, match="raw HTML"):
        _export("<div>x</div>\n")


# The source block model


def test_source_blocks_carry_what_a_splice_needs() -> None:
    text = _read("sampler.source.md")
    blocks = _source(text)

    deep = _find(blocks, "Deep item i")
    assert (deep.kind, deep.prefix, deep.continuation, deep.depth) == (
        Kind.LIST_ITEM,
        "    - ",
        "      ",
        3,
    )
    callout = _find(blocks, "Second callout paragraph.")
    assert (callout.kind, callout.prefix, callout.continuation, callout.depth) == (
        Kind.CALLOUT_PARAGRAPH,
        "    ",
        "    ",
        1,
    )
    step = _find(blocks, "Run this from the project root:")
    assert (step.kind, step.prefix, step.depth) == (Kind.LIST_ITEM, "   ", 1)
    tab = _find(blocks, "For one project")
    assert (tab.kind, tab.depth) == (Kind.TAB_LABEL, 1)
    assert text[slice(*tab.span)] == '::tab{label="For one project"}'


def test_source_spans_hold_the_block_text() -> None:
    text = _read("sampler.source.md")
    lines = text.split("\n")

    for block in _source(text):
        raw = text[slice(*block.span)]
        first_line = lines[block.lines[0]]
        assert first_line.startswith(block.prefix), block
        assert text[: block.span[0]].endswith(block.prefix), block
        if block.kind is Kind.AUTHOR_NOTE:
            assert raw.startswith("<!--") and raw.endswith("-->"), block
        elif block.kind is Kind.FENCE:
            assert raw.startswith("```") and raw.endswith("```"), block
        elif block.kind is Kind.DESCRIPTION:
            assert raw.startswith(">-"), block
        elif block.kind not in {Kind.CALLOUT, Kind.TAB_LABEL}:
            assert " ".join(raw.split()) == block.text, block


def test_replacing_a_span_changes_only_that_block() -> None:
    text = _read("sampler.source.md")
    blocks = _source(text)
    editable = [
        index
        for index, block in enumerate(blocks)
        if block.family == "prose" or block.kind in {Kind.HEADING, Kind.TABLE_CELL}
    ]

    for index in editable:
        start, end = blocks[index].span
        edited = _source(text[:start] + "Edited words." + text[end:])
        assert [block.text for block in edited] == [
            "Edited words." if i == index else block.text
            for i, block in enumerate(blocks)
        ], blocks[index]


def test_trailing_comment_is_its_own_author_note() -> None:
    text = "1. Start a session. <!-- TODO: a note. -->\n"
    host, note = _source(text)

    assert (host.kind, host.text, text[slice(*host.span)]) == (
        Kind.LIST_ITEM,
        "Start a session.",
        "Start a session.",
    )
    assert (note.kind, note.text, note.continuation) == (
        Kind.AUTHOR_NOTE,
        "TODO: a note.",
        "   ",
    )
    assert text[slice(*note.span)] == "<!-- TODO: a note. -->"


@pytest.mark.parametrize(
    "text",
    ["Hide \\<!-- this --> and more.\n", "\\<!-- this -->\n"],
    ids=["mid-paragraph", "own-paragraph"],
)
def test_an_escaped_comment_opener_is_text(text: str) -> None:
    [block] = _source(text)

    assert (block.kind, block.text) == (Kind.PARAGRAPH, text.strip())
    assert to_doc_markdown(text) == text


def test_an_escaped_backslash_before_a_comment_opens_it() -> None:
    host, note = _source("Text \\\\<!-- a note -->\n")

    assert (host.text, note.kind, note.text) == (
        "Text \\\\",
        Kind.AUTHOR_NOTE,
        "a note",
    )


def test_table_cell_comment_follows_the_table() -> None:
    text = (
        "| Status | Meaning |\n| --- | --- |\n"
        "| `429` | Too many. <!-- TODO: thresholds. --> |\n| `413` | Too large. |\n"
        "\nAfter.\n"
    )
    blocks = _source(text)

    assert [(block.kind, block.text) for block in blocks] == [
        (Kind.TABLE_CELL, "Status"),
        (Kind.TABLE_CELL, "Meaning"),
        (Kind.TABLE_CELL, "`429`"),
        (Kind.TABLE_CELL, "Too many."),
        (Kind.TABLE_CELL, "`413`"),
        (Kind.TABLE_CELL, "Too large."),
        (Kind.AUTHOR_NOTE, "TODO: thresholds."),
        (Kind.PARAGRAPH, "After."),
    ]
    cell = blocks[3].cell
    assert cell is not None
    assert (cell.lines, cell.row, cell.column) == ((0, 4), 1, 1)


def test_bold_header_cell_text_is_inside_the_bold() -> None:
    # sampler.baseline.md, line 89: the header `**Task**` exports as `Task`.
    text = "| **Task** | Use |\n| --- | --- |\n| a | b |\n"
    header = _source(text)[0]

    assert header.text == "Task"
    assert text[slice(*header.span)] == "Task"
    assert header.cell is not None and header.cell.bold
    assert _export("| Task | Use |\n| :---- | :---- |\n| a | b |")[0].text == "Task"


def test_folded_description_is_the_yaml_value() -> None:
    text = "---\nname: x\ndescription: >-\n  One line\n  and two.\n---\n\n# X\n"
    description = _source(text)[0]

    assert (description.kind, description.text) == (
        Kind.DESCRIPTION,
        "One line and two.",
    )
    assert description.lines == (2, 5)
    assert text[slice(*description.span)] == ">-\n  One line\n  and two."


def test_single_line_description_span_is_the_scalar() -> None:
    text = "---\ndescription: Search the DFO.\n---\n"
    description = _source(text)[0]

    assert text[slice(*description.span)] == "Search the DFO."
    assert description.prefix == "description: "


def test_callout_marker_inside_a_fence_is_code() -> None:
    blocks = _source("```markdown\n!!! note\n    Body.\n```\n")

    assert [block.kind for block in blocks] == [Kind.FENCE]


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ('!!! note "Heads up"\n    Body.\n', "titled callout"),
        ("Text <!-- note --> and more.\n", "text after it"),
        ("<div>raw</div>\n", "raw HTML"),
        ("# T\n\n##\n\nText.\n", "line 3: an empty heading"),
    ],
)
def test_source_refuses_what_has_no_doc_form(text: str, problem: str) -> None:
    with pytest.raises(BlockError, match=problem):
        _source(text)


# The push transform


def test_to_doc_markdown_writes_the_doc_forms() -> None:
    source = (
        "---\ndescription: Search the DFO.\n---\n\n# Title\n\n"
        "See [the bundle](data/bundle.md), [up](../x.md) and [site](/data).\n\n"
        "!!! note\n    First. <!-- TODO: inline. -->\n\n    Second.\n\n"
        "<!-- TODO: standalone <x>. -->\n\n"
        '1. Copy.\n\n   :::tabs\n\n   ::tab{label="curl"}\n\n   ```bash\n   ls\n   ```\n\n'
        "   :::\n"
    )

    assert to_doc_markdown(source) == (
        "**Description:** Search the DFO.\n\n\n# Title\n\n"
        "See [the bundle](./data/bundle.md), [up](../x.md) and [site](/data).\n\n"
        "> **Note:** First.\n>\n> **Author note:** TODO: inline.\n>\n>\n> Second.\n\n"
        "\n**Author note:** TODO: standalone \\<x>.\n\n\n"
        "1. Copy.\n\n   \n\n   **Tab: curl**\n\n   ```bash\n   ls\n   ```\n\n   \n"
    )


def test_to_doc_markdown_opens_a_list_first_callout_with_its_label() -> None:
    source = "!!! warning\n    - A list first\n"

    assert to_doc_markdown(source) == "> **Warning:**\n>\n> - A list first\n"


def test_to_doc_markdown_leaves_fences_verbatim() -> None:
    source = "````markdown\n<!-- not a note -->\n[x](y.md)\n!!! note\n````\n"

    assert to_doc_markdown(source) == source


def test_to_doc_markdown_keeps_untouched_lines() -> None:
    source = _read("pages/use-in-your-agent.source.md")
    doc = to_doc_markdown(source).split("\n")

    untouched = [
        line
        for line in source.split("\n")
        if "<!--" not in line and "::" not in line and "](" not in line
    ][4:]
    assert all(line in doc for line in untouched)
