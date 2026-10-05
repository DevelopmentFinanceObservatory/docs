"""Translate between a source page and its Google Doc.

`to_doc_markdown` rewrites a source page into the Markdown docsync uploads, a form
Google keeps on import and gives back on export. `parse_blocks` reads either side
into leaf blocks (`blocks.Block`), and `align_baseline` pairs a source page's blocks
with the blocks of the Doc's first export, refusing the page when a pair differs.
Two blocks' texts are the same when markdown-it renders them to the same HTML after
`normalise` (`rendered_text`), so an escape Google adds (`1960\\.`) or drops
(`&amp;` exported as `&`) changes nothing. `editor_text` turns a Doc block's text into
the text a splice writes into the source.

The Doc form of each source construct:

- front matter: its `description` only, as a first paragraph `**Description:** ...`;
- `!!! note` callout: a blockquote whose first paragraph opens `**Note:** `;
- HTML comment: a paragraph `**Author note:** ...` in the comment's container. A
  comment that ends a line of text becomes such a paragraph directly after its block,
  and a comment in a table cell one directly after the table;
- `::tab{label="X"}`: a paragraph `**Tab: X**`; `:::tabs` and `:::` lines are dropped;
- a bare relative link target `x.md`: `./x.md`, since Google turns `x.md` into
  `http://x.md`.

Every other line is uploaded as the source holds it.
"""

from __future__ import annotations

import heapq
import html
import itertools
import re
from collections.abc import Callable, Iterable, Iterator, Sequence, Set
from dataclasses import dataclass, field, replace
from enum import StrEnum

import yaml
from markdown_it import MarkdownIt
from markdown_it.token import Token

from dfo_docs.docsync.blocks import Block, Cell, Kind
from dfo_docs.normalise import (
    _ADMONITION_MARKER_RE,
    _ADMONITION_TYPES,
    _COMMENT_RE,
    _LINK_RE,
    FRONTMATTER_RE,
    _extract_admonition_body,
)

_MARKDOWN = MarkdownIt("commonmark").enable("table")

_TABS_FENCE_RE = re.compile(r"^(?P<indent>[ \t]*):::(?:tabs)?[ \t]*$")
_TAB_RE = re.compile(r'^(?P<indent>[ \t]*)::tab\{label="(?P<label>[^"]*)"\}[ \t]*$')
_DESCRIPTION_LINE_RE = re.compile(r"^description:[ \t]*(?P<value>.*?)[ \t]*$")
_CODE_SPAN_RE = re.compile(r"(?<!`)(?P<ticks>`+)(?!`).*?(?<!`)(?P=ticks)(?!`)")
_LIST_MARKER_RE = re.compile(r"(?:[-*+]|\d{1,9}[.)])(?=[ \t]|$)")
_URL_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")

_CLOSING_HASHES_RE = re.compile(r"(?<=\S)[ \t]+#+$")
_MOVED_SPACE_RE = re.compile(r"  (?=\S)")
_BOLD_CELL_RE = re.compile(r"^\*\*(?P<inner>(?:(?!\*\*).)+)\*\*$")
_DESCRIPTION_LEAD = "**Description:** "
_AUTHOR_NOTE_LEAD = "**Author note:** "
_TAB_LABEL_RE = re.compile(r"^\*\*Tab: (?P<label>.+)\*\*$")
_CALLOUT_LABELS = "|".join(sorted(kind.capitalize() for kind in _ADMONITION_TYPES))
_CALLOUT_LEAD_RE = re.compile(rf"^\*\*(?P<label>{_CALLOUT_LABELS}):\*\*(?: |$)")
# Any lead the Doc form gives a block: `**Author note:**`, `**Note:**`, `**Tab: `.
_LEAD_RE = re.compile(
    rf"\*\*(?:(?P<label>Author note|Description|{_CALLOUT_LABELS}):\*\*|(?P<tab>Tab): )"
)

# A backslash escape of ASCII punctuation. Google escapes punctuation the source
# writes bare: `1960\.`, `spec\_id`, `Chat \+ Canvas`, `oda-\*`, `apis\#981`.
_ESCAPE_RE = re.compile(r"\\(?P<char>[!-/:-@\[-`{-~])")
_CURLY_QUOTES = str.maketrans(
    {"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"}
)


def _unlink_bare_url(match: re.Match[str]) -> str:
    url = match.group("url")
    return url if _ESCAPE_RE.sub(r"\g<char>", match.group("text")) == url else match[0]


def _unlink_bare_address(match: re.Match[str]) -> str:
    address = match.group("address")
    unescaped = _ESCAPE_RE.sub(r"\g<char>", match.group("text"))
    return address if unescaped == address else match[0]


# Google's Markdown export, mapped back to the source dialect, outside code spans:
# only what rendering would not absorb. Each rule is pinned by a test and observed in
# a recorded export under tests/docsync/fixtures/.
_NORMALISE_RULES: tuple[
    tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]], ...
] = (
    # A root-relative target `/data` exports as `http:///data`.
    (re.compile(r"(?<=\]\()http://(?=/)"), ""),
    # `to_doc_markdown` writes a bare relative target `x.md` as `./x.md`.
    (re.compile(r"(?<=\]\()\./"), ""),
    # Google links a bare URL: `https://x/` exports as `[https\://x/](https://x/)`.
    (
        re.compile(r"\[(?P<text>[^\]\s]+)\]\((?P<url>https?://[^)\s]+)\)"),
        _unlink_bare_url,
    ),
    # And a bare address: `data@one.org` exports as `[data@one.org](mailto:data@one.org)`.
    (
        re.compile(r"\[(?P<text>[^\]\s]+)\]\(mailto:(?P<address>[^)\s@]+@[^)\s]+)\)"),
        _unlink_bare_address,
    ),
)


class Dialect(StrEnum):
    """Which Markdown `parse_blocks` reads: a source page or a Doc's export."""

    SOURCE = "source"
    EXPORT = "export"


