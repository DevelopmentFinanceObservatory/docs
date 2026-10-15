"""Tests for dfo_docs.docsync.edits: Doc edits onto the source, and the merge.

`fixtures/edits/<page>.edited.md` is Google's export of a Doc uploaded from
`to_doc_markdown(<source>)` after scripted Docs API edits (replaceAllText, insertText,
deleteContentRange); its baseline is the recorded `sampler.baseline.md` or
`pages/<page>.baseline.md`, which the upload reproduced byte for byte.
`<page>.expected.md` is the source with exactly those edits made by hand.
`pages/conventions.*` is a page from the apis repository and its recorded baseline,
which holds Author notes on lines of their own and in table cells.
`pages/use-studio.*`, `pages/connect.*` and `pages/methods.*` are pages from the hub
and the ai repository with their recorded baselines, holding Author notes beside
paragraphs, tabs and code blocks.
`pages/conventions-live.*` is an earlier version of that page, its recorded
baseline, and Google's export after an editor resolved a TODO note, pressed Enter at
the end of a paragraph and typed a sentence, and typed a paragraph below the page's
final list.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dfo_docs.docsync.adapter import align_baseline, to_doc_markdown
from dfo_docs.docsync.blocks import Kind
from dfo_docs.docsync.edits import (
    Clash,
    EditResult,
    ReportKind,
    apply_edits,
    heading_anchor,
    merge_onto_current,
)

FIXTURES = Path(__file__).parent / "fixtures"
RECORDED = {
    "sampler": ("sampler.source.md", "sampler.baseline.md"),
    "get-data": ("pages/get-data.source.md", "pages/get-data.baseline.md"),
    "use-in-your-agent": (
        "pages/use-in-your-agent.source.md",
        "pages/use-in-your-agent.baseline.md",
    ),
    "conventions": ("pages/conventions.source.md", "pages/conventions.baseline.md"),
    "conventions-live": (
        "pages/conventions-live.source.md",
        "pages/conventions-live.baseline.md",
    ),
    "use-studio": ("pages/use-studio.source.md", "pages/use-studio.baseline.md"),
    "connect": ("pages/connect.source.md", "pages/connect.baseline.md"),
    "methods": ("pages/methods.source.md", "pages/methods.baseline.md"),
}


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def _recorded(page: str, edited: str) -> EditResult:
    source, baseline = RECORDED[page]
    return apply_edits(
        page=page, source=_read(source), baseline=_read(baseline), edited=edited
    )


def _edit(text: str, *replacements: tuple[str, str]) -> str:
    for old, new in replacements:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    return text


def _sampler(*replacements: tuple[str, str]) -> EditResult:
    return _recorded("sampler", _edit(_read("sampler.baseline.md"), *replacements))


def _local(source: str, *replacements: tuple[str, str]) -> EditResult:
    """Edit the Doc form of a small source page, standing in for its export."""
    baseline = to_doc_markdown(source)
    return apply_edits(
        page="p",
        source=source,
        baseline=baseline,
        edited=_edit(baseline, *replacements),
    )


def _kinds(result: EditResult) -> list[tuple[ReportKind, str]]:
    return [(report.kind, report.block.text) for report in result.reports]


# Recorded Doc edits


def test_sampler_edits_apply_exactly() -> None:
    result = _recorded("sampler", _read("edits/sampler.edited.md"))

    assert result.text == _read("edits/sampler.expected.md")
    assert [(report.kind, report.message) for report in result.reports] == [
        (
            ReportKind.FOLDED_DESCRIPTION,
            "a folded description is not rewritten; edit the front matter",
        ),
        (
            ReportKind.HEADING_ANCHOR,
            "anchor #step-2-change-the-years is now #step-2-change-the-year-range",
        ),
        _beside_text("an Author note")[:2],
        _beside_text("an Author note")[:2],
        (
            ReportKind.CODE_EDIT,
            "code edits are not applied; change the code in the source",
        ),
    ]
    assert [report.block.text for report in result.reports[2:4]] == [
        "TODO: a top-level author note with `code`, a [link](../build/share.md) and"
        " <dfo-site>.",
        "TODO: an inline note in a callout.",
    ]
    assert result.reports[4].block.kind is Kind.FENCE


def test_get_data_edits_apply_exactly() -> None:
    result = _recorded("get-data", _read("edits/get-data.edited.md"))

    assert result.text == _read("edits/get-data.expected.md")
    assert _kinds(result) == [
        (ReportKind.HEADING_ANCHOR, "Step 3: check the table"),
        (ReportKind.CODE_EDIT, result.reports[1].block.text),
    ]
    assert "README.md" in result.reports[1].block.text


@pytest.mark.parametrize("page", RECORDED)
def test_an_unedited_doc_leaves_the_source_unchanged(page: str) -> None:
    source, baseline = RECORDED[page]

    result = _recorded(page, _read(baseline))

    assert result.text == _read(source)
    assert result.reports == ()


# Changed blocks


def test_single_line_description_is_re_emitted_as_yaml() -> None:
    source = "---\ndescription: Search the DFO.\ntitle: X\n---\n\n# X\n"

    result = _local(source, ("Search the DFO.", "Search: the DFO"))

    assert result.text == (
        "---\ndescription: 'Search: the DFO'\ntitle: X\n---\n\n# X\n"
    )


def test_author_note_edit_is_a_comment_at_its_prefix() -> None:
    result = _sampler(("a standalone note inside", "a note inside"))

    assert "\n  <!-- TODO: a note inside a list item -->\n" in result.text


def test_author_note_cannot_close_itself() -> None:
    result = _sampler(("a standalone note inside", "a note --> inside"))

    assert result.text == _read("sampler.source.md")
    assert _kinds(result) == [
        (ReportKind.NOT_APPLIED, "TODO: a standalone note inside a list item")
    ]


NOTE = (
    "**Author note:** TODO: a top-level author note with `code`, a"
    " [link](../build/share.md) and \\<dfo-site\\>."
)
NOTE_COMMENT = (
    "<!-- TODO: a top-level author note with `code`, a [link](../build/share.md)"
    " and <dfo-site>. -->"
)
NOTE_TO_TEXT = (
    ReportKind.NOTE_LABEL,
    "an Author note became page text; check it belongs on the site",
    "",
)
TEXT_TO_NOTE = (
    ReportKind.NOTE_LABEL,
    "a paragraph became an Author note and leaves the site",
    "",
)
MISPLACED_NOTE = "the Author note label is not at the start of a paragraph"


def _beside_text(what: str) -> tuple[ReportKind, str, str]:
    """The flag on a region that changed a note or the description and page text."""
    return (
        ReportKind.NOTE_LABEL,
        f"{what} and the page text beside it changed together; check no text moved"
        " between them",
        "",
    )


def _messages(result: EditResult) -> list[tuple[ReportKind, str, str]]:
    return [(report.kind, report.message, report.quote) for report in result.reports]


def _refused(reason: str, doc: str) -> tuple[ReportKind, str, str]:
    """The report of a region left unchanged, quoting the Doc's text."""
    return (
        ReportKind.REFUSED,
        f"{reason}; this part of the page is not changed",
        doc,
    )


@pytest.mark.parametrize(
    ("relabelled", "written"),
    [
        (
            NOTE.removeprefix("**Author note:** "),
            "TODO: a top-level author note with `code`, a [link](../build/share.md)"
            " and \\<dfo-site>.",
        ),
        (
            NOTE.replace("**Author note:**", "Author note:"),
            "Author note: TODO: a top-level author note with `code`, a"
            " [link](../build/share.md) and \\<dfo-site>.",
        ),
        (
            NOTE.replace("**Author note:**", "**Author's note:**"),
            "**Author's note:** TODO: a top-level author note with `code`, a"
            " [link](../build/share.md) and \\<dfo-site>.",
        ),
    ],
    ids=["deleted", "unbolded", "renamed"],
)
def test_a_removed_author_note_label_publishes_the_note(
    relabelled: str, written: str
) -> None:
    result = _sampler((NOTE, relabelled))

    assert result.text == _edit(_read("sampler.source.md"), (NOTE_COMMENT, written))
    assert _messages(result) == [NOTE_TO_TEXT]
    assert result.reports[0].block.kind is Kind.AUTHOR_NOTE


@pytest.mark.parametrize(
    ("note", "answer"),
    [
        (
            "TODO: add the public base URL once the API access policy exists.",
            "The public base URL is https://api.one.org once the API access"
            " policy exists.",
        ),
        (
            "TODO: document the key scheme once the API access policy exists.",
            "Each key is a bearer token; the API access policy sets the key scheme.",
        ),
    ],
    ids=["base-url", "key-scheme"],
)
def test_a_note_resolved_in_place_becomes_page_text(note: str, answer: str) -> None:
    baseline = _read("pages/conventions.baseline.md")

    result = _recorded(
        "conventions", _edit(baseline, (f"**Author note:** {note}", answer))
    )

    assert result.text == _edit(
        _read("pages/conventions.source.md"), (f"<!-- {note} -->", answer)
    )
    assert _messages(result) == [NOTE_TO_TEXT]


def test_a_table_cell_note_resolved_in_place_follows_the_table() -> None:
    note = "TODO: rate-limit thresholds; set in proxy config, not recorded in the apis repository."
    answer = "The rate limit is 10 calls per second, set in the proxy config."
    source = _read("pages/conventions.source.md")
    table_end = (
        "Send `Content-Type: application/json`."
        " <!-- TODO: accepted media types; set in proxy config. --> |\n"
    )

    result = _recorded(
        "conventions",
        _edit(
            _read("pages/conventions.baseline.md"), (f"**Author note:** {note}", answer)
        ),
    )

    assert result.text == _edit(
        source,
        (
            f"Too many requests. <!-- {note} -->",
            "Too many requests." + " " * (len(note) + 10),
        ),
        (table_end, f"{table_end}\n{answer}\n"),
    )
    assert _messages(result) == [NOTE_TO_TEXT]


@pytest.mark.parametrize(
    ("note", "host"),
    [
        (
            "> **Author note:** TODO: an inline note in a callout.",
            "    First callout paragraph with 60 observations.",
        ),
        (
            "   **Author note:** TODO: an inline note on a list item.",
            "1. Start a new Claude Code session.",
        ),
    ],
    ids=["callout", "list-item"],
)
def test_a_removed_inline_note_label_adds_a_paragraph_after_its_line(
    note: str, host: str
) -> None:
    text = note.split("**Author note:** ")[1]
    source = _read("sampler.source.md")
    continuation = " " * (len(host) - len(host.lstrip(" 0123456789.")))

    result = _sampler((note, note.replace("**Author note:** ", "")))

    assert result.text == _edit(
        source, (f"{host} <!-- {text} -->\n", f"{host}\n\n{continuation}{text}\n")
    )
    assert _messages(result) == [NOTE_TO_TEXT]


