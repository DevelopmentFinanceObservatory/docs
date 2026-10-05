"""The leaf blocks docsync aligns between a source page and its Google Doc export.

A page is an ordered sequence of leaf blocks in Doc order. Containers (lists,
blockquotes, callouts) hold blocks, and their paragraphs are the blocks.
`adapter.parse_blocks` builds the sequence from a source file or from a Doc's
Markdown export, and the two sequences of one page align 1:1 by position and
`family`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Kind(StrEnum):
    """What a leaf block is.

    `DESCRIPTION` is the front-matter `description`. `CALLOUT` is a callout's
    `!!! note` marker, shown in the Doc as the bold `Note:` lead of its first
    paragraph. Its text is the label, such as `Note`. `CALLOUT_PARAGRAPH` is a
    paragraph directly in a callout body. `AUTHOR_NOTE` is an HTML comment, shown in
    the Doc as a paragraph opening `Author note:`. `TAB_LABEL` is a `::tab{label=...}`
    directive. Its text is the label. `FENCE` is a fenced or indented code block. Its
    text is the code. `TABLE_CELL` is one cell of a GFM table, header row included.
    `RULE` is a horizontal rule. Its text is empty.
    """

    DESCRIPTION = "description"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    BLOCKQUOTE = "blockquote"
    CALLOUT = "callout"
    CALLOUT_PARAGRAPH = "callout_paragraph"
    AUTHOR_NOTE = "author_note"
    TAB_LABEL = "tab_label"
    FENCE = "fence"
    TABLE_CELL = "table_cell"
    RULE = "rule"


# Paragraph kinds that share one alignment family.
#
# A Doc export loses the container a paragraph sat in. Google merges adjacent
# blockquotes, so a callout body and a following quote read as one quote, and a
# paragraph after a fence in a list item comes back outside the list.
PROSE_KINDS = frozenset(
    {Kind.PARAGRAPH, Kind.LIST_ITEM, Kind.BLOCKQUOTE, Kind.CALLOUT_PARAGRAPH}
)

# Kinds whose source text is not Markdown: a YAML value, a comment, a label.
PLAIN_KINDS = frozenset({Kind.DESCRIPTION, Kind.AUTHOR_NOTE, Kind.TAB_LABEL})


@dataclass(frozen=True)
class Cell:
    """Where a `TABLE_CELL` sits: the table's line span and the cell's position.

    `lines` is `[start, end)` over the whole table, header and delimiter rows
    included. `row` 0 is the header row; body rows count from 1. `bold` is set for a
    source header cell written whole in bold (`**Task**`): its block's text and span
    are what sits inside the `**`, since Google drops a header cell's bold.
    """

    lines: tuple[int, int]
    row: int
    column: int
    bold: bool = False


@dataclass(frozen=True)
class Block:
    """One leaf block of a page.

    `text` is what alignment compares. For prose, headings, cells and author notes it
    is the inline Markdown, with a trailing HTML comment removed (the comment is its
    own `AUTHOR_NOTE`) and soft line breaks joined by a space. For a fence it is the
    code, for a callout or tab label the label, and for a description the YAML value.

    `span` is `[start, end)` character offsets into the parsed text, covering:

    - prose, heading, cell: the inline text, without container markers, list
      markers, heading markers, or a trailing comment;
    - author note: the whole `<!-- ... -->`;
    - fence: every line from the opening to the closing fence;
    - callout: the `!!! note` line; tab label: the `::tab{...}` directive;
    - description: the YAML scalar after `description: `, a folded `>-` scalar
      through its last line;
    - rule: the rule's markup, such as `---`.

    `lines` is `[start, end)` over the source lines the block's span touches.
    `prefix` is the text of `lines[0]` before `span` starts. `continuation` is the
    prefix a new paragraph needs to sit in the same container directly after this
    block: `"   "` in an ordered list item, `"> "` in a blockquote, `"    "` in a
    callout body, `""` at top level. `depth` counts the containers (list items,
    blockquotes, callouts) around the block. `cell` is set for `TABLE_CELL` only.
    `level` is a heading's level, 1 to 6, and 0 for every other kind. `info` is a
    fenced code block's info string, such as `bash`, and empty for every other kind.

    `line_spans` is set for prose and headings: the `[start, end)` span of the
    block's text on each line it covers, so `text` is those slices joined by single
    spaces. A splice uses it to keep the source's line breaks.

    A hard break (a line ending in two spaces) ends a leaf, so one Markdown paragraph
    can be several leaves. `after_break` is set on each leaf after the first: it
    continues the leaf before it across a hard break. In an export, a paragraph made
    with Enter in the Doc reads the same way.
    """

    kind: Kind
    text: str
    span: tuple[int, int]
    lines: tuple[int, int]
    prefix: str
    continuation: str
    depth: int
    cell: Cell | None = None
    level: int = 0
    info: str = ""
    line_spans: tuple[tuple[int, int], ...] = ()
    after_break: bool = False

    @property
    def family(self) -> str:
        """The alignment family: `"prose"` for every `PROSE_KINDS` kind, else the kind."""
        return "prose" if self.kind in PROSE_KINDS else self.kind.value