class BlockError(ValueError):
    """A page holds a construct the block model cannot represent."""


class BaselineMismatchError(ValueError):
    """A source block and the block at the same position in the baseline export differ.

    `source` or `baseline` is None when that side has fewer blocks than `index`.
    """

    def __init__(
        self,
        *,
        page: str,
        index: int,
        source: Block | None,
        baseline: Block | None,
    ) -> None:
        self.page = page
        self.index = index
        self.source = source
        self.baseline = baseline
        super().__init__(
            f"{page}: block {index} differs between the source and the Doc baseline:"
            f" source {_describe(source)}, baseline {_describe(baseline)}"
        )


@dataclass(frozen=True)
class BlockPair:
    """A source block and the baseline export block aligned with it."""

    source: Block
    baseline: Block


def normalise(text: str) -> str:
    """Map a block's text from Google's export dialect towards the source dialect.

    Only what rendering does not absorb: link targets Google or `to_doc_markdown`
    rewrote, bare URLs and addresses Google linked, and trailing hard-break spaces.
    Escapes stay, since `rendered_text` reads them. Code spans pass through
    unchanged, except that Google moves a code span's trailing space outside it:
    `` `Bearer ` followed `` exports as `` `Bearer`  followed ``, so a code span
    followed by two spaces and text takes one space back.
    """
    pieces = []
    position = 0
    for code in _CODE_SPAN_RE.finditer(text):
        pieces.append(_normalise_prose(text[position : code.start()]))
        position = code.end()
        ticks = code.group("ticks")
        if _MOVED_SPACE_RE.match(text, position):
            pieces.append(f"{code.group()[: -len(ticks)]} {ticks}")
            position += 1
        else:
            pieces.append(code.group())
    pieces.append(_normalise_prose(text[position:]))
    return "".join(pieces).rstrip()


def _normalise_prose(text: str) -> str:
    for pattern, replacement in _NORMALISE_RULES:
        text = pattern.sub(replacement, text)
    return text


def rendered_text(block: Block, *, dialect: Dialect) -> str:
    """What alignment compares for a block: its text as markdown-it renders it.

    A fence's text is its code, compared exactly. A source description or author
    note renders in its Doc form, as `to_doc_markdown` uploads it.
    """
    if block.kind is Kind.FENCE:
        return block.text
    text = block.text
    if dialect is Dialect.SOURCE and block.kind in {Kind.DESCRIPTION, Kind.AUTHOR_NOTE}:
        text = _doc_text(text)
    return _MARKDOWN.renderInline(normalise(text))


type ContentKey = tuple[str, int, int, str, str]


def content_key(block: Block, *, dialect: Dialect) -> ContentKey:
    """A block's kind, depth, heading level, `rendered_text` and fence info string.

    Two exports whose blocks have the same keys hold the same content, structure
    included: a heading's level, a paragraph turned into a list item or a quote, a
    code block's language.
    """
    return (
        block.kind.value,
        block.depth,
        block.level,
        rendered_text(block, dialect=dialect),
        block.info,
    )


def export_content_key(export: str) -> tuple[ContentKey, ...]:
    """The `content_key` of every block of a Doc export, in order.

    Raises:
        BlockError: The export holds a construct the block model cannot represent.
    """
    return tuple(
        content_key(block, dialect=Dialect.EXPORT)
        for block in parse_blocks(export, dialect=Dialect.EXPORT)
    )


def editor_text(
    text: str, *, markdown: bool, around: tuple[str, str] = ("", "")
) -> str:
    """The text a splice writes into the source for a Doc block's `text`.

    After `normalise`, curly quotes become straight ones outside code spans, as the
    sources write them. In Markdown text each escape Google added is removed where
    the text renders the same without it, and kept where it does not: `\\<host\\>`
    becomes `\\<host>`, and `2\\*3\\*4` keeps an escape so it stays literal. Escapes
    go from the right, so an opener keeps its escape. `around` is the source text
    written before and after the result, such as a heading's `## ` or a bold header
    cell's `**`, and counts for the rendering. Text that is not Markdown
    (`markdown=False`: a description, an author note, a tab label) loses every
    escape.
    """
    text = straight_quotes(normalise(text))
    if not markdown:
        return _outside_code(text, lambda prose: _ESCAPE_RE.sub(r"\g<char>", prose))
    return drop_needless_escapes([around[0], text, around[1]], editable={1})[1]


def straight_quotes(text: str) -> str:
    """`text` with curly quotes made straight outside code spans."""
    return _outside_code(text, lambda prose: prose.translate(_CURLY_QUOTES))


def drop_needless_escapes(parts: Sequence[str], *, editable: Set[int]) -> list[str]:
    """`parts` with each escape in an `editable` part removed where it changes nothing.

    An escape outside code spans goes when the joined parts render the same without
    it, inline and as a block. Escapes go from the right, so an opener keeps its
    escape: `\\<host\\>` becomes `\\<host>`, and `2\\*3\\*4` keeps one escape.
    """
    parts = list(parts)
    target = _render_both("".join(parts))
    for index in sorted(editable, reverse=True):
        text = parts[index]
        code = [match.span() for match in _CODE_SPAN_RE.finditer(text)]
        escapes = [
            match.start()
            for match in _ESCAPE_RE.finditer(text)
            if not any(start <= match.start() < end for start, end in code)
        ]
        for position in reversed(escapes):
            candidate = text[:position] + text[position + 1 :]
            trial = [*parts[:index], candidate, *parts[index + 1 :]]
            if _render_both("".join(trial)) == target:
                text = candidate
                parts[index] = text
    return parts