@pytest.mark.parametrize(
    ("page", "paragraph"),
    [
        (
            "sampler",
            "Escapes Google adds: spec\\_id, Chat \\+ Canvas, oda-\\* skills, apis\\#981,"
            " (item 8), Value \\= 0\\.",
        ),
        ("conventions", "Bundles carry a reproducing call"),
    ],
    ids=["sampler", "conventions"],
)
def test_a_paragraph_given_the_note_label_becomes_a_note(
    page: str, paragraph: str
) -> None:
    source, baseline = (_read(name) for name in RECORDED[page])
    line = next(line for line in source.split("\n") if line.startswith(paragraph[:20]))

    result = _recorded(
        page, _edit(baseline, (paragraph, f"**Author note:** {paragraph}"))
    )

    assert result.text == _edit(source, (f"\n{line}\n", f"\n<!-- {line} -->\n"))
    assert _messages(result) == [TEXT_TO_NOTE]


def test_a_new_author_note_paragraph_becomes_a_note_with_no_report() -> None:
    result = _sampler(("## Next\n", "**Author note:** new hidden note\n\n## Next\n"))

    assert result.text == _edit(
        _read("sampler.source.md"),
        ("## Next\n", "<!-- new hidden note -->\n\n## Next\n"),
    )
    assert result.reports == ()


LABELLED = (
    "# T\n\nThe panel shows the totals.\n\n"
    "<!-- TODO: verify on the staging site that the panel shows the totals. -->"
    "\n\nEnd.\n"
)
LABELLED_NOTE = (
    "**Author note:** TODO: verify on the staging site that the panel shows the totals."
)


@pytest.mark.parametrize(
    ("join", "message"),
    [
        (
            ("totals.\n\n\n**Author note:**", "totals. **Author note:**"),
            _refused(MISPLACED_NOTE, f"The panel shows the totals. {LABELLED_NOTE}"),
        ),
        (
            ("End.", "End. **Description:** X"),
            _refused(
                "the Description label is not at the start of a paragraph",
                "End. **Description:** X",
            ),
        ),
        (
            ("End.", "End. **Note:** X"),
            _refused(
                "the Note label is not at the start of a paragraph", "End. **Note:** X"
            ),
        ),
        (
            ("End.", "End. **Tab: X**"),
            _refused(
                "the Tab label is not at the start of a paragraph", "End. **Tab: X**"
            ),
        ),
        (
            ("# T", "# **Author note:** T"),
            _refused(MISPLACED_NOTE, "# **Author note:** T"),
        ),
        (
            ("totals.\n\n\nEnd.", "totals. **Author note:** End."),
            _refused(MISPLACED_NOTE, f"{LABELLED_NOTE} **Author note:** End."),
        ),
    ],
    ids=["note", "description", "callout", "tab", "heading", "note-in-note"],
)
def test_a_label_inside_a_paragraph_changes_nothing(
    join: tuple[str, str], message: tuple[ReportKind, str]
) -> None:
    result = _local(LABELLED, join)

    assert result.text == LABELLED
    assert _messages(result) == [message]


@pytest.mark.parametrize(
    ("page", "join"),
    [
        (
            "sampler",
            ("second line.\n\n**Author note:**", "second line. **Author note:**"),
        ),
        (
            "conventions",
            (
                "answers without it.\n\n**Author note:** TODO: document",
                "answers without it. **Author note:** TODO: document",
            ),
        ),
    ],
)
def test_a_note_joined_onto_the_paragraph_before_changes_nothing(
    page: str, join: tuple[str, str]
) -> None:
    source, baseline = (_read(name) for name in RECORDED[page])

    result = _recorded(page, _edit(baseline, join))

    assert result.text == source
    [(kind, message, quote)] = _messages(result)
    assert kind is ReportKind.REFUSED
    assert message == f"{MISPLACED_NOTE}; this part of the page is not changed"
    assert join[1] in quote


DESCRIPTION = (
    "Search the DFO on /data in plain language, adjust the result, then download"
    " it as a CSV or copy a link."
)


@pytest.mark.parametrize(
    "relabelled",
    ["Search", "Description: Search", "**Summary:** Search"],
    ids=["deleted", "unbolded", "renamed"],
)
def test_a_changed_description_label_keeps_the_description(relabelled: str) -> None:
    result = _sampler(("**Description:** Search", relabelled))

    assert result.text == _read("sampler.source.md")
    assert _messages(result) == [
        _refused(
            "the Description label was removed or changed",
            relabelled.removesuffix("Search") + DESCRIPTION,
        )
    ]


@pytest.mark.parametrize(
    ("typed", "written"),
    [("A new first line.", "A new first line."), ("**Author note:** x", "<!-- x -->")],
    ids=["paragraph", "note"],
)
def test_a_paragraph_typed_above_the_description_is_page_text(
    typed: str, written: str
) -> None:
    result = _sampler(
        ("**Description:** Search", f"{typed}\n\n**Description:** Search")
    )

    assert result.text == _edit(
        _read("sampler.source.md"), ("# Sampler page", f"{written}\n\n# Sampler page")
    )
    assert result.reports == ()


@pytest.mark.parametrize(
    ("source", "edit", "message"),
    [
        (
            "# T\n\nIntro.\n\n<!-- TODO: check this -->\n\nShort para.\n\nEnd.\n",
            ("check this\n\n\nShort para.", "check this Short para."),
            _refused(
                "text was joined onto or split off an Author note",
                "**Author note:** TODO: check this Short para.",
            ),
        ),
        (
            "# T\n\nIntro.\n\n<!-- TODO: check -->\n\n## Access\n\nEnd.\n",
            ("check\n\n\n## Access", "check Access"),
            _refused(
                "text was joined onto or split off an Author note",
                "**Author note:** TODO: check Access",
            ),
        ),
        (
            "# T\n\nIntro.\n\n<!-- TODO: verify it. It comes from the APIs. -->\n\nEnd.\n",
            ("verify it. It", "verify it.  \nIt"),
            _refused(
                "text was joined onto or split off an Author note",
                "**Author note:** TODO: verify it.\n\nIt comes from the APIs.",
            ),
        ),
        (
            "---\ndescription: Short summary.\n---\n\nIntro paragraph.\n\nEnd.\n",
            (
                "Short summary.\n\n\nIntro paragraph.",
                "Short summary. Intro paragraph.",
            ),
            _refused(
                "text was joined onto or split off the Description",
                "**Description:** Short summary. Intro paragraph.",
            ),
        ),
    ],
    ids=["paragraph", "heading", "enter", "description"],
)
def test_text_joined_onto_or_split_off_a_note_changes_nothing(
    source: str, edit: tuple[str, str], message: tuple[ReportKind, str]
) -> None:
    result = _local(source, edit)

    assert result.text == source
    assert _messages(result) == [message]


@pytest.mark.parametrize(
    ("edit", "doc"),
    [
        (
            ("hard break  \nand", "hard break  \n**Author note:** and"),
            "A paragraph with a hard break\n\n**Author note:** and its second line.",
        ),
        (
            ("A paragraph with a hard", "**Author note:** A paragraph with a hard"),
            "**Author note:** A paragraph with a hard break\n\nand its second line.",
        ),
    ],
    ids=["second-line", "first-line"],
)
def test_a_note_label_on_a_line_of_a_hard_break_paragraph_changes_nothing(
    edit: tuple[str, str], doc: str
) -> None:
    result = _sampler(edit)

    assert result.text == _read("sampler.source.md")
    assert _messages(result) == [
        _refused(
            "a paragraph with a line break and an Author note changed together", doc
        )
    ]


@pytest.mark.parametrize(
    ("source", "edit", "message"),
    [
        (
            "# T\n\n- Item one.\n- Item two.\n\nEnd.\n",
            ("- Item one.", "- **Author note:** Item one."),
            _refused(
                "a list item cannot become an Author note",
                "- **Author note:** Item one.",
            ),
        ),
        (
            "# T\n\n- Item one.\n- Item two.\n\nEnd.\n",
            ("- Item one.\n- Item two.", "**Author note:** Item one.\n\n- Item two."),
            _refused(
                "a list item cannot become an Author note",
                "**Author note:** Item one.",
            ),
        ),
        (
            "# T\n\nIntro.\n\n## Access\n\nBody.\n",
            ("## Access", "**Author note:** Access"),
            _refused(
                "a heading cannot become an Author note", "**Author note:** Access"
            ),
        ),
        (
            "# T\n\nIntro.\n\n## Access\n\n<!-- TODO: add the base URL -->\n\nBody.\n",
            ("Access\n\n\n**Author note:**", "Access **Author note:**"),
            _refused(
                MISPLACED_NOTE, "## Access **Author note:** TODO: add the base URL"
            ),
        ),
    ],
    ids=["item-labelled", "item-restyled", "heading-restyled", "note-onto-heading"],
)
def test_a_list_item_or_heading_cannot_become_a_note(
    source: str, edit: tuple[str, str], message: tuple[ReportKind, str]
) -> None:
    result = _local(source, edit)

    assert result.text == source
    assert _messages(result) == [message]
    to_doc_markdown(result.text)


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (
            ("> **Note:** First", "> Note: First"),
            _refused(
                "the Note label was removed or changed",
                "> Note: First callout paragraph with 60 observations.",
            ),
        ),
        (
            ("> **Note:** First", "> **Note:** **Author note:** First"),
            _refused(
                MISPLACED_NOTE,
                "> **Note:** **Author note:** First callout paragraph with 60"
                " observations.",
            ),
        ),
        (
            ("> **Note:** First", "> **Author note:** First"),
            _refused(
                "the Note label was removed or changed",
                "> **Author note:** First callout paragraph with 60 observations.",
            ),
        ),
        *(
            (
                ("**Tab: For every session**", typed),
                _refused("the Tab label was removed or changed", typed),
            )
            for typed in (
                "For every session",
                "Tab: For every session",
                "**Tab:** For every session",
                "**Tab:**",
            )
        ),
    ],
    ids=[
        "callout-unbolded",
        "callout-note-label",
        "callout-replaced",
        "tab-removed",
        "tab-unbolded",
        "tab-split",
        "tab-emptied",
    ],
)
def test_a_changed_callout_or_tab_label_changes_nothing(
    edit: tuple[str, str], message: tuple[ReportKind, str]
) -> None:
    result = _sampler(edit)

    assert result.text == _read("sampler.source.md")
    assert _messages(result) == [message]


ORDERED = (
    "# T\n\nIntro stays here.\n\n<!-- TODO: say how many sources -->\n\n"
    "The panel lists sources for each country in a table.\n\nClosing paragraph.\n"
)


def test_a_deleted_note_beside_changed_text_is_flagged_once() -> None:
    result = _local(
        ORDERED,
        ("**Author note:** TODO: say how many sources\n\n\n", ""),
        ("in a table.", "in a table, now sorted.\n\nA brand new paragraph."),
    )

    assert result.text == (
        "# T\n\nIntro stays here.\n\n"
        "The panel lists sources for each country in a table, now sorted.\n\n"
        "A brand new paragraph.\n\nClosing paragraph.\n"
    )
    assert _messages(result) == [_beside_text("an Author note")]
    assert result.reports[0].block.text == "TODO: say how many sources"