# One inline token: a code span, a link target with its brackets, an autolink, an
# escape, an entity, a word, a run of white space, or one other character.
_TOKEN_RE = re.compile(
    r"(?P<code>(?<!`)(?P<ticks>`+)(?!`).*?(?<!`)(?P=ticks)(?!`))"
    r"|\]\((?:[^()\s]|\([^()\s]*\))*\)"
    r"|<[A-Za-z][A-Za-z0-9+.-]*:[^\s<>]*>"
    r"|\\[!-/:-@\[-`{-~]"
    r"|&(?:#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});"
    r"|[^\W_]+"
    r"|\s+"
    r"|.",
    re.DOTALL,
)


def inline_tokens(text: str) -> list[str]:
    """Split inline Markdown into tokens that join back into `text`.

    Words, white space and punctuation are tokens, and so is each piece of notation
    that renders as one thing: a code span, a link target `](x.md)`, an autolink, a
    backslash escape, an entity.
    """
    return [match.group() for match in _TOKEN_RE.finditer(text)]


def token_key(token: str) -> str:
    """What an `inline_tokens` token shows, the same in the source and the export.

    White space is one space, an escape its character, an entity its character, a
    curly quote a straight one, and a link target loses the rewrites `normalise`
    undoes (`./x.md`, `http:///data`). Code spans compare exactly.
    """
    if token.startswith("`"):
        return token
    if token.isspace():
        return " "
    if _ESCAPE_RE.fullmatch(token):
        return token[1]
    if token.startswith("&"):
        token = html.unescape(token)
    return _normalise_prose(token).translate(_CURLY_QUOTES)


def _render_both(text: str) -> tuple[str, str]:
    """`text` rendered inline and as a block, where a line-start `#` or `-` counts."""
    return _MARKDOWN.renderInline(text), _MARKDOWN.render(text)


def _outside_code(text: str, transform: Callable[[str], str]) -> str:
    """Apply `transform` to the text between code spans."""
    pieces = []
    position = 0
    for code in _CODE_SPAN_RE.finditer(text):
        pieces.append(transform(text[position : code.start()]))
        pieces.append(code.group())
        position = code.end()
    pieces.append(transform(text[position:]))
    return "".join(pieces)


def parse_blocks(text: str, *, dialect: Dialect) -> tuple[Block, ...]:
    """Parse a source page or a Doc export into leaf blocks, in Doc order.

    An export heading with no text (`##` alone on its line) is dropped, so an
    emptied heading reads as a deleted one.

    Raises:
        BlockError: The page holds a construct the block model cannot represent: a
            titled callout, a comment with text after it on its line, raw HTML other
            than a comment, a table row without a leading `|`, or, in a source page,
            a heading with no text.
    """
    if dialect is Dialect.SOURCE:
        return _parse_source(text).blocks
    walk = _Walk()
    _walk_into(walk, _View.whole(text), dialect=dialect)
    return tuple(_export_leads(walk.blocks))


def align_baseline(*, page: str, source: str, baseline: str) -> tuple[BlockPair, ...]:
    """Pair every block of `source` with the block at its position in `baseline`.

    `baseline` is the Doc's export right after `to_doc_markdown(source)` was uploaded.
    A pair matches when the blocks share a family and a `rendered_text`.

    Raises:
        BaselineMismatchError: The two pages have different block counts, or a pair
            differs in family or text. It names the first such position.
    """
    source_blocks = parse_blocks(source, dialect=Dialect.SOURCE)
    baseline_blocks = parse_blocks(baseline, dialect=Dialect.EXPORT)
    pairs = []
    for index in range(max(len(source_blocks), len(baseline_blocks))):
        ours = source_blocks[index] if index < len(source_blocks) else None
        theirs = baseline_blocks[index] if index < len(baseline_blocks) else None
        if ours is None or theirs is None or not _matches(ours, theirs):
            raise BaselineMismatchError(
                page=page, index=index, source=ours, baseline=theirs
            )
        pairs.append(BlockPair(source=ours, baseline=theirs))
    return tuple(pairs)


def list_item_lines(source: str) -> tuple[tuple[int, int], ...]:
    """The `[start, end)` line span of every list item on a source page, as parsed."""
    return _parse_source(source).items


def callout_lines(source: str) -> tuple[tuple[int, int], ...]:
    """The `[start, end)` line span of every callout on a source page, marker included."""
    return tuple(
        (callout.marker, callout.end) for callout in _parse_source(source).callouts
    )


def to_doc_markdown(source: str) -> str:
    """Rewrite a source page into the Markdown docsync uploads as its Doc.

    Lines the Doc form leaves alone pass through byte for byte.
    """
    parsed = _parse_source(source)
    lines = Lines(source)
    edits: list[Edit] = []

    if parsed.front_matter_end:
        description = next(
            (block for block in parsed.blocks if block.kind is Kind.DESCRIPTION), None
        )
        lead = (
            f"{_DESCRIPTION_LEAD}{_doc_text(description.text)}\n\n"
            if description
            else ""
        )
        edits.append(Edit(0, parsed.front_matter_end, lead))

    for callout in parsed.callouts:
        edits.extend(_callout_edits(callout, lines))
    for line_no, label in parsed.directives:
        match = _TAB_RE.match(lines.lines[line_no]) or _TABS_FENCE_RE.match(
            lines.lines[line_no]
        )
        assert match is not None
        start = lines.offset(line_no, len(match.group("indent")))
        replacement = f"**Tab: {label}**" if label is not None else ""
        edits.append(Edit(start, lines.line_end(line_no), replacement))

    for host, notes in parsed.hosted_notes:
        edits.extend(_hosted_note_edits(host, notes, parsed=parsed, lines=lines))

    hosted = {note for _, notes in parsed.hosted_notes for note in notes}
    for block in parsed.blocks:
        if block.kind is Kind.AUTHOR_NOTE and block not in hosted:
            edits.extend(_note_edits(block, parsed=parsed, lines=lines))
        elif block.family == "prose" or block.kind in {Kind.HEADING, Kind.TABLE_CELL}:
            edits.extend(_link_edits(source, block.span))

    for start, label in parsed.callout_leads:
        edits.append(Edit(start, start, label))

    return apply_text_edits(source, edits)


# Parsing


@dataclass(frozen=True)
class Lines:
    """A text split into lines, with each line's starting offset."""

    text: str
    lines: list[str] = field(init=False)
    starts: list[int] = field(init=False)

    def __post_init__(self) -> None:
        lines = self.text.split("\n")
        starts = [0]
        for line in lines[:-1]:
            starts.append(starts[-1] + len(line) + 1)
        object.__setattr__(self, "lines", lines)
        object.__setattr__(self, "starts", starts)

    def offset(self, line_no: int, column: int) -> int:
        return self.starts[line_no] + column

    def line_end(self, line_no: int) -> int:
        return self.starts[line_no] + len(self.lines[line_no])


@dataclass(frozen=True)
class _View:
    """Markdown handed to markdown-it, and the page it was cut from.

    `local_to_page[k]` is the page line that line `k` of `markdown` came from. A
    callout body is parsed as its own view, dedented, with `callout` set.
    """

    page: Lines
    markdown: str
    local_to_page: tuple[int, ...]
    callout: bool = False

    @classmethod
    def whole(cls, text: str) -> _View:
        page = Lines(text)
        return cls(page, text, tuple(range(len(page.lines))))


@dataclass(frozen=True)
class _Callout:
    """A `!!! type` callout: marker line, first body line, end (exclusive)."""

    label: str
    marker: int
    body_start: int
    end: int
    indented: bool


@dataclass(frozen=True)
class _SourceParse:
    blocks: tuple[Block, ...]
    front_matter_end: int
    callouts: tuple[_Callout, ...]
    directives: tuple[tuple[int, str | None], ...]
    """Every tabs directive line, with its tab label or None for `:::tabs`/`:::`."""
    hosted_notes: tuple[tuple[Block, tuple[Block, ...]], ...]
    """Comments that end a line of text, by the block whose line they end."""
    callout_leads: tuple[tuple[int, str], ...]
    """Where each callout's `**Note:** ` lead goes in the Doc form, and the lead."""
    items: tuple[tuple[int, int], ...]
    """The page line span of every list item, callout bodies included."""


@dataclass
class _Walk:
    """What one markdown-it pass collects, in Doc order.

    `entries` pairs each block with the page line it sorts by when walks merge. A
    comment in a table cell sorts by the table's last line, since its Doc paragraph
    follows the table.
    """

    entries: list[tuple[int, Block]] = field(default_factory=list)
    hosted_notes: list[tuple[Block, tuple[Block, ...]]] = field(default_factory=list)
    items: list[tuple[int, int]] = field(default_factory=list)

    @property
    def blocks(self) -> list[Block]:
        return [block for _, block in self.entries]

    def add(self, block: Block, *, anchor: int | None = None) -> None:
        self.entries.append((block.lines[0] if anchor is None else anchor, block))


def _parse_source(text: str) -> _SourceParse:
    page = Lines(text)
    masked = list(page.lines)

    front_matter_end = 0
    walks: list[_Walk] = []
    if match := FRONTMATTER_RE.match(text):
        front_matter_end = match.end()
        last = text.count("\n", 0, front_matter_end)
        for line_no in range(last):
            masked[line_no] = ""
        if description := _description_block(page, match.group("body")):
            walks.append(_Walk())
            walks[-1].add(description)

    fence_lines = _fence_lines("\n".join(masked))
    directives: list[tuple[int, str | None]] = []
    tab_labels = _Walk()
    for line_no, line in enumerate(masked):
        if line_no in fence_lines:
            continue
        if tab := _TAB_RE.match(line):
            directives.append((line_no, tab.group("label")))
            column = len(tab.group("indent"))
            tab_labels.add(
                Block(
                    kind=Kind.TAB_LABEL,
                    text=tab.group("label"),
                    span=(page.offset(line_no, column), page.line_end(line_no)),
                    lines=(line_no, line_no + 1),
                    prefix=line[:column],
                    continuation=line[:column],
                    depth=0,
                )
            )
            masked[line_no] = ""
        elif _TABS_FENCE_RE.match(line):
            directives.append((line_no, None))
            masked[line_no] = ""
    walks.append(tab_labels)

    callouts = _find_callouts(masked, fence_lines)
    callout_leads: list[tuple[int, str]] = []
    for callout in callouts:
        body = [
            line[4:] if callout.indented and line.startswith("    ") else line
            for line in masked[callout.body_start : callout.end]
        ]
        view = _View(
            page,
            "\n".join(body),
            tuple(range(callout.body_start, callout.end)),
            callout=True,
        )
        walk = _Walk()
        walk.add(
            Block(
                kind=Kind.CALLOUT,
                text=callout.label,
                span=(page.starts[callout.marker], page.line_end(callout.marker)),
                lines=(callout.marker, callout.marker + 1),
                prefix="",
                continuation="",
                depth=0,
            )
        )
        _walk_into(walk, view, dialect=Dialect.SOURCE)
        first = walk.blocks[1] if len(walk.entries) > 1 else None
        if (
            first
            and first.kind is Kind.CALLOUT_PARAGRAPH
            and (first.lines[0] == callout.body_start)
        ):
            callout_leads.append((first.span[0], f"**{callout.label}:** "))
        else:
            start = page.starts[callout.body_start]
            callout_leads.append((start, f"> **{callout.label}:**\n>\n"))
        walks.append(walk)
        for line_no in range(callout.marker, callout.end):
            masked[line_no] = ""

    main = _Walk()
    _walk_into(
        main,
        _View(page, "\n".join(masked), tuple(range(len(masked)))),
        dialect=Dialect.SOURCE,
    )
    walks.append(main)

    merged = heapq.merge(*(walk.entries for walk in walks), key=lambda entry: entry[0])
    blocks = [block for _, block in merged]
    # A tab label sits in the container of the content it labels.
    for index, block in enumerate(blocks[:-1]):
        if block.kind is Kind.TAB_LABEL:
            blocks[index] = replace(block, depth=blocks[index + 1].depth)
    return _SourceParse(
        blocks=tuple(blocks),
        front_matter_end=front_matter_end,
        callouts=tuple(callouts),
        directives=tuple(directives),
        hosted_notes=tuple(item for walk in walks for item in walk.hosted_notes),
        callout_leads=tuple(callout_leads),
        items=tuple(sorted(item for walk in walks for item in walk.items)),
    )