def test_a_note_added_beside_a_deleted_paragraph_is_flagged_once() -> None:
    source = (
        "# T\n\nIntro stays here.\n\nA paragraph to go.\n\n"
        "The panel lists sources.\n\nClosing paragraph.\n"
    )

    result = _local(
        source,
        ("A paragraph to go.\n\n", ""),
        ("lists sources.", "lists sources, sorted.\n\n**Author note:** check it"),
    )

    assert result.text == (
        "# T\n\nIntro stays here.\n\nThe panel lists sources, sorted.\n\n"
        "<!-- check it -->\n\nClosing paragraph.\n"
    )
    assert _messages(result) == [_beside_text("an Author note")]
    assert result.reports[0].block.text == "check it"


def test_each_note_a_region_turns_into_text_is_flagged() -> None:
    source = "# T\n\nA.\n\n<!-- one -->\n\n<!-- two -->\n\nB.\n"

    result = _local(
        source, ("**Author note:** one\n\n\n\n", ""), ("**Author note:** two", "two")
    )

    assert result.text == "# T\n\nA.\n\ntwo\n\nB.\n"
    assert _messages(result) == [NOTE_TO_TEXT, NOTE_TO_TEXT]
    assert [source[slice(*report.block.span)] for report in result.reports] == [
        "<!-- one -->",
        "<!-- two -->",
    ]


# Resolving a note in the Doc

STUDIO_TEXT = (
    "Studio generates a new plan, title, and answer for each run. The chart uses the"
    " same data."
)
STUDIO_NOTE = (
    "**Author note:** TODO: verify the chart title, plan and answer against the"
    " staging site; they come from the recorded Studio session in the ai"
    " repository, docs/transcripts/studio\\_transcript\\_plan.jsonl."
)
STUDIO_COMMENT = (
    "<!-- TODO: verify the chart title, plan and answer against the staging site;"
    " they come from the recorded Studio session in the ai"
    " repository, docs/transcripts/studio_transcript_plan.jsonl. -->"
)
ANSWER = "The staging site shows the same title."


@pytest.mark.parametrize(
    ("edit", "written", "messages"),
    [
        (
            (f"{STUDIO_TEXT}\n\n{STUDIO_NOTE}\n\n", f"{STUDIO_TEXT}  \n{ANSWER}\n\n"),
            (STUDIO_COMMENT, ANSWER),
            [NOTE_TO_TEXT],
        ),
        (
            (STUDIO_NOTE, f"{STUDIO_NOTE}  \n{ANSWER}"),
            (STUDIO_COMMENT, f"{STUDIO_COMMENT}\n\n{ANSWER}"),
            [],
        ),
        (
            (STUDIO_NOTE, STUDIO_NOTE.replace("TODO: verify", "DONE: verified")),
            (STUDIO_COMMENT, STUDIO_COMMENT.replace("TODO: verify", "DONE: verified")),
            [],
        ),
        (
            (
                STUDIO_NOTE,
                STUDIO_NOTE.replace("TODO: verify", "DONE: verified") + f"  \n{ANSWER}",
            ),
            (
                STUDIO_COMMENT,
                STUDIO_COMMENT.replace("TODO: verify", "DONE: verified")
                + f"\n\n{ANSWER}",
            ),
            [_beside_text("an Author note")],
        ),
        ((STUDIO_NOTE, ANSWER), (STUDIO_COMMENT, ANSWER), [NOTE_TO_TEXT]),
        ((f"{STUDIO_NOTE}\n\n", ""), (f"{STUDIO_COMMENT}\n\n", ""), []),
    ],
    ids=[
        "deleted-and-answered-after-the-paragraph-before",
        "answered-after-the-note",
        "edited",
        "edited-and-answered-after-the-note",
        "typed-over",
        "deleted",
    ],
)
def test_a_note_resolved_with_enter_applies_in_doc_order(
    edit: tuple[str, str], written: tuple[str, str], messages: list[tuple]
) -> None:
    source, baseline = (_read(name) for name in RECORDED["use-studio"])

    result = _recorded("use-studio", _edit(baseline, edit))

    assert result.text == _edit(source, written)
    assert _messages(result) == messages


CONNECT_NOTE = "**Author note:** TODO: verify the ChatGPT UI labels and plan list."
CONNECT_COMMENT = "<!-- TODO: verify the ChatGPT UI labels and plan list. -->"
CONNECT_TEXT = (
    "ChatGPT's own tool-call limit is about 60 seconds and it sends no progress"
    " notifications, so a call that reaches this server's 45-second answer already"
    " has margin."
)


@pytest.mark.parametrize(
    ("note", "comment"),
    [
        ("", ""),
        (
            f"{CONNECT_NOTE.replace('TODO', 'DONE')}\n\n",
            f"{CONNECT_COMMENT.replace('TODO', 'DONE')}\n\n",
        ),
    ],
    ids=["note-deleted", "note-edited"],
)
def test_a_paragraph_made_with_enter_after_a_note_s_neighbour_is_added(
    note: str, comment: str
) -> None:
    source, baseline = (_read(name) for name in RECORDED["connect"])

    result = _recorded(
        "connect",
        _edit(
            baseline,
            (
                f"{CONNECT_NOTE}\n\n{CONNECT_TEXT}",
                f"{note}{CONNECT_TEXT}  \nA new sentence follows.",
            ),
        ),
    )

    assert result.text == _edit(
        source,
        (
            f"{CONNECT_COMMENT}\n\n{CONNECT_TEXT}",
            f"{comment}{CONNECT_TEXT}\n\nA new sentence follows.",
        ),
    )
    assert result.reports == ()


def test_a_long_paragraph_joined_onto_a_note_changes_nothing() -> None:
    source, baseline = (_read(name) for name in RECORDED["connect"])
    note = (
        "**Author note:** TODO: replace \\<dfo-site\\> with the public URL once the"
        " website is deployed."
    )
    paragraph = next(
        block for block in baseline.split("\n\n") if block.startswith("One endpoint")
    )

    result = _recorded(
        "connect", _edit(baseline, (f"{note}\n\n{paragraph}", f"{note} {paragraph}"))
    )

    assert result.text == source
    assert _messages(result) == [
        _refused(
            "text was joined onto or split off an Author note", f"{note} {paragraph}"
        )
    ]


CONNECT_OUTPUT_NOTE = (
    "**Author note:** TODO: verify this output against the public endpoint once it"
    " exists. It comes from a call to the data tools against the dev APIs on 28"
    " September 2026\\."
)
CONNECT_CHECK = (
    "If the assistant answers without calling `search`, check that the client lists"
    " the DFO tools. In Claude Code, `claude mcp list` shows each server and whether"
    " it connected."
)
STUDIO_DESCRIPTION = (
    "**Description:** Ask DFO Studio one question, approve its research plan, read"
    " the chart it draws on the canvas, and pin the card you want to keep."
)


def _split(text: str, at: str, *words: tuple[str, str]) -> tuple[str, str]:
    """`text` split with Enter after `at`, as the export writes it, and the Doc's
    paragraphs as a refusal quotes them, with `words` changed in both."""
    first, second = text.split(f"{at} ", 1)
    for old, new in words:
        first, second = first.replace(old, new), second.replace(old, new)
    return f"{first}{at}  \n{second}", f"{first}{at}\n\n{second}"


@pytest.mark.parametrize(
    ("page", "old", "new", "doc", "what"),
    [
        (
            "connect",
            CONNECT_OUTPUT_NOTE,
            *_split(CONNECT_OUTPUT_NOTE, "once it exists.", ("dev ", "development ")),
            "an Author note",
        ),
        (
            "connect",
            f"{CONNECT_OUTPUT_NOTE}\n\n{CONNECT_CHECK}",
            joined := (
                f"{CONNECT_OUTPUT_NOTE}"
                f" {CONNECT_CHECK.replace('check that', 'confirm that')}"
            ),
            joined,
            "an Author note",
        ),
        (
            "connect",
            f"{CONNECT_NOTE}\n\n{CONNECT_TEXT}",
            joined := f"{CONNECT_NOTE} {CONNECT_TEXT.replace('about 60', 'around 60')}",
            joined,
            "an Author note",
        ),
        (
            "use-studio",
            STUDIO_NOTE,
            *_split(STUDIO_NOTE, "staging site;", ("they come", "These come")),
            "an Author note",
        ),
        (
            "use-studio",
            STUDIO_NOTE,
            *_split(STUDIO_NOTE, "staging site;", ("TODO: verify", "TODO: check")),
            "an Author note",
        ),
        (
            "use-studio",
            STUDIO_DESCRIPTION,
            *_split(STUDIO_DESCRIPTION, "research plan,", ("the card", "the cards")),
            "the Description",
        ),
    ],
    ids=[
        "split-second-part-edited",
        "joined-next-edited",
        "joined-next-edited-short-note",
        "split-second-part-edited-studio",
        "split-first-part-edited",
        "description-split-edited",
    ],
)
def test_text_crossing_a_note_edge_with_a_word_changed_changes_nothing(
    page: str, old: str, new: str, doc: str, what: str
) -> None:
    source, baseline = (_read(name) for name in RECORDED[page])

    result = _recorded(page, _edit(baseline, (old, new)))

    assert result.text == source
    assert _messages(result) == [
        _refused(f"text was joined onto or split off {what}", doc)
    ]


@pytest.mark.parametrize(
    ("source", "edit", "written", "what"),
    [
        (
            "# T\n\nIntro.\n\n<!-- TODO: check this -->\n\nShort para.\n\nEnd.\n",
            ("check this\n\n\nShort para.\n\n", "checked this\n\n"),
            "# T\n\nIntro.\n\n<!-- TODO: checked this -->\n\nEnd.\n",
            "an Author note",
        ),
        (
            "---\ndescription: Short summary.\n---\n\nIntro paragraph.\n\nEnd.\n",
            ("Short summary.\n\n\n", "A short summary.\n\nNew paragraph.\n\n"),
            "---\ndescription: A short summary.\n---\n\nNew paragraph.\n\n"
            "Intro paragraph.\n\nEnd.\n",
            "the Description",
        ),
        (
            "# T\n\nIntro.\n\n<!-- TODO: check this -->\n\nShort para.\n\nEnd.\n",
            ("check this\n\n\nShort para.", "checked this\n\n\nShort paragraph."),
            "# T\n\nIntro.\n\n<!-- TODO: checked this -->\n\nShort paragraph.\n\n"
            "End.\n",
            "an Author note",
        ),
        (
            "# T\n\nIntro.\n\n<!-- one -->\n\n<!-- two -->\n\nShort para.\n\nEnd.\n",
            (
                "one\n\n\n\n**Author note:** two\n\n\nShort para.",
                "one more\n\n\n\n**Author note:** two more\n\n\nShort paragraph.",
            ),
            "# T\n\nIntro.\n\n<!-- one more -->\n\n<!-- two more -->\n\n"
            "Short paragraph.\n\nEnd.\n",
            "an Author note",
        ),
        (
            "# T\n\nIntro.\n\n<!-- TODO: check this -->\n\nShort para.\n\nEnd.\n",
            ("**Author note:** TODO: check this\n\n\nShort para.\n\n", ""),
            "# T\n\nIntro.\n\nEnd.\n",
            "an Author note",
        ),
    ],
    ids=[
        "note-edited-next-paragraph-deleted",
        "description-edited-paragraph-added",
        "note-edited-next-paragraph-edited",
        "two-notes-edited-next-paragraph-edited",
        "note-and-next-paragraph-deleted",
    ],
)
def test_a_note_changed_beside_changed_text_is_flagged_once(
    source: str, edit: tuple[str, str], written: str, what: str
) -> None:
    result = _local(source, edit)

    assert result.text == written
    assert _messages(result) == [_beside_text(what)]


@pytest.mark.parametrize(
    ("page", "old", "new", "doc"),
    [
        (
            "connect",
            f"{CONNECT_OUTPUT_NOTE}\n\n{CONNECT_CHECK}",
            *_split(CONNECT_OUTPUT_NOTE, "once it exists."),
        ),
        (
            "connect",
            f"{CONNECT_OUTPUT_NOTE}\n\n{CONNECT_CHECK}",
            typed := (
                f"{CONNECT_OUTPUT_NOTE} {CONNECT_CHECK}\n\nAsk the assistant for the"
                " latest figures and it calls the data tools first."
            ),
            typed,
        ),
    ],
    ids=["split-next-paragraph-deleted", "joined-new-paragraph-typed"],
)
def test_a_note_split_or_join_paired_by_position_changes_nothing(
    page: str, old: str, new: str, doc: str
) -> None:
    source, baseline = (_read(name) for name in RECORDED[page])

    result = _recorded(page, _edit(baseline, (old, new)))

    assert result.text == source
    assert _messages(result) == [
        _refused("text was joined onto or split off an Author note", doc)
    ]


def test_a_join_onto_a_note_with_enter_in_the_next_paragraph_changes_nothing() -> None:
    source = (
        "# T\n\nIntro.\n\n<!-- TODO: check the numbers -->\n\nShort para here."
        "\n\nSecond para with two sentences. It goes on.\n\n## End\n"
    )

    result = _local(
        source,
        ("numbers\n\n\nShort", "numbers Short"),
        ("sentences. It", "sentences.  \nIt"),
    )

    assert result.text == source
    assert _messages(result) == [
        _refused(
            "text was joined onto or split off an Author note",
            "**Author note:** TODO: check the numbers Short para here.\n\nSecond para"
            " with two sentences.\n\nIt goes on.",
        )
    ]


UNPLACED = (
    "# Title\n\n- First item.\n- Second item.\n\n<!-- TODO: an intro note. -->\n\n"
    "For an amount V in source currency S in year t, the recipe converts it with"
    " this formula.\n\n```\nV * D\n```\n\nAfter the code.\n"
)


def test_a_region_whose_new_paragraph_has_no_place_keeps_what_it_deletes() -> None:
    doc = "1. Zebra lantern quantum replaces everything here."

    result = _local(
        UNPLACED,
        (
            "**Author note:** TODO: an intro note.\n\n\nFor an amount V in source"
            " currency S in year t, the recipe converts it with this formula.",
            doc,
        ),
    )

    assert result.text == UNPLACED
    assert _messages(result) == [
        _refused("an added paragraph sits in no container its neighbours share", doc)
    ]


@pytest.mark.parametrize(
    ("page", "note", "start", "doc"),
    [
        (
            "methods",
            "**Author note:** TODO: name which provenances declare which recipe once"
            " the recipe declarations are in the graph.",
            "For an amount V",
            "1. The DAC recipe converts an amount in its source currency to the"
            " target currency at constant base-year prices like this.",
        ),
        (
            "connect",
            CONNECT_NOTE,
            "ChatGPT's own tool-call",
            "- Calls that run longer than a minute fail in ChatGPT, which shows no"
            " progress; this server answers within 45 seconds.",
        ),
    ],
    ids=["methods", "connect"],
)
def test_a_note_deleted_beside_a_rewrite_that_has_no_place_keeps_both(
    page: str, note: str, start: str, doc: str
) -> None:
    source, baseline = (_read(name) for name in RECORDED[page])
    paragraph = next(
        block for block in baseline.split("\n\n") if block.startswith(start)
    )

    result = _recorded(page, _edit(baseline, (f"{note}\n\n{paragraph}", doc)))

    assert result.text == source
    assert _messages(result) == [
        _refused("an added paragraph sits in no container its neighbours share", doc)
    ]


def test_a_note_and_paragraph_rewritten_below_a_list_apply_after_it() -> None:
    source, baseline = (_read(name) for name in RECORDED["methods"])
    note = (
        "TODO: name which provenances declare which recipe once the recipe"
        " declarations are in the graph."
    )
    doc = (
        "The DAC recipe converts an amount in its source currency to the target"
        " currency at constant base-year prices like this."
    )
    paragraph = next(
        block for block in baseline.split("\n\n") if block.startswith("For an amount V")
    )
    written = next(
        block for block in source.split("\n\n") if block.startswith("For an amount V")
    )

    result = _recorded(
        "methods", _edit(baseline, (f"**Author note:** {note}\n\n{paragraph}", doc))
    )

    assert result.text == _edit(source, (f"<!-- {note} -->\n\n{written}", doc))
    assert _messages(result) == [NOTE_TO_TEXT]


QUOTE = "> Total population in Kenya, 1960 to 2024, according to 4 sources."


@pytest.mark.parametrize(
    ("edit", "doc"),
    [
        (
            (QUOTE, QUOTE.replace("> ", "> **Author note:** ")),
            QUOTE.replace("> ", "> **Author note:** "),
        ),
        (
            (QUOTE, f"{QUOTE}  \n> **Author note:** TODO: check this on staging."),
            "> **Author note:** TODO: check this on staging.",
        ),
    ],
    ids=["labelled", "added"],
)
def test_a_note_in_a_quote_changes_nothing(edit: tuple[str, str], doc: str) -> None:
    result = _recorded("get-data", _edit(_read("pages/get-data.baseline.md"), edit))

    assert result.text == _read("pages/get-data.source.md")
    assert _messages(result) == [_refused("an Author note cannot sit in a quote", doc)]


def test_a_note_typed_after_a_quote_is_a_note() -> None:
    result = _recorded(
        "get-data",
        _edit(
            _read("pages/get-data.baseline.md"),
            (QUOTE, f"{QUOTE}\n\n**Author note:** TODO: check this on staging."),
        ),
    )

    assert result.text == _edit(
        _read("pages/get-data.source.md"),
        (f"{QUOTE}\n", f"{QUOTE}\n\n<!-- TODO: check this on staging. -->\n"),
    )
    assert result.reports == ()


@pytest.mark.parametrize(
    ("typed", "written"),
    [
        (" \\<\\!-- hide this --\\> And more.", " \\<!-- hide this --> And more."),
        ("  \n\\<\\!-- hide this --\\>", "\n\n\\<!-- hide this -->"),
    ],
    ids=["in-a-paragraph", "own-paragraph"],
)
def test_a_typed_comment_opener_stays_text(typed: str, written: str) -> None:
    line = (
        "Hover over the line to read the value for a single year. You can drag the"
        " card to another spot on the canvas and resize it."
    )
    edited = _edit(_read("pages/use-studio.baseline.md"), (line, line + typed))

    result = _recorded("use-studio", edited)

    assert result.text == _edit(
        _read("pages/use-studio.source.md"), (line, line + written)
    )
    assert result.reports == ()
    align_baseline(page="use-studio", source=result.text, baseline=edited)


# Adding list items in the Doc


@pytest.mark.parametrize(
    ("after", "added", "written"),
    [
        (
            "   **Author note:** TODO: an inline note on a list item.  \n",
            "4. A fourth step.  \n",
            (
                "1. Start a new Claude Code session."
                " <!-- TODO: an inline note on a list item. -->\n",
                "1. A fourth step.\n",
            ),
        ),
        (
            "  **Author note:** TODO: a standalone note inside a list item",
            "  \n- Outer item three",
            (
                "  <!-- TODO: a standalone note inside a list item -->\n",
                "- Outer item three\n",
            ),
        ),
    ],
    ids=["after-an-inline-note", "after-a-standalone-note"],
)
def test_an_item_added_after_an_item_s_note_joins_its_list(
    after: str, added: str, written: tuple[str, str]
) -> None:
    result = _sampler((after, after + added))

    line, item = written
    assert result.text == _edit(_read("sampler.source.md"), (line, line + item))
    assert result.reports == ()


def test_an_item_added_after_a_link_list_item_with_a_note_joins_its_list() -> None:
    item = next(
        line
        for line in _read("pages/connect.baseline.md").split("\n")
        if line.startswith("- The Tools reference")
    )

    result = _recorded(
        "connect",
        _edit(
            _read("pages/connect.baseline.md"), (item, f"{item}\n- A new related page.")
        ),
    )

    source = _read("pages/connect.source.md")
    line = next(line for line in source.split("\n") if line.startswith("- The Tools"))
    assert result.text == _edit(source, (line, f"{line}\n- A new related page."))
    assert result.reports == ()


@pytest.mark.parametrize(
    ("typed", "written"),
    [
        (
            "\n\n- Drag to move.\n- Resize from a corner.",
            "- Drag to move.\n- Resize from a corner.",
        ),
        (
            "  \n- Drag to move.  \n- Resize from a corner.",
            "- Drag to move.\n- Resize from a corner.",
        ),
        (
            "\n\n1. Drag to move.\n2. Resize from a corner.",
            "1. Drag to move.\n2. Resize from a corner.",
        ),
    ],
    ids=["bullets", "bullets-after-enter", "numbered"],
)
def test_a_list_added_after_a_paragraph_opens_a_list_there(
    typed: str, written: str
) -> None:
    baseline = _read("pages/use-studio.baseline.md")
    paragraph = next(
        block for block in baseline.split("\n\n") if block.startswith("Open the ⋮")
    )
    source = _read("pages/use-studio.source.md")
    original = next(
        block for block in source.split("\n\n") if block.startswith("Open the ⋮")
    )

    result = _recorded("use-studio", _edit(baseline, (paragraph, paragraph + typed)))

    assert result.text == _edit(source, (original, f"{original}\n\n{written}"))
    assert result.reports == ()


def test_a_numbered_item_before_a_bullet_list_opens_its_own_list() -> None:
    source = "# T\n\nIntro.\n\n- Bullet one\n- Bullet two\n"

    result = _local(source, ("Intro.\n\n", "Intro.\n\n1. A step.\n\n"))

    assert result.text == "# T\n\nIntro.\n\n1. A step.\n\n- Bullet one\n- Bullet two\n"
    assert result.reports == ()