def _description_block(page: Lines, body: str) -> Block | None:
    data = yaml.safe_load(body)
    if not isinstance(data, dict) or "description" not in data:
        return None
    value = data["description"]
    if not isinstance(value, str):
        raise BlockError("front matter description is not a string")
    for line_no in range(1, body.count("\n") + 2):
        line = page.lines[line_no]
        if not (match := _DESCRIPTION_LINE_RE.match(line)):
            continue
        start = page.offset(line_no, match.start("value"))
        end_line = line_no
        if match.group("value")[:1] in {">", "|"}:
            while end_line + 1 <= body.count("\n") + 1 and (
                page.lines[end_line + 1][:1] in {" ", "\t"}
                or not page.lines[end_line + 1].strip()
            ):
                end_line += 1
            while not page.lines[end_line].strip():
                end_line -= 1
            end = page.offset(end_line, len(page.lines[end_line].rstrip()))
        else:
            end = page.offset(line_no, match.end("value"))
        return Block(
            kind=Kind.DESCRIPTION,
            text=value,
            span=(start, end),
            lines=(line_no, end_line + 1),
            prefix=line[: match.start("value")],
            continuation="",
            depth=0,
        )
    raise BlockError("front matter description is not a top-level `description:` key")


def _fence_lines(text: str) -> frozenset[int]:
    """Every line inside a fenced code block, fence lines included."""
    lines: set[int] = set()
    for token in _MARKDOWN.parse(text):
        if token.type == "fence" and token.map:
            lines.update(range(*token.map))
    return frozenset(lines)


def _find_callouts(lines: list[str], fence_lines: frozenset[int]) -> list[_Callout]:
    callouts = []
    for line_no, line in enumerate(lines):
        if line_no in fence_lines or not (match := _ADMONITION_MARKER_RE.match(line)):
            continue
        kind = match.group("type").lower()
        if kind not in _ADMONITION_TYPES:
            continue
        if match.group("title") is not None:
            raise BlockError(f"line {line_no + 1}: a titled callout has no Doc form")
        body, end = _extract_admonition_body(lines, line_no)
        body_start = end - len(body)
        indented = any(
            line.startswith("    ") for line in lines[body_start:end] if line.strip()
        )
        callouts.append(
            _Callout(kind.capitalize(), line_no, body_start, end, indented=indented)
        )
    return callouts


def _walk_into(walk: _Walk, view: _View, *, dialect: Dialect) -> None:
    tokens = _MARKDOWN.parse(view.markdown)
    markdown_lines = view.markdown.split("\n")
    containers: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        depth = len(containers) + view.callout
        match token.type:
            case "list_item_open" | "blockquote_open":
                containers.append(token.type)
                if token.type == "list_item_open" and token.map:
                    # An item's map runs over the blank lines after it, and a
                    # callout's lines are blank in the view that holds the list.
                    first, last = token.map[0], token.map[1] - 1
                    while last > first and not markdown_lines[last].strip():
                        last -= 1
                    walk.items.append(
                        (view.local_to_page[first], view.local_to_page[last] + 1)
                    )
            case "list_item_close" | "blockquote_close":
                containers.pop()
            case "paragraph_open":
                kind = _paragraph_kind(containers, callout=view.callout)
                _add_inline(
                    walk,
                    view,
                    token,
                    tokens[index + 1],
                    kind=kind,
                    depth=depth,
                    dialect=dialect,
                )
            case "heading_open":
                _add_inline(
                    walk,
                    view,
                    token,
                    tokens[index + 1],
                    kind=Kind.HEADING,
                    depth=depth,
                    dialect=dialect,
                    level=int(token.tag[1:]),
                )
            case "hr":
                walk.add(_rule(view, token, depth))
            case "fence" | "code_block":
                walk.add(_code_block(view, token, depth))
            case "html_block":
                if dialect is Dialect.EXPORT:
                    raise BlockError(_where(view, token, "raw HTML in an export"))
                for block in _comment_blocks(view, token, depth):
                    walk.add(block)
            case "table_open":
                close = next(
                    i
                    for i in range(index, len(tokens))
                    if tokens[i].type == "table_close"
                )
                _add_table(walk, view, token, depth, dialect=dialect)
                index = close
        index += 1


def _paragraph_kind(containers: list[str], *, callout: bool) -> Kind:
    if containers and containers[-1] == "blockquote_open":
        return Kind.BLOCKQUOTE
    if containers:
        return Kind.LIST_ITEM
    return Kind.CALLOUT_PARAGRAPH if callout else Kind.PARAGRAPH


@dataclass(frozen=True)
class _Piece:
    """One line of a paragraph's inline text."""

    line_no: int
    start: int
    end: int
    text: str
    hard_break: bool