@pytest.mark.parametrize(
    ("source", "edit", "reason", "doc"),
    [
        (
            "# T\n\n1. First step.\n\n   ```sh\n   run it\n   ```\n\n"
            "- Bullet one\n- Bullet two\n",
            ("```\n\n- Bullet one", "```\n\n2. Second step.\n\n- Bullet one"),
            "a paragraph added next to a code block in a list cannot be placed",
            "2. Second step.",
        ),
        (
            "# T\n\n- Bullet one\n- Bullet two\n\nEnd.\n",
            ("- Bullet two\n", "- Bullet two\n1. A step.\n"),
            "an added paragraph sits in no container its neighbours share",
            "1. A step.",
        ),
    ],
    ids=["after-a-fence-before-a-bullet-list", "after-a-bullet-list"],
)
def test_a_numbered_item_beside_a_bullet_list_does_not_join_it(
    source: str, edit: tuple[str, str], reason: str, doc: str
) -> None:
    result = _local(source, edit)

    assert result.text == source
    assert _messages(result) == [_refused(reason, doc)]


def test_a_new_list_that_opens_with_a_nested_item_changes_nothing() -> None:
    baseline = _read("pages/use-studio.baseline.md")
    paragraph = next(
        block for block in baseline.split("\n\n") if block.startswith("You'll ask")
    )
    typed = "- First new point.\n    - Nested point.\n- Second new point."

    result = _recorded(
        "use-studio", _edit(baseline, (paragraph, f"{paragraph}\n\n{typed}"))
    )

    assert result.text == _read("pages/use-studio.source.md")
    assert [(report.kind, report.message) for report in result.reports] == [
        (
            ReportKind.REFUSED,
            "an added paragraph sits in no container its neighbours share; this part"
            " of the page is not changed",
        )
    ]


def test_a_list_marker_removed_in_the_doc_is_reported() -> None:
    item = "- How to read a card on the canvas and where its data came from."

    result = _recorded(
        "use-studio",
        _edit(_read("pages/use-studio.baseline.md"), (item, item.removeprefix("- "))),
    )

    assert result.text == _read("pages/use-studio.source.md")
    assert _messages(result) == [
        (
            ReportKind.NOT_APPLIED,
            "a list marker was added or removed in the Doc; only its text is applied",
            "",
        )
    ]


def test_a_note_unlabelled_under_its_item_s_text_is_a_paragraph_of_the_item() -> None:
    result = _sampler(
        (
            "  **Author note:** TODO: a standalone note inside a list item",
            "  TODO: a standalone note inside a list item",
        )
    )

    assert result.text == _edit(
        _read("sampler.source.md"),
        (
            "  <!-- TODO: a standalone note inside a list item -->",
            "\n  TODO: a standalone note inside a list item",
        ),
    )
    assert _messages(result) == [NOTE_TO_TEXT]


def test_deleting_two_paragraphs_in_a_row_leaves_one_blank_line() -> None:
    result = _local("# T\n\nA.\n\nB.\n\nC.\n\nD.\n", ("B.\n\nC.\n\n", ""))

    assert result.text == "# T\n\nA.\n\nD.\n"


def test_an_emptied_author_note_deletes_the_note() -> None:
    result = _sampler((NOTE, "**Author note:**"))

    assert result.text == _edit(
        _read("sampler.source.md"),
        (
            "\n\n<!-- TODO: a top-level author note with `code`, a"
            " [link](../build/share.md) and <dfo-site>. -->",
            "",
        ),
    )
    assert result.reports == ()


def test_an_emptied_inline_author_note_leaves_its_list_item() -> None:
    result = _sampler(
        ("**Author note:** TODO: an inline note on a list item.", "**Author note:**")
    )

    assert result.text == _edit(
        _read("sampler.source.md"),
        (" <!-- TODO: an inline note on a list item. -->", ""),
    )
    assert result.reports == ()


def test_an_added_empty_author_note_adds_nothing() -> None:
    result = _sampler(("\n## Next", "\n**Author note:**\n\n## Next"))

    assert result.text == _read("sampler.source.md")


def test_tab_label_with_a_quote_is_reported() -> None:
    result = _sampler(("**Tab: For one project**", '**Tab: For "one" project**'))

    assert result.text == _read("sampler.source.md")
    assert _kinds(result) == [(ReportKind.NOT_APPLIED, "For one project")]


def test_callout_label_change_is_reported() -> None:
    result = _sampler(("> **Warning:**", "> **Tip:**"))

    assert result.text == _read("sampler.source.md")
    assert _kinds(result) == [(ReportKind.NOT_APPLIED, "Warning")]


def test_table_cell_pipe_is_escaped() -> None:
    result = _sampler(("The MCP server guide", "The guide \\| soon"))

    row = next(line for line in result.text.split("\n") if "soon" in line)
    assert row.endswith("| The guide \\| soon    |")


def test_an_emptied_bold_header_cell_loses_its_bold() -> None:
    result = _sampler(("| Task |", "|  |"))

    row = next(line for line in result.text.split("\n") if "Start here" in line)
    assert row.startswith("|                                                    | Use")


def test_a_star_typed_in_a_bold_header_cell_keeps_its_escape() -> None:
    result = _sampler(("| Task |", "| Task \\* |"))

    assert "| **Task \\*** " in result.text


def test_a_compact_table_cell_is_spliced_in_place() -> None:
    source = "# T\n\n|a|b|\n|-|-|\n|one|two|\n"

    result = _local(source, ("two", "three"))

    assert result.text == "# T\n\n|a|b|\n|-|-|\n|one|three|\n"


def test_a_cell_edit_in_an_unpadded_table_changes_only_its_row() -> None:
    note = "**Author note:** TODO: link when the MCP endpoint and its guide are public"

    result = _sampler((note, note.replace("are public", "go public")))

    assert result.text == _read("sampler.source.md").replace(
        "its guide are public -->", "its guide go public -->"
    )


def test_a_padded_table_is_re_rendered_when_a_cell_outgrows_its_column() -> None:
    source = "# T\n\n| a   | b   |\n| --- | --- |\n| one | two |\n"

    result = _local(source, ("two", "twenty-two"))

    assert result.text == (
        "# T\n\n| a   | b          |\n| --- | ---------- |\n| one | twenty-two |\n"
    )


def test_unchanged_table_keeps_its_layout() -> None:
    result = _sampler(("Then more.", "Then less."))

    assert "| The DFO MCP server <!-- TODO: link when" in result.text


def test_a_container_change_applies_only_the_text() -> None:
    quote = "> Total population in Kenya, 1960 to 2024, according to 4 sources."
    result = _recorded(
        "get-data", _edit(_read("pages/get-data.baseline.md"), (quote, quote[2:]))
    )

    assert result.text == _read("pages/get-data.source.md")
    assert [(r.kind, r.message) for r in result.reports] == [
        (
            ReportKind.NOT_APPLIED,
            "moved from blockquote at depth 1 to paragraph at depth 0;"
            " only its text is applied",
        )
    ]


def test_one_word_edit_in_a_soft_wrapped_paragraph_changes_one_line() -> None:
    result = _sampler(("whose first line ends here", "whose first line stops here"))

    assert result.text == _read("sampler.source.md").replace(
        "whose first line ends here\n", "whose first line stops here\n"
    )
    assert result.reports == ()


def test_soft_wrap_keeps_each_line_break_whose_words_stay() -> None:
    source = "# T\n\n- One two\n  three four\n  five six.\n"

    # Google exports the paragraph on one line.
    baseline = "# T\n\n- One two three four five six."

    result = apply_edits(
        page="p",
        source=source,
        baseline=baseline,
        edited=baseline.replace("three", "3"),
    )

    assert result.text == "# T\n\n- One two\n  3 four\n  five six.\n"


WRAPPED = (
    "# T\n\n"
    "The first line of a long wrapped paragraph ends with word\n"
    "and the second line carries on for a while until it ends\n"
    "while the third line starts with while and ends with\n"
    "the fourth line, which closes the paragraph.\n\n"
    "Next.\n"
)


@pytest.mark.parametrize(
    ("doc", "line"),
    [
        (
            ("word and the second", "word the second"),
            ("and the second line", "the second line"),
        ),
        (
            ("with word and", "with and"),
            ("ends with word\n", "ends with\n"),
        ),
        (
            ("until it ends while", "until it ends - while"),
            ("until it ends\n", "until it ends -\n"),
        ),
        (
            ("ends with the fourth", "ends with + the fourth"),
            ("and ends with\n", "and ends with +\n"),
        ),
    ],
    ids=["delete-line-start", "delete-line-end", "dash-at-break", "plus-at-break"],
)
def test_an_edit_at_a_soft_wrap_keeps_every_line_break(
    doc: tuple[str, str], line: tuple[str, str]
) -> None:
    baseline = WRAPPED.replace("\n", " ").replace("  ", "\n\n").rstrip()

    result = apply_edits(
        page="p", source=WRAPPED, baseline=baseline, edited=_edit(baseline, doc)
    )

    assert result.text == _edit(WRAPPED, line)


def test_an_insertion_at_a_recorded_soft_wrap_ends_the_line() -> None:
    result = _sampler(("ends here and whose", "ends here - and whose"))

    assert result.text == _read("sampler.source.md").replace(
        "first line ends here\n", "first line ends here -\n"
    )


def test_soft_wrap_joins_only_the_lines_where_a_break_would_open_a_list() -> None:
    source = "# T\n\nOne two\nthree four\nfive six.\n"
    baseline = "# T\n\nOne two three four five six."

    result = apply_edits(
        page="p",
        source=source,
        baseline=baseline,
        edited=_edit(baseline, ("three", "-")),
    )

    assert result.text == "# T\n\nOne two - four\nfive six.\n"


@pytest.mark.parametrize(
    "rest", ["- the second line", "---", "===", "> quoted", "1. next", "```"]
)
def test_a_deletion_that_leaves_a_marker_at_a_line_start_joins_only_that_line(
    rest: str,
) -> None:
    source = f"# T\n\nFirst line here\nand {rest}\nthird line.\n"
    baseline = f"# T\n\nFirst line here and {rest} third line."

    result = apply_edits(
        page="p",
        source=source,
        baseline=baseline,
        edited=_edit(baseline, (f"here and {rest}", f"here {rest}")),
    )

    assert result.text == _edit(
        source, (f"First line here\nand {rest}", f"First line here {rest}")
    )


SOFT = (
    "A soft-wrapped paragraph whose first line ends here\n"
    "and whose second line ends the paragraph."
)
HARD = "A paragraph with a hard break  \nand its second line."


@pytest.mark.parametrize(
    ("doc", "source"),
    [
        # A boundary added in the Doc reads as a new paragraph.
        (
            ("ends here and whose", "ends here  \nand whose"),
            ("ends here\nand whose", "ends here\n\nand whose"),
        ),
        (
            ("whose second line ends", "whose second  \nline ends"),
            ("whose second line ends", "whose second\n\nline ends"),
        ),
        # A paragraph joined onto a hard-break paragraph keeps its hard break.
        (
            ("ends the paragraph.\n\nA paragraph", "ends the paragraph. A paragraph"),
            ("ends the paragraph.\n\nA paragraph", "ends the paragraph. A paragraph"),
        ),
        # A hard break removed in the Doc becomes one space, with no trailing spaces.
        (
            ("hard break  \nand its", "hard break and its"),
            ("hard break  \nand its", "hard break and its"),
        ),
        (
            ("hard break  \nand its second line.", "hard break"),
            ("hard break  \nand its second line.", "hard break"),
        ),
        (
            ("its second line.", "its third line."),
            ("its second line.", "its third line."),
        ),
    ],
    ids=[
        "break-in-a-line",
        "break-in-the-last-line",
        "join-onto-a-hard-break",
        "remove-a-hard-break",
        "delete-the-line-after-a-hard-break",
        "edit-after-a-hard-break",
    ],
)
def test_hard_breaks_follow_the_doc(
    doc: tuple[str, str], source: tuple[str, str]
) -> None:
    result = _sampler(doc)

    assert result.text == _edit(_read("sampler.source.md"), source)
    assert result.reports == ()


def test_a_paragraph_added_after_a_hard_break_keeps_the_break_with_the_next_line() -> (
    None
):
    result = _sampler(("hard break  \nand its", "hard break  \nNew line.  \nand its"))

    assert result.text == _edit(
        _read("sampler.source.md"),
        ("hard break  \nand its", "hard break\n\nNew line.  \nand its"),
    )


@pytest.mark.parametrize(
    ("doc", "source"),
    [
        (
            ("and its second line.", "and its  \nsecond line."),
            ("and its second line.", "and its\n\nsecond line."),
        ),
        (
            ("and its second line.", "and its second  \nline."),
            ("and its second line.", "and its second\n\nline."),
        ),
        (
            (
                "A paragraph with a hard break  \n",
                "A paragraph  \nwith a hard break  \n",
            ),
            (
                "A paragraph with a hard break  \n",
                "A paragraph\n\nwith a hard break  \n",
            ),
        ),
    ],
    ids=["after-the-hard-break", "late-after-the-hard-break", "before-the-hard-break"],
)
def test_a_break_added_beside_a_hard_break_leaves_the_hard_break_in_place(
    doc: tuple[str, str], source: tuple[str, str]
) -> None:
    result = _sampler(doc)

    assert result.text == _edit(_read("sampler.source.md"), source)
    assert result.reports == ()


HARD_BREAKS = (
    "# T\n\n"
    "First para one  \nfirst para two  \nfirst para three.\n\n"
    "Second para with words  \nand a second line.\n\n"
    "- Item one  \n  item one more\n- Item two\n\n"
    "> Quote line one  \n> quote line two.\n\n"
    "Plain closing paragraph here.\n"
)


@pytest.mark.parametrize(
    ("doc", "source"),
    [
        (
            [("first para two", "first  \npara two")],
            [("first para two", "first\n\npara two")],
        ),
        ([("- Item one", "- Item  \n  one")], [("- Item one", "- Item\n\n  one")]),
        (
            [("  item one more", "  item  \n  one more")],
            [("  item one more", "  item\n\n  one more")],
        ),
        (
            [("and a second", "and  \na second")],
            [("and a second", "and\n\na second")],
        ),
        (
            [
                ("Item one  \n  item one more", "Item one item one more"),
                ("- Item two", "- Item  \n  two"),
            ],
            [
                ("Item one  \n  item one more", "Item one item one more"),
                ("- Item two", "- Item\n\n  two"),
            ],
        ),
    ],
    ids=[
        "paragraph",
        "list-item-first-line",
        "list-item-last-line",
        "two-lines",
        "two-items",
    ],
)
def test_hard_breaks_stay_where_the_source_has_them(
    doc: list[tuple[str, str]], source: list[tuple[str, str]]
) -> None:
    result = _local(HARD_BREAKS, *doc)

    assert result.text == _edit(HARD_BREAKS, *source)
    assert result.reports == ()


def test_a_break_added_at_any_word_gap_keeps_every_hard_break() -> None:
    baseline = to_doc_markdown(HARD_BREAKS)
    gaps = [match.start() for match in re.finditer(r"(?<=[a-z,.]) (?=[a-z])", baseline)]

    def hard_breaks(text: str) -> list[tuple[str, str]]:
        return sorted(re.findall(r"(\S+)  \n[ >]*(\S+)", text))

    assert len(gaps) == 23
    for gap in gaps:
        line = baseline[baseline.rfind("\n", 0, gap) + 1 : gap]
        prefix = re.sub(r"^- ", "  ", line[: len(line) - len(line.lstrip(" >-"))])
        edited = f"{baseline[:gap]}  \n{prefix}{baseline[gap + 1 :]}"

        result = apply_edits(
            page="p", source=HARD_BREAKS, baseline=baseline, edited=edited
        )

        assert hard_breaks(result.text) == hard_breaks(HARD_BREAKS), line
        assert result.reports == ()
        align_baseline(page="p", source=result.text, baseline=edited)


@pytest.mark.parametrize(
    ("typed", "written"),
    [
        # Google escapes what an editor types literally; the source keeps the escapes
        # it needs to render the same.
        (r"Replace \<host\> in the URL.", r"Replace \<host> in the URL."),
        (r"Multiply 2\*3\*4 here.", r"Multiply 2\*3*4 here."),
        (r"Ends in 1960\.", "Ends in 1960."),
    ],
)
def test_typed_punctuation_stays_literal(typed: str, written: str) -> None:
    result = _local(
        "# Page\n\nReplace the host in the URL.\n",
        ("Replace the host in the URL.", typed),
    )

    assert result.text == f"# Page\n\n{written}\n"


def test_an_escaping_source_with_an_unedited_doc_is_unchanged() -> None:
    source = "# Page\n\nUse \\* as a wildcard.\n\nTom &amp; Jerry.\n"
    baseline = "# Page\n\nUse \\* as a wildcard.\n\nTom & Jerry."

    result = apply_edits(page="p", source=source, baseline=baseline, edited=baseline)

    assert result.text == source


def test_curly_quotes_typed_in_the_doc_become_straight() -> None:
    result = _local(
        "# T\n\nNo sign-in.\n",
        ("No sign-in.", "\u201cNo sign-in\u201d isn\u2019t `\u2018x\u2019`."),
    )

    assert result.text == '# T\n\n"No sign-in" isn\'t `\u2018x\u2019`.\n'


@pytest.mark.parametrize(
    "source",
    [
        "Use spec\\_id and version 2\\.0 with your token.",
        "See [the guide](./guide.md) and send your token.",
        "The \u201cquoted\u201d word and your token.",
        "See <https://example.org/a_b> and your token.",
    ],
    ids=["escapes", "dot-slash-link", "curly-quotes", "autolink"],
)
def test_a_one_word_edit_keeps_the_source_notation_around_it(source: str) -> None:
    page = f"# T\n\n{source}\n\nSecond para.\n"

    result = _local(page, ("your token", "your API token"))

    assert result.text == page.replace("your token", "your API token")
    assert result.reports == ()


def test_an_entity_the_export_decodes_stays_in_the_source() -> None:
    source = "# T\n\nR&amp;D and your token.\n"
    baseline = "# T\n\nR&D and your token."

    result = apply_edits(
        page="p",
        source=source,
        baseline=baseline,
        edited=baseline.replace("your token", "your API token"),
    )

    assert result.text == "# T\n\nR&amp;D and your API token.\n"


def test_an_edit_next_to_kept_notation_keeps_only_the_escapes_it_needs() -> None:
    result = _local(
        "# T\n\nUse spec\\_id with the host.\n",
        ("the host.", "\\<host\\> and 2\\*3\\*4\\."),
    )

    assert result.text == "# T\n\nUse spec\\_id with \\<host> and 2\\*3*4.\n"


# Structural changes


def test_heading_level_change_is_reported() -> None:
    result = _sampler(("## Step 2: change the years", "### Step 2: change the years"))

    assert result.text == _read("sampler.source.md")
    assert [(r.kind, r.message) for r in result.reports] == [
        (
            ReportKind.NOT_APPLIED,
            "heading level 2 became 3 in the Doc; only its text is applied",
        )
    ]


@pytest.mark.parametrize("marker", ["- ", "> "])
def test_paragraph_turned_into_a_list_item_or_quote_is_reported(marker: str) -> None:
    source = "# Page\n\n## Section\n\nFirst paragraph.\n\nSecond paragraph.\n"

    result = _local(source, ("Second paragraph.", f"{marker}Second paragraph."))

    assert result.text == source
    assert [r.kind for r in result.reports] == [ReportKind.NOT_APPLIED]
    assert result.reports[0].message.startswith("moved from paragraph at depth 0 to")


def test_inserted_and_deleted_rules_are_reported() -> None:
    source = "# T\n\nA.\n\n---\n\nB.\n"

    inserted = _local(source, ("B.", "B.\n\n***\n\nC."))
    deleted = _local(source, ("---\n\n", ""))

    assert inserted.text == source.replace("B.\n", "B.\n\nC.\n")
    assert _kinds(inserted) == [(ReportKind.STRUCTURAL_INSERT, "")]
    assert deleted.text == source
    assert _kinds(deleted) == [(ReportKind.STRUCTURAL_DELETE, "")]


@pytest.mark.parametrize(
    "export", ["curl -H token https://api", "curl -H MYTOKEN https://api"]
)
def test_a_code_block_restyled_as_text_is_a_reported_code_edit(export: str) -> None:
    source = "# T\n\nRun this:\n\n```bash\ncurl -H token https://api\n```\n\nThen.\n"

    result = _local(source, ("```bash\ncurl -H token https://api\n```", export))

    assert result.text == source
    assert [(r.kind, r.block.kind) for r in result.reports] == [
        (ReportKind.CODE_EDIT, Kind.FENCE)
    ]


def test_a_code_block_language_change_is_a_reported_code_edit() -> None:
    source = "# T\n\nRun this:\n\n```bash\nls\n```\n"

    result = _local(source, ("```bash", "```python"))

    assert result.text == source
    assert [(r.kind, r.message) for r in result.reports] == [
        (
            ReportKind.CODE_EDIT,
            "the code block's language 'bash' became 'python' in the Doc;"
            " change it in the source",
        )
    ]


# Inserted blocks


def test_paragraph_added_to_a_list_item_with_a_note_follows_the_item() -> None:
    # A comment ends the item's line, so the new paragraph goes after that line.
    result = _sampler(
        (
            "3. Start a new Claude Code session.  \n",
            "3. Start a new Claude Code session.  \n     \n"
            "   A new paragraph in item three.  \n",
        )
    )

    assert result.text == _read("sampler.source.md").replace(
        "1. Start a new Claude Code session. <!-- TODO: an inline note on a list"
        " item. -->\n",
        "1. Start a new Claude Code session. <!-- TODO: an inline note on a list"
        " item. -->\n\n   A new paragraph in item three.\n",
    )
    assert result.reports == ()