def _add_inline(
    walk: _Walk,
    view: _View,
    opener: Token,
    inline: Token,
    *,
    kind: Kind,
    depth: int,
    dialect: Dialect,
    level: int = 0,
) -> None:
    assert opener.map is not None
    page = view.page
    pieces: list[_Piece] = []
    for local, content in enumerate(inline.content.split("\n"), start=opener.map[0]):
        line_no = view.local_to_page[local]
        line = page.lines[line_no]
        text = content.strip()
        trimmed = line.rstrip()
        if kind is Kind.HEADING:
            trimmed = _CLOSING_HASHES_RE.sub("", trimmed)
        if not trimmed.endswith(text):
            raise BlockError(_where(view, opener, "inline text not found on its line"))
        start = len(trimmed) - len(text)
        pieces.append(
            _Piece(
                line_no,
                start,
                len(trimmed),
                text,
                len(line) - len(line.rstrip(" ")) >= 2,
            )
        )

    group: list[_Piece] = []
    after_break = False
    for position, piece in enumerate(pieces):
        group.append(piece)
        if piece.hard_break and position < len(pieces) - 1 and kind is not Kind.HEADING:
            _add_leaf(
                walk,
                view,
                group,
                kind=kind,
                depth=depth,
                dialect=dialect,
                after_break=after_break,
            )
            group = []
            after_break = True
    if group:
        _add_leaf(
            walk,
            view,
            group,
            kind=kind,
            depth=depth,
            dialect=dialect,
            level=level,
            after_break=after_break,
        )


def _add_leaf(
    walk: _Walk,
    view: _View,
    pieces: list[_Piece],
    *,
    kind: Kind,
    depth: int,
    dialect: Dialect,
    level: int = 0,
    after_break: bool = False,
) -> None:
    page = view.page
    first, last = pieces[0], pieces[-1]
    notes: tuple[Block, ...] = ()
    end_column = last.end
    texts = [piece.text for piece in pieces]
    if dialect is Dialect.SOURCE:
        for piece in pieces[:-1]:
            if _comments(piece.text):
                raise BlockError(
                    f"line {piece.line_no + 1}: a comment has text after it"
                )
        host, comments = _split_trailing_comments(last.text, line_no=last.line_no)
        if comments:
            if not host:
                raise BlockError(f"line {last.line_no + 1}: a comment has no host text")
            texts[-1] = host
            end_column = last.start + len(host)
            continuation = _continuation(page.lines[first.line_no][: first.start])
            notes = tuple(
                _note_block(
                    page,
                    last.line_no,
                    last.start + start,
                    last.start + end,
                    continuation=continuation,
                    depth=depth,
                )
                for start, end in comments
            )

    prefix = page.lines[first.line_no][: first.start]
    ends = [piece.end for piece in pieces[:-1]] + [end_column]
    line_spans = tuple(
        (page.offset(piece.line_no, piece.start), page.offset(piece.line_no, end))
        for piece, end, text in zip(pieces, ends, texts, strict=True)
        if text
    )
    if not line_spans:
        if dialect is Dialect.EXPORT and kind is Kind.HEADING:
            # A heading the editor emptied reads as a deleted heading.
            return
        raise BlockError(f"line {first.line_no + 1}: an empty {kind.value}")
    block = Block(
        kind=kind,
        text=" ".join(text for text in texts if text),
        span=(line_spans[0][0], line_spans[-1][1]),
        lines=(first.line_no, last.line_no + 1),
        prefix=prefix,
        continuation="" if kind is Kind.HEADING else _continuation(prefix),
        depth=depth,
        level=level,
        line_spans=line_spans,
        after_break=after_break,
    )
    walk.add(block)
    for note in notes:
        walk.add(note, anchor=block.lines[0])
    if notes:
        walk.hosted_notes.append((block, notes))


def _split_trailing_comments(
    text: str, *, line_no: int
) -> tuple[str, list[tuple[int, int]]]:
    """Split `text` into its text and the comments that end it.

    Raises:
        BlockError: Text follows a comment.
    """
    comments = _comments(text)
    if not comments:
        return text, []
    tail = text[comments[0][0] :]
    if _COMMENT_RE.sub("", tail).strip():
        raise BlockError(f"line {line_no + 1}: a comment has text after it")
    return text[: comments[0][0]].rstrip(), comments


def _comments(text: str) -> list[tuple[int, int]]:
    """Spans of the HTML comments in `text` outside code spans.

    An escaped opener (`\\<!--`, as a splice writes a `<!--` typed in the Doc) is
    text, since Markdown renders it as typed.
    """
    code = [match.span() for match in _CODE_SPAN_RE.finditer(text)]
    found = []
    for match in _COMMENT_RE.finditer(text):
        before = text[: match.start()]
        escapes = len(before) - len(before.rstrip("\\"))
        if escapes % 2 == 0 and not any(
            start <= match.start() < end for start, end in code
        ):
            found.append(match.span())
    return found


def _note_block(
    page: Lines,
    line_no: int,
    start: int,
    end: int,
    *,
    continuation: str,
    depth: int,
) -> Block:
    raw = page.lines[line_no][start:end]
    return Block(
        kind=Kind.AUTHOR_NOTE,
        text=_comment_text(raw),
        span=(page.offset(line_no, start), page.offset(line_no, end)),
        lines=(line_no, line_no + 1),
        prefix=page.lines[line_no][:start],
        continuation=continuation,
        depth=depth,
    )


def _comment_text(raw: str) -> str:
    inner = raw.removeprefix("<!--").removesuffix("-->")
    return " ".join(inner.split())


def _comment_blocks(view: _View, token: Token, depth: int) -> Iterator[Block]:
    """The author notes of an HTML block that holds only comments."""
    assert token.map is not None
    page = view.page
    first = view.local_to_page[token.map[0]]
    last = view.local_to_page[token.map[1] - 1]
    while not page.lines[last].strip():
        last -= 1
    start = page.starts[first]
    raw = page.text[start : page.line_end(last)]
    if _COMMENT_RE.sub("", raw).strip():
        raise BlockError(_where(view, token, "raw HTML other than a comment"))
    for match in _COMMENT_RE.finditer(raw):
        line_no = page.text.count("\n", 0, start + match.start())
        column = start + match.start() - page.starts[line_no]
        prefix = page.lines[line_no][:column]
        yield Block(
            kind=Kind.AUTHOR_NOTE,
            text=_comment_text(match.group()),
            span=(start + match.start(), start + match.end()),
            lines=(line_no, page.text.count("\n", 0, start + match.end()) + 1),
            prefix=prefix,
            continuation=_continuation(prefix),
            depth=depth,
        )


def _rule(view: _View, token: Token, depth: int) -> Block:
    assert token.map is not None
    page = view.page
    line_no = view.local_to_page[token.map[0]]
    line = page.lines[line_no]
    column = len(line) - len(line.lstrip(" \t>"))
    return Block(
        kind=Kind.RULE,
        text="",
        span=(page.offset(line_no, column), page.line_end(line_no)),
        lines=(line_no, line_no + 1),
        prefix=line[:column],
        continuation=_continuation(line[:column]),
        depth=depth,
    )


def _code_block(view: _View, token: Token, depth: int) -> Block:
    assert token.map is not None
    page = view.page
    first = view.local_to_page[token.map[0]]
    last = view.local_to_page[token.map[1] - 1]
    line = page.lines[first]
    column = line.find(token.markup) if token.type == "fence" else 0
    return Block(
        kind=Kind.FENCE,
        text=token.content,
        span=(page.offset(first, column), page.line_end(last)),
        lines=(first, last + 1),
        prefix=line[:column],
        continuation=_continuation(line[:column]),
        depth=depth,
        info=token.info.strip() if token.type == "fence" else "",
    )


def _add_table(
    walk: _Walk, view: _View, token: Token, depth: int, *, dialect: Dialect
) -> None:
    assert token.map is not None
    page = view.page
    rows = [view.local_to_page[local] for local in range(*token.map)]
    table_lines = (rows[0], rows[-1] + 1)
    notes: list[Block] = []
    for row, line_no in enumerate(rows):
        if row == 1:
            continue
        line = page.lines[line_no]
        lead = line.find("|")
        if lead < 0 or line[:lead].strip(" \t>"):
            raise BlockError(f"line {line_no + 1}: a table row has no leading `|`")
        continuation = _continuation(line[:lead])
        for column, (cell_start, cell_end) in enumerate(_cells(line, lead)):
            start, text = cell_start, line[cell_start:cell_end]
            if dialect is Dialect.SOURCE:
                text, comments = _split_trailing_comments(text, line_no=line_no)
                notes.extend(
                    _note_block(
                        page,
                        line_no,
                        start + comment_start,
                        start + comment_end,
                        continuation=continuation,
                        depth=depth,
                    )
                    for comment_start, comment_end in comments
                )
            bold = _BOLD_CELL_RE.match(text) if row == 0 else None
            if bold:
                # Google drops the bold of a header cell, whose style is bold anyway,
                # so the cell's text is what sits inside the `**`.
                start += 2
                text = bold.group("inner")
            walk.add(
                Block(
                    kind=Kind.TABLE_CELL,
                    text=text,
                    span=(
                        page.offset(line_no, start),
                        page.offset(line_no, start + len(text)),
                    ),
                    lines=(line_no, line_no + 1),
                    prefix=line[:start],
                    continuation=continuation,
                    depth=depth,
                    cell=Cell(
                        table_lines,
                        row=0 if row == 0 else row - 1,
                        column=column,
                        bold=bold is not None,
                    ),
                )
            )
    if notes:
        host = walk.entries[-1][1]
        for note in notes:
            walk.add(note, anchor=rows[-1])
        walk.hosted_notes.append((host, tuple(notes)))


def _cells(line: str, lead: int) -> Iterator[tuple[int, int]]:
    """The stripped `[start, end)` of each cell in a table row starting at `lead`."""
    pipes = [lead]
    position = lead + 1
    while position < len(line):
        if line[position] == "\\":
            position += 2
            continue
        if line[position] == "|":
            pipes.append(position)
        position += 1
    if line[pipes[-1] + 1 :].strip():
        pipes.append(len(line))
    for left, right in itertools.pairwise(pipes):
        raw = line[left + 1 : right]
        start = left + 1 + (len(raw) - len(raw.lstrip()))
        yield start, max(start, left + 1 + len(raw.rstrip()))


def _continuation(prefix: str) -> str:
    """The prefix a new paragraph in the same container as `prefix`'s line needs."""
    return _LIST_MARKER_RE.sub(lambda match: " " * len(match.group()), prefix)


def _export_leads(blocks: Iterable[Block]) -> Iterator[Block]:
    """Read the Doc-form leads back into the blocks they stand for.

    The first paragraph that opens `**Description:**` is the description, wherever
    it stands. A later one is page text. A bare `**Description:**` or
    `**Author note:**` reads as a description or note with no text.
    """
    described = False
    for block in blocks:
        if block.family != "prose":
            yield block
            continue
        if not described and (lead := _lead(block.text, _DESCRIPTION_LEAD)):
            described = True
            yield _strip_lead(block, lead, Kind.DESCRIPTION)
        elif lead := _lead(block.text, _AUTHOR_NOTE_LEAD):
            yield _strip_lead(block, lead, Kind.AUTHOR_NOTE)
        elif tab := _TAB_LABEL_RE.match(block.text):
            yield replace(block, kind=Kind.TAB_LABEL, text=tab.group("label"))
        elif block.kind is Kind.BLOCKQUOTE and (
            lead := _CALLOUT_LEAD_RE.match(block.text)
        ):
            start = block.span[0]
            yield replace(
                block,
                kind=Kind.CALLOUT,
                text=lead.group("label"),
                span=(start, start + len(lead.group().rstrip())),
                line_spans=(),
            )
            if block.text[lead.end() :]:
                yield _strip_lead(block, lead.end(), Kind.CALLOUT_PARAGRAPH)
        else:
            yield block


def lead_label(text: str, *, start: int) -> str | None:
    """The label of the first Doc-form lead in `text` from offset `start`, if any.

    The label is what the lead names: `Author note`, `Description`, `Tab`, or a
    callout's `Note`, `Tip` or `Warning`.
    """
    found = _LEAD_RE.search(text, start)
    return None if found is None else found.group("label") or found.group("tab")