def test_paragraph_added_to_a_list_item_before_its_note_follows_the_item() -> None:
    source = "# T\n\n1. Install it. <!-- check the version -->\n1. Run it.\n"
    baseline = "# T\n\n1. Install it.  \n     \n   **Author note:** check the version  \n2. Run it."
    edited = baseline.replace(
        "1. Install it.  \n", "1. Install it.  \n     \n   Use the latest release.  \n"
    )

    result = apply_edits(page="p", source=source, baseline=baseline, edited=edited)

    assert result.text == (
        "# T\n\n1. Install it. <!-- check the version -->\n\n"
        "   Use the latest release.\n1. Run it.\n"
    )
    assert result.reports == ()


def test_paragraph_added_to_a_plain_list_item_follows_the_item() -> None:
    source = "# T\n\n- Install it.\n- Run it.\n"
    baseline = "# T\n\n- Install it.  \n- Run it."
    edited = baseline.replace(
        "- Install it.  \n", "- Install it.  \n    \n  Use the latest release.  \n"
    )

    result = apply_edits(page="p", source=source, baseline=baseline, edited=edited)

    assert (
        result.text == "# T\n\n- Install it.\n\n  Use the latest release.\n- Run it.\n"
    )
    assert result.reports == ()


def test_paragraph_added_after_a_nested_list_continues_the_outer_item() -> None:
    source = "# T\n\n- Outer.\n  - Inner.\n- Next.\n"
    baseline = "# T\n\n- Outer.  \n  - Inner.  \n- Next."
    edited = baseline.replace(
        "  - Inner.  \n", "  - Inner.  \n    \n  More on outer.  \n"
    )

    result = apply_edits(page="p", source=source, baseline=baseline, edited=edited)

    assert result.text == "# T\n\n- Outer.\n  - Inner.\n\n  More on outer.\n- Next.\n"
    assert result.reports == ()


def test_a_live_export_applies_a_resolved_note_enter_and_a_closing_line() -> None:
    note = "TODO: add the public base URL once the API access policy exists."
    paragraph = (
        "Bundles carry a reproducing call with an `Authorization: Bearer"
        " $DFO_API_KEY` header. The development deployment answers without it."
    )
    last_item = (
        "- [Resolve a question](resolve-a-question.md) shows how a `200` Search"
        " response reports an unanswered question."
    )

    result = _recorded("conventions-live", _read("pages/conventions-live.edited.md"))

    assert result.text == _edit(
        _read("pages/conventions-live.source.md"),
        (f"<!-- {note} -->", "The public base URL is shared on request."),
        (paragraph, f"{paragraph}\n\nAn added sentence typed with Enter."),
        (last_item, f"{last_item}\n\nA closing line typed below the list."),
    )
    assert _messages(result) == [NOTE_TO_TEXT]


@pytest.mark.parametrize(
    ("source", "edit", "written"),
    [
        (
            "# T\n\n- One.\n- Two.\n",
            ("- Two.\n", "- Two.\n\nTyped below.\n"),
            "# T\n\n- One.\n- Two.\n\nTyped below.\n",
        ),
        (
            "# T\n\n1. One.\n2. Two.\n\n## Next\n\nEnd.\n",
            ("2. Two.\n", "2. Two.\n\nTyped below.\n"),
            "# T\n\n1. One.\n2. Two.\n\nTyped below.\n\n## Next\n\nEnd.\n",
        ),
        (
            "# T\n\n- One.\n  - Inner.\n\n```sh\nrun\n```\n",
            ("  - Inner.\n", "  - Inner.\n\nTyped below.\n"),
            "# T\n\n- One.\n  - Inner.\n\nTyped below.\n\n```sh\nrun\n```\n",
        ),
    ],
    ids=["end-of-page", "before-a-heading", "after-a-nested-item-before-code"],
)
def test_a_paragraph_typed_below_a_list_goes_after_the_list(
    source: str, edit: tuple[str, str], written: str
) -> None:
    result = _local(source, edit)

    assert result.text == written
    assert result.reports == ()


def test_inserted_paragraph_in_a_callout_takes_its_indent() -> None:
    result = _sampler(
        (
            "> Second callout paragraph.  \n",
            "> Second callout paragraph.  \n> More.  \n",
        )
    )

    assert "    Second callout paragraph.\n\n    More.\n" in result.text
    assert result.reports == ()


def test_inserted_author_note_becomes_a_comment() -> None:
    result = _sampler(
        (
            "Then more.\n",
            "Then more.  \n**Author note:** TODO: check the \\<years\\>.\n",
        )
    )

    assert "Then more.\n\n<!-- TODO: check the <years>. -->\n" in result.text


def test_inserted_heading_is_placed_at_top_level() -> None:
    result = _sampler(("## Next\n", "## Next\n\n### Also\n"))

    assert "## Next\n\n### Also\n\n- [Share live data" in result.text


def test_paragraph_after_a_fence_in_a_list_is_reported() -> None:
    result = _sampler(
        (
            "mkdir -p ~/.claude/skills\n```\n",
            "mkdir -p ~/.claude/skills\n```\n\nWhere does this go?\n",
        )
    )

    assert result.text == _read("sampler.source.md")
    assert _messages(result) == [
        _refused(
            "a paragraph added next to a code block in a list cannot be placed",
            "Where does this go?",
        )
    ]


@pytest.mark.parametrize(
    ("replacement", "kind"),
    [
        (('```\n{"a": 1}\n```\n', '```\n{"a": 1}\n```\n\n```\nnew\n```\n'), Kind.FENCE),
        (("## Next\n", "## Next\n\n**Tab: New**\n"), Kind.TAB_LABEL),
        (("## Next\n", "## Next\n\n> **Note:**\n"), Kind.CALLOUT),
    ],
)
def test_structural_insert_is_reported(
    replacement: tuple[str, str], kind: Kind
) -> None:
    result = _sampler(replacement)

    reported = [r for r in result.reports if r.kind is ReportKind.STRUCTURAL_INSERT]
    assert [r.block.kind for r in reported] == [kind]
    assert result.text == _read("sampler.source.md")


def test_added_table_row_is_reported() -> None:
    result = _sampler(
        (
            "| The MCP server guide |\n",
            "| The MCP server guide |\n| One | Two | Three |\n",
        )
    )

    assert result.text == _read("sampler.source.md")
    assert {r.kind for r in result.reports} == {ReportKind.TABLE_SHAPE}
    assert len(result.reports) == 3


# Deleted blocks


def test_deleted_fence_and_tab_label_are_reported() -> None:
    result = _sampler(
        ('```\n{"a": 1}\n```\n', ""), ("   **Tab: For every session**\n", "")
    )

    assert result.text == _read("sampler.source.md")
    assert _kinds(result) == [
        (ReportKind.STRUCTURAL_DELETE, "For every session"),
        (ReportKind.STRUCTURAL_DELETE, '{"a": 1}\n'),
    ]


def test_deleted_table_row_is_reported() -> None:
    result = _sampler(
        (
            "| CRS disbursements to Nigeria as CSV | Search on [/data](http:///data)"
            " | [Get data](./get-started/get-data.md) |\n",
            "",
        )
    )

    assert result.text == _read("sampler.source.md")
    assert {r.kind for r in result.reports} == {ReportKind.TABLE_SHAPE}


def test_deleted_table_cell_note_is_removed_in_place() -> None:
    result = _sampler(
        (
            "**Author note:** TODO: link when the MCP endpoint and its guide are public\n",
            "",
        )
    )

    assert result.text == _read("sampler.source.md").replace(
        " <!-- TODO: link when the MCP endpoint and its guide are public -->", ""
    )


def test_deleting_every_callout_paragraph_is_reported() -> None:
    result = _sampler(
        (
            '> **Tip:** Under the sentence, "Why these results?" opens the steps /data took.  \n>   \n',
            "> **Tip:**  \n>   \n",
        )
    )

    assert result.text == _read("sampler.source.md")
    assert [r.kind for r in result.reports] == [ReportKind.STRUCTURAL_DELETE]


def test_deleting_a_list_item_lead_with_children_is_reported() -> None:
    result = _sampler(("- Outer item one  \n    \n", ""))

    assert result.text == _read("sampler.source.md")
    assert (
        ReportKind.NOT_APPLIED,
        "removing the first paragraph of a list item that holds more is not applied",
    ) in [
        (r.kind, r.message) for r in result.reports if r.block.text == "Outer item one"
    ]


@pytest.mark.parametrize(
    "after", ["> A quote.", "Plain paragraph.", "!!! note\n\n    A callout."]
)
def test_deleting_the_last_list_item_before_another_block(after: str) -> None:
    source = f"# T\n\n- one\n- two\n- three\n\n{after}\n"

    result = _local(source, ("- two\n- three", "- two"))

    assert result.text == source.replace("- three\n", "")
    assert result.reports == ()


def test_reordering_list_items_moves_the_item() -> None:
    source = "# T\n\n- one\n- two\n- three\n\n> A quote.\n"

    result = _local(source, ("- two\n- three", "- three\n- two"))

    assert result.text == "# T\n\n- one\n- three\n- two\n\n> A quote.\n"
    assert result.reports == ()


def test_deleting_a_host_whose_note_stays_is_reported() -> None:
    result = _sampler(("3. Start a new Claude Code session.  \n     \n", ""))

    assert result.text == _read("sampler.source.md")
    assert (
        ReportKind.NOT_APPLIED,
        "its line holds text that stays, so it is not removed",
    ) in [
        (r.kind, r.message)
        for r in result.reports
        if r.block.text == "Start a new Claude Code session."
    ]


def test_deleting_a_host_and_its_note_removes_the_line() -> None:
    result = _sampler(
        (
            "3. Start a new Claude Code session.  \n     \n"
            "   **Author note:** TODO: an inline note on a list item.  \n     \n",
            "",
        )
    )

    assert "Start a new Claude Code session" not in result.text
    assert (
        "   The `_template` directory holds the files for creating a new skill.\n\n- Outer item one\n"
        in result.text
    )


def test_a_hash_typed_at_the_end_of_a_heading_keeps_its_escape() -> None:
    result = _sampler(("## Next", "## Next \\#"))

    assert "\n## Next \\#\n" in result.text


def test_an_emptied_heading_is_a_deleted_heading() -> None:
    result = _sampler(("## Next", "##"))

    assert result.text == _edit(_read("sampler.source.md"), ("\n## Next\n", ""))
    assert [(r.kind, r.message) for r in result.reports] == [
        (ReportKind.HEADING_ANCHOR, "heading removed with anchor #next")
    ]


def test_deleted_heading_reports_its_anchor() -> None:
    result = _local("# T\n\nA.\n\n## Old section\n\nB.\n", ("## Old section\n\n", ""))

    assert result.text == "# T\n\nA.\n\nB.\n"
    assert [(r.kind, r.message) for r in result.reports] == [
        (ReportKind.HEADING_ANCHOR, "heading removed with anchor #old-section")
    ]