def _lead(text: str, lead: str) -> int:
    """The length of `lead` at the start of `text`, or 0 when it is not there.

    A lead alone (`**Author note:**`, its space stripped with the line's) is the
    lead of an empty block: the editor cleared the note's text.
    """
    if text.startswith(lead):
        return len(lead)
    return len(text) if text == lead.rstrip() else 0


def _strip_lead(block: Block, length: int, kind: Kind) -> Block:
    (first_start, first_end), *rest = block.line_spans
    return replace(
        block,
        kind=kind,
        text=block.text[length:],
        span=(block.span[0] + length, block.span[1]),
        prefix=block.prefix + block.text[:length],
        line_spans=((first_start + length, first_end), *rest),
    )


# Alignment


def _matches(source: Block, baseline: Block) -> bool:
    return source.family == baseline.family and rendered_text(
        source, dialect=Dialect.SOURCE
    ) == rendered_text(baseline, dialect=Dialect.EXPORT)


def _describe(block: Block | None) -> str:
    if block is None:
        return "<no block>"
    text = block.text if block.kind is Kind.FENCE else normalise(block.text)
    return f"{block.kind.value} {text!r} (line {block.lines[0] + 1})"


def _where(view: _View, token: Token, problem: str) -> str:
    line = view.local_to_page[token.map[0]] + 1 if token.map else "?"
    return f"line {line}: {problem}"


# The push transform


@dataclass(frozen=True)
class Edit:
    """Replace `text[start:end]` with `replacement`."""

    start: int
    end: int
    replacement: str


def apply_text_edits(text: str, edits: list[Edit]) -> str:
    """Apply non-overlapping `edits`; insertions at one offset keep their list order."""
    ordered = [
        edit
        for _, edit in sorted(
            enumerate(edits),
            key=lambda item: (item[1].start, item[1].end, item[0]),
            reverse=True,
        )
    ]
    for later, earlier in itertools.pairwise(ordered):
        if earlier.end > later.start:
            raise AssertionError(f"overlapping edits {earlier} and {later}")
    for edit in ordered:
        text = text[: edit.start] + edit.replacement + text[edit.end :]
    return text


def _callout_edits(callout: _Callout, lines: Lines) -> Iterator[Edit]:
    yield Edit(lines.starts[callout.marker], lines.starts[callout.marker + 1], "")
    for line_no in range(callout.body_start, callout.end):
        line = lines.lines[line_no]
        start = lines.starts[line_no]
        if not line.strip():
            yield Edit(start, start + len(line), ">")
        elif callout.indented and line.startswith("    "):
            yield Edit(start, start + 4, "> ")
        else:
            yield Edit(start, start, "> ")


def _hosted_note_edits(
    host: Block, notes: tuple[Block, ...], *, parsed: _SourceParse, lines: Lines
) -> Iterator[Edit]:
    """Move comments that end a line into paragraphs after the host block."""
    if host.cell is not None:
        for note in notes:
            line_no = note.lines[0]
            cell_end = note.prefix.rstrip()
            yield Edit(lines.starts[line_no] + len(cell_end), note.span[1], "")
        anchor = lines.line_end(host.cell.lines[1] - 1)
    else:
        yield Edit(host.span[1], notes[-1].span[1], "")
        anchor = lines.line_end(host.lines[1] - 1)

    continuation = _doc_continuation(notes[0], parsed)
    separator = continuation.rstrip()
    paragraphs = "".join(
        f"\n{separator}\n{continuation}{_AUTHOR_NOTE_LEAD}{_doc_text(note.text)}"
        for note in notes
    )
    yield Edit(anchor, anchor, f"{paragraphs}\n{separator}")


def _note_edits(note: Block, *, parsed: _SourceParse, lines: Lines) -> Iterator[Edit]:
    """Turn a comment on lines of its own into an author-note paragraph.

    Blank lines around it keep it its own paragraph in the Doc.
    """
    separator = _doc_continuation(note, parsed).rstrip()
    start = lines.starts[note.lines[0]]
    end = lines.line_end(note.lines[1] - 1)
    yield Edit(start, start, f"{separator}\n")
    yield Edit(*note.span, f"{_AUTHOR_NOTE_LEAD}{_doc_text(note.text)}")
    yield Edit(end, end, f"\n{separator}")


def _doc_continuation(block: Block, parsed: _SourceParse) -> str:
    """`block.continuation` in the Doc form, where a callout body is a blockquote."""
    callout = next(
        (c for c in parsed.callouts if c.body_start <= block.lines[0] < c.end), None
    )
    if callout is None:
        return block.continuation
    if callout.indented:
        return "> " + block.continuation[4:]
    return "> " + block.continuation


def _doc_text(text: str) -> str:
    """The Doc form of text the source holds outside Markdown: a comment, a YAML value.

    Bare relative links get `./`, and every `<` outside a code span is escaped, since
    Google drops what reads as an HTML tag (`replace <dfo-site> with`).
    """
    edits = list(_link_edits(text, (0, len(text))))
    code = [match.span() for match in _CODE_SPAN_RE.finditer(text)]
    edits.extend(
        Edit(position, position, "\\")
        for position, char in enumerate(text)
        if char == "<" and not any(start <= position < end for start, end in code)
    )
    return apply_text_edits(text, edits)


def _link_edits(text: str, span: tuple[int, int]) -> Iterator[Edit]:
    """Prefix `./` to each bare relative link target in `text[span]`."""
    segment = text[span[0] : span[1]]
    code = [match.span() for match in _CODE_SPAN_RE.finditer(segment)]
    for match in _LINK_RE.finditer(segment):
        if any(start <= match.start() < end for start, end in code):
            continue
        target = match.group("target")
        if target.startswith(("/", "#", "./", "../")) or _URL_SCHEME_RE.match(target):
            continue
        position = span[0] + match.start("target")
        yield Edit(position, position, "./")