@pytest.mark.parametrize(
    ("heading", "anchor"),
    [
        ("Step 2: change the years", "step-2-change-the-years"),
        ("Use `get_data` with **pandas**", "use-get_data-with-pandas"),
        ("[Links](x.md) & more  here", "links-more-here"),
        ("Café API", "caf-api"),
    ],
)
def test_heading_anchor_matches_the_site_slug(heading: str, anchor: str) -> None:
    assert heading_anchor(heading) == anchor


def test_deleting_the_last_paragraph_drops_the_blank_line_before_it() -> None:
    result = _local("# T\n\nA.\n\nB.\n", ("\n\nB.\n", "\n"))

    assert result.text == "# T\n\nA.\n"


# Repeated text

REPEATED = "the same text appears more than once here, so which copy changed is unclear"


def _rewritten(source: str, edited: str) -> EditResult:
    """Apply a Doc export written whole, for edits a unique replacement cannot name."""
    return apply_edits(
        page="p", source=source, baseline=to_doc_markdown(source), edited=edited
    )


@pytest.mark.parametrize(
    "source",
    [
        "# T\n\nSame.\n\n- Same.\n",
        "# T\n\n1. Same.\n\n- Same.\n",
        "# T\n\n- Same.\n\n  Same.\n",
    ],
)
def test_an_edit_to_text_repeated_in_another_place_keeps_the_other(
    source: str,
) -> None:
    edited = source.replace("Same.", "Changed.", 1)

    result = _rewritten(source, edited)

    assert result.text == edited
    assert result.reports == ()


@pytest.mark.parametrize("column", [0, 1])
def test_an_edit_to_one_of_two_identical_cells_in_the_last_row_applies(
    column: int,
) -> None:
    source = "# T\n\nIntro.\n\n| A | B |\n|---|---|\n| x | y |\n| Same | Same |\n"
    cells = ["Same", "Same"]
    cells[column] = "Changed"
    edited = source.replace("| Same | Same |", f"| {cells[0]} | {cells[1]} |")

    result = _rewritten(source, edited)

    assert result.text == edited
    assert result.reports == ()


def test_an_edit_to_the_first_of_two_identical_items_keeps_the_second() -> None:
    source = "# T\n\n- *Same.*\n- _Same._\n"

    result = _rewritten(source, "# T\n\n- *Changed.*\n- *Same.*\n")

    assert result.text == "# T\n\n- *Changed.*\n- _Same._\n"
    assert result.reports == ()


@pytest.mark.parametrize(
    ("source", "edited", "quotes"),
    [
        ("# T\n\n*Same.*\n\n_Same._\n", "# T\n\n*Same.*\n", ["*Same.*"]),
        (
            "# T\n\nA.\n\n*Same.*\n\n_Same._\n",
            "# T\n\n*Same.*\n\nA.\n\n*Same.*\n",
            ["*Same.*", "*Same.*"],
        ),
    ],
)
def test_a_change_to_repeated_text_that_could_be_either_copy_is_refused(
    source: str, edited: str, quotes: list[str]
) -> None:
    result = _rewritten(source, edited)

    assert result.text == source
    assert _messages(result) == [_refused(REPEATED, quote) for quote in quotes]


# Merging onto the current source


PUSHED = "# T\n\nOne.\n\nTwo.\n\nThree.\n"


def test_merge_carries_edits_onto_upstream_changes() -> None:
    result = merge_onto_current(
        pushed=PUSHED,
        edited=PUSHED.replace("One.", "One, edited."),
        current=PUSHED.replace("Three.", "Three, upstream."),
    )

    assert result.text == "# T\n\nOne, edited.\n\nTwo.\n\nThree, upstream.\n"
    assert result.clashes == ()


def test_merge_clash_takes_the_editor_text() -> None:
    result = merge_onto_current(
        pushed=PUSHED,
        edited=PUSHED.replace("Two.", "Two, edited."),
        current=PUSHED.replace("Two.", "Two, upstream.").replace("One.", "Uno."),
    )

    assert result.text == "# T\n\nUno.\n\nTwo, edited.\n\nThree.\n"
    assert result.clashes == (
        Clash(editor_text="Two, edited.\n", upstream_text="Two, upstream.\n"),
    )


@pytest.mark.parametrize(
    ("pushed", "upstream", "editor"),
    [
        (
            "# T\n\n- Alpha item.\n- Beta item.\n- Gamma item.\n\nEnd.\n",
            ("Alpha item.", "Alpha item, fixed upstream."),
            ("Beta item.", "Beta item, edited in Docs."),
        ),
        (
            "| a | b |\n| - | - |\n| 1 | 2 |\n| 3 | 4 |\n",
            ("| 1 | 2 |", "| 1 | 22 |"),
            ("| 3 | 4 |", "| 3 | 44 |"),
        ),
    ],
)
def test_merge_keeps_both_edits_to_adjacent_lines(
    pushed: str, upstream: tuple[str, str], editor: tuple[str, str]
) -> None:
    result = merge_onto_current(
        pushed=pushed,
        edited=pushed.replace(*editor),
        current=pushed.replace(*upstream),
    )

    assert result.text == pushed.replace(*upstream).replace(*editor)
    assert result.clashes == ()


def test_merge_clashes_only_on_the_lines_both_sides_changed() -> None:
    pushed = "- Alpha.\n- Beta.\n- Gamma.\n"

    result = merge_onto_current(
        pushed=pushed,
        edited=pushed.replace("Beta.", "Beta, editor.").replace(
            "Gamma.", "Gamma, editor."
        ),
        current=pushed.replace("Alpha.", "Alpha, upstream.").replace(
            "Beta.", "Beta, upstream."
        ),
    )

    assert result.text == "- Alpha, upstream.\n- Beta, editor.\n- Gamma, editor.\n"
    assert result.clashes == (
        Clash(editor_text="- Beta, editor.\n", upstream_text="- Beta, upstream.\n"),
    )


@pytest.mark.parametrize(
    "current",
    ["- A.\n- X.\n- B.\n- C.\n", "- A.\n- B.\n- X.\n- C.\n"],
    ids=["insert-before", "insert-after"],
)
def test_merge_keeps_an_upstream_insert_beside_an_edited_line(current: str) -> None:
    pushed = "- A.\n- B.\n- C.\n"

    result = merge_onto_current(
        pushed=pushed, edited=pushed.replace("B.", "B, editor."), current=current
    )

    assert result.text == current.replace("B.", "B, editor.")
    assert result.clashes == ()


def test_merge_clashes_when_both_sides_change_one_line() -> None:
    pushed = "- A.\n- B.\n- C.\n"

    result = merge_onto_current(
        pushed=pushed,
        edited=pushed.replace("B.", "B, editor."),
        current=pushed.replace("B.", "B, upstream."),
    )

    assert result.text == "- A.\n- B, editor.\n- C.\n"
    assert result.clashes == (
        Clash(editor_text="- B, editor.\n", upstream_text="- B, upstream.\n"),
    )


def test_merge_keeps_both_edits_to_different_words_of_one_line() -> None:
    pushed = "# T\n\nSend a request with your token and read the reply.\n\nEnd.\n"

    result = merge_onto_current(
        pushed=pushed,
        edited=pushed.replace("the reply", "the JSON reply"),
        current=pushed.replace("a request", "a GET request"),
    )

    assert result.text == pushed.replace("a request", "a GET request").replace(
        "the reply", "the JSON reply"
    )
    assert result.clashes == ()


def test_merge_clashes_only_on_the_words_both_sides_changed() -> None:
    pushed = "# T\n\nSend a request and read the reply.\n"

    result = merge_onto_current(
        pushed=pushed,
        edited=pushed.replace("a request", "one request").replace("reply", "answer"),
        current=pushed.replace("a request", "the request"),
    )

    assert result.text == "# T\n\nSend one request and read the answer.\n"
    assert result.clashes == (
        Clash(
            editor_text="Send one request and read the answer.\n",
            upstream_text="Send the request and read the reply.\n",
        ),
    )


def test_merge_with_no_upstream_change_is_the_edited_text() -> None:
    edited = PUSHED.replace("Two.", "Two, edited.")

    result = merge_onto_current(pushed=PUSHED, edited=edited, current=PUSHED)

    assert result.text == edited
    assert result.clashes == ()


def test_merge_keeps_conflict_markers_the_page_holds() -> None:
    page = "# T\n\n```text\n<<<<<<< ours\n=======\n>>>>>>> theirs\n```\n\nOne.\n"

    result = merge_onto_current(
        pushed=page, edited=page.replace("One.", "Two."), current=page
    )

    assert result.text == page.replace("One.", "Two.")


@pytest.mark.parametrize(
    ("editor", "merged"),
    [
        ("The box ED2 that opens", "The ED2 that UP opens"),
        ("The box which opens", "The which UP opens"),
    ],
)
def test_merge_keeps_an_insertion_between_an_upstream_delete_and_insert(
    editor: str, merged: str
) -> None:
    pushed = "# T\n\nThe box that opens has two tabs.\n"

    result = merge_onto_current(
        pushed=pushed,
        edited=pushed.replace("The box that opens", editor),
        current=pushed.replace("The box that opens", "The that UP opens"),
    )

    assert result.text == pushed.replace("The box that opens", merged)
    assert result.clashes == ()


def test_merge_keeps_crlf_line_ends() -> None:
    result = merge_onto_current(
        pushed="a b\r\nc\r\n", edited="a B\r\nc\r\n", current="A b\r\nc\r\n"
    )

    assert result.text == "A B\r\nc\r\n"


@pytest.mark.parametrize(
    ("pushed", "edited", "current", "merged"),
    [
        ("x y", "x Y", "X y", "X Y"),
        ("x y\n", "x Y", "X y\n", "X Y"),
        ("x y", "x Y", "X y\n", "X Y\n"),
    ],
)
def test_merge_keeps_the_final_newline_a_side_chose(
    pushed: str, edited: str, current: str, merged: str
) -> None:
    result = merge_onto_current(pushed=pushed, edited=edited, current=current)

    assert result.text == merged


def test_merge_drops_a_final_crlf_the_editor_removed() -> None:
    result = merge_onto_current(
        pushed="a\r\nb\r\n", edited="A\r\nb", current="a\r\nb\r\nc\r\n"
    )

    assert result.text == "A\r\nb\r\nc"


def test_merge_keeps_an_upstream_rewrap_beside_an_editor_word() -> None:
    result = merge_onto_current(
        pushed="# T\n\none two five six seven\n",
        edited="# T\n\none two FIVE six seven\n",
        current="# T\n\none two five\nsix seven\n",
    )

    assert result.text == "# T\n\none two FIVE\nsix seven\n"
    assert result.clashes == ()


def test_merge_markers_outrun_the_pages_own() -> None:
    rule = "=" * 41

    result = merge_onto_current(
        pushed="x\n\nend\n",
        edited=f"x\n\nEditor title\n{rule}\n",
        current=f"x\n\nUpstream title\n{rule}\n",
    )

    assert result.text == f"x\n\nEditor title\n{rule}\n"
    assert result.clashes == (
        Clash(
            editor_text=f"Editor title\n{rule}\n",
            upstream_text=f"Upstream title\n{rule}\n",
        ),
    )
