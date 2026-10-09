"""Turn the edits made in a Google Doc into changes on its source page.

`apply_edits` compares the Doc's export with the baseline (the export right after
upload) paragraph by paragraph, and within a changed region token by token, and
splices only the changed tokens into the source page. Every source byte the editor
did not touch stays: prefixes, fences, directives, table layout, escapes, link
targets. What the source cannot take from a Doc (a code edit, a new fence, a new table
row) is left out and reported. `merge_onto_current` then carries the result onto the
source as it stands now, with `git merge-file`, re-merging each conflict line by line
and then word by word.
"""

from __future__ import annotations

import bisect
import itertools
import re
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Callable, Iterable, Iterator, Sequence, Set
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
from pathlib import Path

import yaml
from markdown_it import MarkdownIt
from markdown_it.token import Token

from dfo_docs.docsync.adapter import (
    Dialect,
    Edit,
    Lines,
    align_baseline,
    apply_text_edits,
    callout_lines,
    drop_needless_escapes,
    editor_text,
    inline_tokens,
    lead_label,
    list_item_lines,
    normalise,
    parse_blocks,
    rendered_text,
    straight_quotes,
    token_key,
)
from dfo_docs.docsync.blocks import PLAIN_KINDS, PROSE_KINDS, Block, Kind

# How alike two blocks of one family must be to pair them inside a changed region.
_PAIR_RATIO = 0.5
# How alike a note's text must be to its other side's text, with a unit's text
# added, for text to have crossed the note's edge (`_rejoins`).
_CROSS_RATIO = 0.9

_MARKER_SIZE = 41
_LINE_RE = re.compile(r"[^\n]*\n|[^\n]+\Z")
_JOIN_GAP_RE = re.compile(r"\n[ \t>]*\n")
_MARKER_RUN_RE = re.compile(r"^(?:<+|=+|>+|\|+)", re.MULTILINE)
_ITEM_START_RE = re.compile(r"(?:[-*+]|\d{1,9}[.)])[ \t]+$")
_ORDERED_START_RE = re.compile(r"\d{1,9}[.)][ \t]+$")
_TOP_ITEM_RE = re.compile(r"(?:[-*+]|\d{1,9}[.)])[ \t]")
_OWN_LINE_PREFIX_RE = re.compile(r"[ \t>]*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+[ \t>]*)*")
_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")
_DELIMITER_CELL_RE = re.compile(r"^(?P<left>:?)-+(?P<right>:?)$")
_SLUG_DROP_RE = re.compile(r"[^A-Za-z0-9_\s-]")
_SLUG_SPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[^\W_]+")
_MARKDOWN = MarkdownIt("commonmark").enable("table")

# Kinds a new Doc paragraph can be placed next to, and placed as.
_PLACEABLE = PROSE_KINDS | {Kind.HEADING, Kind.AUTHOR_NOTE}


class ReportKind(StrEnum):
    """Why a report was made.

    `HEADING_ANCHOR` and `NOTE_LABEL` name an edit that was applied. Every other
    kind names an edit left out of the source.

    `HEADING_ANCHOR` marks a heading that changed or was removed, and with it the
    anchor that links to it use. `NOTE_LABEL` marks an applied region in two cases.
    An Author note and a paragraph traded places: the editor removed or added the
    label, or deleted one and typed the other; each such block is flagged. Or a note
    or the description was changed, added or deleted and page text changed in the
    same region, so text may have moved between them; the region is flagged once.

    `REFUSED` leaves a whole region of the page unchanged and quotes the Doc's text
    of it, which only the editor can rework.
    """

    CODE_EDIT = "code_edit"
    STRUCTURAL_INSERT = "structural_insert"
    STRUCTURAL_DELETE = "structural_delete"
    TABLE_SHAPE = "table_shape"
    FOLDED_DESCRIPTION = "folded_description"
    HEADING_ANCHOR = "heading_anchor"
    NOTE_LABEL = "note_label"
    NOT_APPLIED = "not_applied"
    REFUSED = "refused"


@dataclass(frozen=True)
class Report:
    """One Doc edit the reviewer should know about.

    `block` is the source block the edit touched, or for an inserted block the block
    as parsed from the Doc's export. `quote` is set for `REFUSED`: the Doc's text of
    the region left unchanged, one line per Doc paragraph, paragraphs separated by
    a blank line.
    """

    kind: ReportKind
    block: Block
    message: str
    quote: str = ""


@dataclass(frozen=True)
class Clash:
    """A block the editor and upstream both changed since the page was pushed.

    The editor's text is what the pull request applies; the upstream text is what it
    replaced.
    """

    editor_text: str
    upstream_text: str


@dataclass(frozen=True)
class EditResult:
    """The source page with the Doc's edits applied, and what was left out.

    `refused` holds the index of every source unit in a region a `REFUSED` report
    left unchanged, for `apply_edits`'s `keep`.
    """

    text: str
    reports: tuple[Report, ...]
    refused: frozenset[int] = frozenset()


@dataclass(frozen=True)
class MergeResult:
    """The editor's changes carried onto the current source, and every clash.

    Each clash is a region the editor and an upstream commit both changed; `text`
    holds the editor's side.
    """

    text: str
    clashes: tuple[Clash, ...]


def apply_edits(
    *, page: str, source: str, baseline: str, edited: str, keep: Set[int] = frozenset()
) -> EditResult:
    """Apply the edits between `baseline` and `edited` to `source`.

    `source` is the page at the commit that was pushed, `baseline` the Doc's export
    right after that push, and `edited` its export after the editing. Alignment works on units: one
    per paragraph (its leaves, chained by `Block.after_break`) or other leaf block
    (`_units`). A unit counts as changed when its edited text renders differently
    from the source text (`adapter.rendered_text`). A change of heading level, of
    container, of a code block's language, a code block restyled as text, or an added
    or removed rule is reported, never silently dropped. Each changed region (a run of
    units between unchanged ones) is applied as `_apply_region` says. When `edited`
    equals `baseline`, the result is `source` unchanged.

    `keep` holds source unit indices (an `EditResult.refused` from the same `source`
    and `baseline`) to leave as `source` has them: every changed region that holds one
    is skipped without a report. A merge whose base and editor sides both leave those
    units alone then reads no change there, so the current source's text stands.

    Raises:
        adapter.BaselineMismatchError: `baseline` does not align with `source`.
        adapter.BlockError: `edited` holds a construct the block model cannot read.
    """
    pairs = align_baseline(page=page, source=source, baseline=baseline)
    blocks = tuple(pair.source for pair in pairs)
    baseline_blocks = [pair.baseline for pair in pairs]
    edited_blocks = parse_blocks(edited, dialect=Dialect.EXPORT)
    units = _units(blocks)
    baseline_groups = [tuple(baseline_blocks[i] for i in unit) for unit in units]
    breaks = _source_breaks(baseline_blocks, units, edited_blocks)
    edited_groups = [
        tuple(edited_blocks[j] for j in unit)
        for unit in _units(edited_blocks, breaks=breaks)
    ]
    steps, runs, ambiguous = _match(baseline_groups, edited_groups)
    match = _Match(
        units=units,
        sources=[tuple(blocks[i] for i in unit) for unit in units],
        baseline=baseline_groups,
        edited=edited_groups,
        export=Lines(edited),
        steps=steps,
        runs=runs,
        ambiguous=ambiguous,
    )
    plan = _Plan(source, blocks)
    deleted: list[_Unit] = []
    refused: set[int] = set()
    for changed, positions in match.runs:
        olds, _ = _sides([match.steps[position] for position in positions])
        if changed:
            if not keep.isdisjoint(olds):
                continue
            reported = len(plan.reports)
            deleted.extend(_apply_region(plan, match, positions))
            if any(r.kind is ReportKind.REFUSED for r in plan.reports[reported:]):
                refused.update(olds)
            continue
        for position in positions:
            index, edited_index = match.steps[position]
            assert index is not None and edited_index is not None
            if index not in keep:
                plan.change(
                    units[index], match.baseline[index], match.edited[edited_index]
                )
    plan.delete(deleted)
    return EditResult(
        text=plan.render(), reports=tuple(plan.reports), refused=frozenset(refused)
    )


def merge_onto_current(*, pushed: str, edited: str, current: str) -> MergeResult:
    """Merge the edits from `pushed` to `edited` onto `current`, the latest source.

    Runs `git merge-file --diff3 current pushed edited`, then merges each conflict
    again line by line, since git reports changes to adjacent lines as one conflict,
    and each line both sides changed word by word. Only words both sides changed
    clash. There the editor's words win and the lines are returned as a `Clash`.
    The texts pass to git as bytes, so line endings stay as they are. The result
    ends in a newline as `current` does, unless the editor added or removed the
    final newline. Git's conflict markers are longer than any run of `<`, `=`, `>`
    or `|` that starts a line of the three texts.

    Raises:
        RuntimeError: `git merge-file` failed.
    """
    texts = {"current": current, "pushed": pushed, "editor": edited}
    size = max(_MARKER_SIZE, 1 + max(map(_longest_marker_run, texts.values())))
    with tempfile.TemporaryDirectory() as directory:
        paths = []
        for name, text in texts.items():
            path = Path(directory) / name
            path.write_bytes(text.encode())
            paths.append(str(path))
        completed = subprocess.run(
            [
                "git",
                "merge-file",
                "-p",
                "--diff3",
                f"--marker-size={size}",
                "-L",
                "upstream",
                "-L",
                "pushed",
                "-L",
                "editor",
                *paths,
            ],
            capture_output=True,
            check=False,
        )
    if not 0 <= completed.returncode <= 127:
        stderr = completed.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"git merge-file failed: {stderr}")
    result = _resolve_conflicts(completed.stdout.decode(), marker_size=size)
    final = edited if edited.endswith("\n") != pushed.endswith("\n") else current
    text = result.text
    if not final.endswith("\n"):
        text = text.removesuffix("\r\n" if text.endswith("\r\n") else "\n")
    elif text and not text.endswith("\n"):
        text += "\n"
    return MergeResult(text=text, clashes=result.clashes)


def _longest_marker_run(text: str) -> int:
    """The longest run of `<`, `=`, `>` or `|` that starts a line of `text`."""
    runs = _MARKER_RUN_RE.findall(text)
    return max(map(len, runs), default=0)


# Matching the baseline with the edited export


# The indexes of the blocks of one unit, and those blocks.
type _Unit = tuple[int, ...]
type _Group = tuple[Block, ...]
# A baseline unit and the edited unit matched with it; None on the missing side.
type _Step = tuple[int | None, int | None]


def _units(blocks: Sequence[Block], *, breaks: Set[int] | None = None) -> list[_Unit]:
    """The units alignment matches: each paragraph, and each other leaf block.

    The prose leaves of one paragraph, chained by `Block.after_break`, form one unit.
    With `breaks`, only a leaf whose index it holds continues the leaf before it;
    every other leaf starts a unit. An Author note or description with no text (a
    bare lead in the Doc) is in no unit, so an emptied note reads as a deleted one
    and an added empty one adds nothing.
    """
    units: list[_Unit] = []
    for index, block in enumerate(blocks):
        if block.kind in {Kind.AUTHOR_NOTE, Kind.DESCRIPTION} and not block.text:
            continue
        if (
            units
            and block.after_break
            and (breaks is None or index in breaks)
            and block.family == "prose"
            and units[-1][-1] == index - 1
            and blocks[index - 1].family == "prose"
        ):
            units[-1] = (*units[-1], index)
        else:
            units.append((index,))
    return units


def _source_breaks(
    baseline: Sequence[Block], units: Sequence[_Unit], edited: Sequence[Block]
) -> set[int]:
    """The edited leaves that continue the leaf before them across a source hard break.

    A Doc exports both a source hard break and a paragraph made with Enter as a line
    that ends in two spaces. The break is the source's only where the baseline has
    that break between the same two leaves: in a token diff of the page's prose
    (`_break_tokens`), it lies inside a run of equal tokens that holds a token
    beside it and a hard break of the baseline. Every other such line end starts a
    paragraph the editor made.
    """
    unit_of = {index: number for number, unit in enumerate(units) for index in unit}
    base, _ = _break_tokens(
        baseline, lambda i: i in unit_of and unit_of.get(i - 1) == unit_of[i]
    )
    theirs, leaves = _break_tokens(
        edited,
        lambda j: edited[j].after_break and edited[j - 1].family == "prose",
    )
    matcher = SequenceMatcher(None, base, theirs, autojunk=False)
    return {
        leaves[start + offset]
        for _, start, size in matcher.get_matching_blocks()
        if size > 1
        for offset in range(size)
        if start + offset in leaves
    }


# Tokens `_break_tokens` puts between blocks: a hard break, and any other edge.
_BREAK_TOKEN = "\x00break"
_EDGE_TOKEN = "\x00edge"


def _break_tokens(
    blocks: Sequence[Block], chained: Callable[[int], bool]
) -> tuple[list[str], dict[int, int]]:
    """The page's text as tokens, and the block each hard-break token comes before.

    Prose leaves give their `_token` keys; a leaf `chained` to the one before it
    starts with a hard-break token, any other block with an edge token. A block of
    any other family is one token of its own.
    """
    tokens: list[str] = []
    breaks: dict[int, int] = {}
    for index, block in enumerate(blocks):
        if block.family != "prose":
            tokens.extend((_EDGE_TOKEN, f"\x00{block.family}"))
            continue
        if index and chained(index):
            breaks[len(tokens)] = index
            tokens.append(_BREAK_TOKEN)
        else:
            tokens.append(_EDGE_TOKEN)
        tokens.extend(_token(token) for token in inline_tokens(normalise(block.text)))
    return tokens, breaks


def _texts(group: _Group) -> tuple[str, ...]:
    return tuple(rendered_text(block, dialect=Dialect.EXPORT) for block in group)


type _GroupKey = tuple[tuple[Kind, int, str, int | None, str], ...]


def _group_key(group: _Group) -> _GroupKey:
    """What alignment compares: each block's place and its text.

    The place is the block's kind, depth, list marker (numbered, bullet, or none for
    a paragraph that does not start an item) and table column. Blocks of one text in
    different places, such as a paragraph and a list item or two cells of one row,
    differ, so an unchanged one is never matched to the other.
    """
    return tuple(
        (
            block.kind,
            block.depth,
            _marker(block),
            None if block.cell is None else block.cell.column,
            rendered_text(block, dialect=Dialect.EXPORT),
        )
        for block in group
    )


def _marker(block: Block) -> str:
    if not _starts_item(block):
        return ""
    return "numbered" if _is_numbered(block) else "bullet"


@dataclass(frozen=True)
class _Anchor:
    """A source block and the edited block paired with it, beside an inserted block.

    `entered` is set when the inserted unit, and every unit between it and
    `edited`, is a paragraph made with Enter at the end of the one before
    (`_entered`).
    """

    source: Block
    edited: Block
    entered: bool = False


@dataclass(frozen=True)
class _Match:
    """A page's units, their source, baseline and edited groups, and how they match.

    `export` is the edited export. `steps` pairs baseline units with edited units in
    order, `runs` splits the step positions into unchanged runs and changed regions,
    and `ambiguous` holds the first position of each region where identical units
    leave the pairing a guess (`_match`).
    """

    units: Sequence[_Unit]
    sources: Sequence[_Group]
    baseline: Sequence[_Group]
    edited: Sequence[_Group]
    export: Lines
    steps: Sequence[_Step]
    runs: Sequence[tuple[bool, range]]
    ambiguous: Set[int]

    def anchor(self, position: int, *, step: int) -> _Anchor | None:
        """The nearest paired unit before (`step` -1) or after (1) the inserted
        unit at `position`.

        Its last blocks stand before an inserted unit, its first blocks after one.
        The description sits in the front matter, so it is skipped.
        """
        inserted = self.steps[position][1]
        assert inserted is not None
        position += step
        while 0 <= position < len(self.steps):
            index, edited_index = self.steps[position]
            if (
                index is not None
                and edited_index is not None
                and self.sources[index][0].kind is not Kind.DESCRIPTION
            ):
                if step > 0:
                    return _Anchor(self.sources[index][0], self.edited[edited_index][0])
                return _Anchor(
                    self.sources[index][-1],
                    self.edited[edited_index][-1],
                    entered=all(
                        _entered(self.edited[j - 1][-1], self.edited[j][0])
                        for j in range(edited_index + 1, inserted + 1)
                    ),
                )
            position += step
        return None

    def doc_text(self, indexes: Sequence[int]) -> str:
        """The export's text from edited unit `indexes[0]` to `indexes[-1]`.

        Each Doc paragraph is one line, and a blank line separates paragraphs, so
        the text shows where the editor pressed Enter.
        """
        if not indexes:
            return ""
        first, last = self.edited[indexes[0]][0], self.edited[indexes[-1]][-1]
        paragraphs: list[list[str]] = [[]]
        for line in self.export.lines[first.lines[0] : last.lines[1]]:
            if line.strip(" >"):
                paragraphs[-1].append(line.strip())
            if not line.strip(" >") or line.endswith("  "):
                paragraphs.append([])
        return "\n\n".join(" ".join(lines) for lines in paragraphs if lines)


@dataclass
class _Segment:
    """A run of units the matcher found equal, or a changed region between them.

    `repeated` is set on a changed region that took in an equal unit beside it whose
    key it also holds (`_absorb_repeats`).
    """

    equal: bool
    olds: range
    news: range
    repeated: bool = False


def _match(
    baseline: Sequence[_Group], edited: Sequence[_Group]
) -> tuple[list[_Step], list[tuple[bool, range]], frozenset[int]]:
    """Match baseline units to edited units in order: the steps, runs and ambiguous.

    Each run is a range of step positions, unchanged (`False`) or a changed region
    (`True`) of pairs, deletes and inserts. `ambiguous` holds the first step position
    of each changed region whose repeated units (`_absorb_repeats`) do not all pair:
    which copy the editor changed is a guess there.
    """
    old_keys = [_group_key(group) for group in baseline]
    new_keys = [_group_key(group) for group in edited]
    matcher = SequenceMatcher(None, old_keys, new_keys, autojunk=False)
    segments = _absorb_repeats(
        [
            _Segment(tag == "equal", range(i1, i2), range(j1, j2))
            for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        ],
        old_keys,
        new_keys,
    )
    steps: list[_Step] = []
    runs: list[tuple[bool, range]] = []
    guessed: set[int] = set()
    for number, segment in enumerate(segments):
        start = len(steps)
        if segment.equal:
            steps.extend(zip(segment.olds, segment.news, strict=True))
        else:
            steps.extend(_pair_region(baseline, edited, segment.olds, segment.news))
        runs.append((not segment.equal, range(start, len(steps))))
        if segment.repeated and any(None in step for step in steps[start:]):
            guessed.add(number)

    # A guessed region's units may be the copies another region moved or added, so
    # every changed region that holds one of its keys is a guess too.
    keys = [
        {old_keys[i] for i in segment.olds} | {new_keys[j] for j in segment.news}
        for segment in segments
    ]
    while doubtful := {
        number
        for number, segment in enumerate(segments)
        if number not in guessed
        and not segment.equal
        and any(keys[number] & keys[other] for other in guessed)
    }:
        guessed |= doubtful
    ambiguous = frozenset(runs[number][1].start for number in guessed)
    return steps, runs, ambiguous


def _absorb_repeats(
    segments: list[_Segment],
    old_keys: Sequence[_GroupKey],
    new_keys: Sequence[_GroupKey],
) -> list[_Segment]:
    """Move into each changed region the equal units beside it whose key it holds.

    The matcher picks one of several identical units as the unchanged one, so an
    edit to the first of two identical paragraphs can read as an insert before the
    second and a delete after it. Taking such units into the region lets
    `_pair_region` pair them in order. An equal run left empty joins the regions on
    either side.
    """
    moved = True
    while moved:
        moved = False
        for number, segment in enumerate(segments):
            if not segment.equal:
                continue
            for side in (-1, 1):
                if not 0 <= number + side < len(segments):
                    continue
                region = segments[number + side]
                keys = {old_keys[i] for i in region.olds}
                keys |= {new_keys[j] for j in region.news}
                edge, rest = (-1, slice(None, -1)) if side > 0 else (0, slice(1, None))
                while segment.olds and old_keys[segment.olds[edge]] in keys:
                    i, j = segment.olds[edge], segment.news[edge]
                    segment.olds, segment.news = segment.olds[rest], segment.news[rest]
                    region.olds = _widened(region.olds, i)
                    region.news = _widened(region.news, j)
                    region.repeated = moved = True
        segments = _joined(segments)
    return segments


def _widened(span: range, index: int) -> range:
    """`span` grown to take in `index`, which lies just before or after it."""
    return range(min(span.start, index), max(span.stop, index + 1))


def _joined(segments: Iterable[_Segment]) -> list[_Segment]:
    """Drop empty equal runs and join the changed regions that then touch."""
    joined: list[_Segment] = []
    for segment in segments:
        if segment.equal and not segment.olds:
            continue
        if joined and not segment.equal and not joined[-1].equal:
            last = joined[-1]
            last.olds = range(last.olds.start, segment.olds.stop)
            last.news = range(last.news.start, segment.news.stop)
            last.repeated = last.repeated or segment.repeated
            continue
        joined.append(segment)
    return joined


def _pair_region(
    baseline: Sequence[_Group], edited: Sequence[_Group], olds: range, news: range
) -> Iterator[_Step]:
    """Pair the units of a changed region by family, then by similarity.

    A region of equal length whose families line up pairs position by position, so a
    rewritten paragraph stays a change. Otherwise the pairing keeps order and
    maximises the summed similarity of pairs at least `_PAIR_RATIO` alike; the rest
    are deletes and inserts.
    """
    if len(olds) == len(news) and all(
        baseline[i][0].family == edited[j][0].family
        for i, j in zip(olds, news, strict=True)
    ):
        yield from zip(olds, news, strict=True)
        return

    def ratio(i: int, j: int) -> float:
        if baseline[i][0].family != edited[j][0].family:
            return 0.0
        value = SequenceMatcher(
            None,
            "\n".join(_texts(baseline[i])),
            "\n".join(_texts(edited[j])),
            autojunk=False,
        ).ratio()
        return value if value >= _PAIR_RATIO else 0.0

    rows, columns = len(olds), len(news)
    score = [[0.0] * (columns + 1) for _ in range(rows + 1)]
    for r, c in itertools.product(range(rows), range(columns)):
        paired = ratio(olds[r], news[c])
        score[r + 1][c + 1] = max(
            score[r][c + 1],
            score[r + 1][c],
            score[r][c] + paired if paired else 0.0,
        )

    steps: list[_Step] = []
    r, c = rows, columns
    while r or c:
        paired = ratio(olds[r - 1], news[c - 1]) if r and c else 0.0
        if paired and score[r][c] == score[r - 1][c - 1] + paired:
            steps.append((olds[r - 1], news[c - 1]))
            r, c = r - 1, c - 1
            continue
        if r and (not c or score[r][c] == score[r - 1][c]):
            steps.append((olds[r - 1], None))
            r -= 1
        else:
            steps.append((None, news[c - 1]))
            c -= 1
    yield from reversed(steps)


# Applying a changed region

_CODE_RESTYLED = (
    "the code block became normal text in the Doc; code edits are not applied, so"
    " change the code in the source"
)
_NOTE_TO_TEXT = "an Author note became page text; check it belongs on the site"
_REPEATED = (
    "the same text appears more than once here, so which copy changed is unclear"
)
_TEXT_TO_NOTE = "a paragraph became an Author note and leaves the site"
# Kinds the Doc shows only as a lead, and the lead's label. A callout's label is its
# text.
_LEAD_KINDS = {Kind.DESCRIPTION: "Description", Kind.CALLOUT: "", Kind.TAB_LABEL: "Tab"}
# Kinds that hold text after a lead the Doc shows: a note, the description.
_LABELLED_KINDS = {Kind.AUTHOR_NOTE, Kind.DESCRIPTION}
# The offset in a Doc block's text from which a lead counts as misplaced. A
# paragraph's own lead is at 0. A note, description and callout paragraph start
# after theirs. A heading and a cell carry none.
_LEAD_START = {
    Kind.PARAGRAPH: 1,
    Kind.LIST_ITEM: 1,
    Kind.BLOCKQUOTE: 1,
    Kind.CALLOUT_PARAGRAPH: 0,
    Kind.AUTHOR_NOTE: 0,
    Kind.DESCRIPTION: 0,
    Kind.HEADING: 0,
    Kind.TABLE_CELL: 0,
}
_NOTE_ITEM_RE = re.compile(
    rf"{_ITEM_START_RE.pattern.removesuffix('$')}\*\*Author note:"
)


def _apply_region(plan: _Plan, match: _Match, positions: range) -> list[_Unit]:
    """Apply one changed region; return the source units it deletes.

    A region where identical units leave the pairing a guess (`_Match.ambiguous`),
    where text crossed the edge of a note, the description, a callout or a tab
    (`_refusals`), or with a Doc unit the source has no place for
    (`_UnplaceableError`), is left unchanged: every unit it deletes stays, and a
    `REFUSED` report quotes the Doc's text of it. Otherwise each unit applies on
    its own (`_apply_units`).
    """
    steps = [match.steps[position] for position in positions]
    news = [j for _, j in steps if j is not None]
    if positions.start in match.ambiguous:
        olds, _ = _sides(steps)
        block = match.sources[olds[0]][0] if olds else match.edited[news[0]][0]
        plan.refuse(block, _REPEATED, quote=match.doc_text(news))
        return []
    if refusal := next(_refusals(match, steps), None):
        block, reason = refusal
        plan.refuse(block, reason, quote=match.doc_text(news))
        return []
    mark = plan.mark()
    try:
        return _apply_units(plan, match, positions, steps)
    except _UnplaceableError as unplaced:
        plan.rollback(mark)
        plan.refuse(unplaced.block, unplaced.reason, quote=match.doc_text(news))
        return []


def _apply_units(
    plan: _Plan, match: _Match, positions: range, steps: Sequence[_Step]
) -> list[_Unit]:
    """Apply each unit of a changed region; return the source units it deletes.

    - A run of paragraphs of one container is spliced as one text
      (`_Plan.change_paragraphs`), so joins, splits and hard breaks land in place.
    - A code block that came back as a paragraph (`_restyled`) is kept, reported.
    - A note deleted and a paragraph added next to it, with nothing else between
      unchanged units (`_neighbours`), is a note whose label the editor removed or
      whose text they replaced: the paragraph is written where the note was
      (`_Plan.relabel`). A paragraph deleted and a note added next to it are the
      reverse. When the source cannot take that, the paragraph is placed as an
      insert.
    - Every other pair is changed, insert placed, and delete returned.

    The notes and paragraphs the region turns into each other are flagged
    (`_flag_notes`). Failing that, a region that changes a note or the description
    and page text is flagged once (`_flag_beside_text`).

    Raises:
        _UnplaceableError: the source has no place for a unit where the Doc puts it.
    """
    olds, news = _sides(steps)
    if (
        olds
        and news
        and plan.change_paragraphs(
            [match.units[i] for i in olds],
            [match.baseline[i] for i in olds],
            [match.edited[j] for j in news],
        )
    ):
        return []

    deletes = [i for i, j in steps if j is None and i is not None]
    inserts = [j for i, j in steps if i is None and j is not None]
    restyled = _restyled(match, deletes, inserts)
    for index in restyled:
        plan.report(ReportKind.CODE_EDIT, match.sources[index][0], _CODE_RESTYLED)
    deletes = [i for i in deletes if i not in restyled]
    inserts = [j for j in inserts if j not in restyled.values()]
    became = {
        j: i
        for j, i in _neighbours(steps).items()
        if {match.sources[i][0].family, match.edited[j][0].family}
        == {"prose", Kind.AUTHOR_NOTE.value}
    }

    placed: list[int] = []
    relabelled: list[int] = []
    for position, (index, edited_index) in zip(positions, steps, strict=True):
        if index is not None and edited_index is not None:
            plan.change(
                match.units[index], match.baseline[index], match.edited[edited_index]
            )
        if edited_index not in inserts:
            continue
        group = match.edited[edited_index]
        origin = became.get(edited_index)
        if origin is not None and plan.relabel(match.units[origin], group):
            deletes.remove(origin)  # rewritten in place
            relabelled.append(origin)
        elif not plan.insert(
            group,
            before=match.anchor(position, step=-1),
            after=match.anchor(position, step=1),
        ):
            continue
        placed.append(edited_index)

    if not _flag_notes(
        plan, match, steps, gone={*relabelled, *deletes}, placed=set(placed)
    ):
        _flag_beside_text(plan, match, steps)
    return [match.units[i] for i in deletes]


def _refusals(match: _Match, steps: Sequence[_Step]) -> Iterator[tuple[Block, str]]:
    """Each block, and why, that leaves a region unchanged.

    A region is left unchanged when a note, description, tab or callout lead stands
    anywhere but at the start of a Doc paragraph, in any kind of block (Backspace
    joined it onto the block before, or the editor typed it there); when a list
    item or heading gains the note label; when a lead the Doc alone shows (a
    callout's, a tab's, the description's) was removed or changed and the region
    holds Doc text; and when text crossed the edge of a note or the description
    (`_crossings`).
    """
    news = [j for _, j in steps if j is not None]
    for block in (block for j in news for block in match.edited[j]):
        start = _LEAD_START.get(block.kind)
        if start is not None and (label := lead_label(block.text, start=start)):
            yield block, f"the {label} label is not at the start of a paragraph"
        if block.kind is Kind.AUTHOR_NOTE and _NOTE_ITEM_RE.search(block.prefix):
            yield block, "a list item cannot become an Author note"
    for j, i in _neighbours(steps).items():
        old = match.sources[i][0]
        if match.edited[j][0].kind is Kind.AUTHOR_NOTE and (
            old.kind is Kind.HEADING or _starts_item(old)
        ):
            kind = "heading" if old.kind is Kind.HEADING else "list item"
            yield old, f"a {kind} cannot become an Author note"
    for index, edited_index in steps:
        old = None if index is None else match.sources[index][0]
        if old and edited_index is None and old.kind in _LEAD_KINDS and news:
            label = _LEAD_KINDS[old.kind] or old.text
            yield old, f"the {label} label was removed or changed"
    yield from _crossings(match, steps)


def _crossings(match: _Match, steps: Sequence[_Step]) -> Iterator[tuple[Block, str]]:
    """Each place where text crossed the edge of a note or the description.

    Text compares as its letters and digits (`_squashed`), and pairing plays no
    part: any other unit of the region, paired or not, may be the one text moved
    to or from. Text crossed when a note or the description changed and
    (`_rejoins`):

    - its new text plus another Doc unit's text is its old text, give or take a
      few letters: Enter split it;
    - its old text plus another baseline unit's text, in either order, is its new
      text, give or take a few letters: Backspace joined that unit onto it.

    It also crossed when a leaf of a paragraph with a source hard break, on one
    side of the region, equals, holds or is held by a note's words on the other:
    the note label moved onto or off that line.
    """
    olds, news = _sides(steps)
    for i, j in itertools.product(olds, news):
        old = match.sources[i][0]
        if old.kind not in _LABELLED_KINDS or match.edited[j][0].kind is not old.kind:
            continue
        was, now = _squashed(match.baseline[i]), _squashed(match.edited[j])
        if was == now:
            continue
        split = _rejoins(
            now, was, (now + _squashed(match.edited[k]) for k in news if k != j)
        )
        joined = _rejoins(
            was,
            now,
            (
                joined
                for text in (_squashed(match.baseline[k]) for k in olds if k != i)
                for joined in (was + text, text + was)
            ),
        )
        if split or joined:
            yield old, f"text was joined onto or split off {_labelled(old)}"

    source = [(match.sources[i][0], match.baseline[i]) for i in olds]
    edited = [(match.edited[j][0], match.edited[j]) for j in news]
    for side, other in ((source, edited), (edited, source)):
        notes = [
            _words(group) for block, group in other if block.kind is Kind.AUTHOR_NOTE
        ]
        for block, group in side:
            if len(group) > 1 and any(
                _overlaps(_words((leaf,)), note) for leaf in group for note in notes
            ):
                yield (
                    block,
                    "a paragraph with a line break and an Author note changed together",
                )


def _rejoins(text: str, target: str, joined: Iterable[str]) -> bool:
    """Whether one of `joined`, `text` with a unit's text beside it, is `target`.

    It is when the two are at least `_CROSS_RATIO` alike and more alike than
    `text` alone is, so a word the editor changed in either part still counts,
    and text the editor typed beside an edited note does not.
    """
    matcher = SequenceMatcher(None, text, target, autojunk=False)
    alone = matcher.ratio()
    for candidate in joined:
        matcher.set_seq1(candidate)
        if (
            matcher.real_quick_ratio() >= _CROSS_RATIO
            and matcher.quick_ratio() >= _CROSS_RATIO
            and (ratio := matcher.ratio()) >= _CROSS_RATIO
            and ratio > alone
        ):
            return True
    return False


def _labelled(block: Block) -> str:
    """How a report names a note or the description."""
    return "an Author note" if block.kind is Kind.AUTHOR_NOTE else "the Description"


def _words(group: _Group) -> str:
    """The text a Doc unit shows, its words separated by single spaces."""
    return " ".join(" ".join(_plain_text(block) for block in group).split())


def _squashed(group: _Group) -> str:
    """The letters and digits of the text a Doc unit shows.

    A heading's `#` marks typed into a note's paragraph drop out with the rest of
    the punctuation.
    """
    return "".join(_WORD_RE.findall(_words(group)))


def _overlaps(text: str, other: str) -> bool:
    """Whether two runs of words are equal or one holds the other, word for word."""
    if not text or not other:
        return False
    return f" {text} " in f" {other} " or f" {other} " in f" {text} "


def _gaps(steps: Sequence[_Step]) -> Iterator[range]:
    """The positions of each run of unpaired steps.

    A run lies between paired steps or the region's edges.
    """
    position = 0
    for paired, run in itertools.groupby(steps, key=lambda step: None not in step):
        size = len(list(run))
        if not paired:
            yield range(position, position + size)
        position += size


def _neighbours(steps: Sequence[_Step]) -> dict[int, int]:
    """Each added unit that stands alone next to one deleted unit, and that unit.

    They are the only two steps of a run of unpaired steps (`_gaps`).
    """
    found: dict[int, int] = {}
    for gap in _gaps(steps):
        deleted, added = _sides(steps[gap.start : gap.stop])
        if len(deleted) == len(added) == 1:
            found[added[0]] = deleted[0]
    return found


def _sides(steps: Sequence[_Step]) -> tuple[list[int], list[int]]:
    """The baseline units and the edited units of `steps`, in order."""
    olds = [index for index, _ in steps if index is not None]
    news = [edited_index for _, edited_index in steps if edited_index is not None]
    return olds, news


def _is_text(block: Block) -> bool:
    """Whether a block is page text: a paragraph, list item, quote or heading."""
    return block.family == "prose" or block.kind is Kind.HEADING


def _is_note(block: Block) -> bool:
    return block.kind is Kind.AUTHOR_NOTE


def _flag_notes(
    plan: _Plan,
    match: _Match,
    steps: Sequence[_Step],
    *,
    gone: Set[int],
    placed: Set[int],
) -> bool:
    """Flag each note or paragraph a region turned into the other; return whether
    any was.

    `gone` holds the source units deleted or rewritten, `placed` the Doc units
    placed. Within one run of unpaired steps (`_gaps`), the place a note or
    paragraph went from: when the run places page text, each note it took is
    flagged; when it places a note, each paragraph or heading it took is. A run
    that takes two notes and places one paragraph flags both, since nothing tells
    which of them the paragraph replaced.
    """
    flagged = False
    for gap in _gaps(steps):
        olds, news = _sides(steps[gap.start : gap.stop])
        took = sorted(index for index in olds if index in gone)
        put = [match.edited[j][0] for j in news if j in placed]
        for was, now, message in (
            (_is_note, _is_text, _NOTE_TO_TEXT),
            (_is_text, _is_note, _TEXT_TO_NOTE),
        ):
            if any(now(block) for block in put):
                for index in took:
                    if was(block := match.sources[index][0]):
                        plan.report(ReportKind.NOTE_LABEL, block, message)
                        flagged = True
    return flagged


def _flag_beside_text(plan: _Plan, match: _Match, steps: Sequence[_Step]) -> None:
    """Flag a region that changed a note or the description and page text too.

    Text may have moved between them in a way `_crossings` cannot see. A unit
    changed when it was added or deleted, or when its words differ from its
    pair's (`_words`). Page text is a paragraph, list item, quote, heading or table
    cell. The flag goes once, on the region's first changed note or description.
    """
    labelled: list[Block] = []
    text = False
    for index, edited_index in steps:
        if index is None:
            assert edited_index is not None
            block = match.edited[edited_index][0]
        elif edited_index is None or _words(match.baseline[index]) != _words(
            match.edited[edited_index]
        ):
            block = match.sources[index][0]
        else:
            continue
        if block.kind in _LABELLED_KINDS:
            labelled.append(block)
        text = text or _is_text(block) or block.kind is Kind.TABLE_CELL
    if labelled and text:
        plan.report(
            ReportKind.NOTE_LABEL,
            labelled[0],
            f"{_labelled(labelled[0])} and the page text beside it changed together;"
            " check no text moved between them",
        )


def _restyled(
    match: _Match, deletes: Sequence[int], inserts: Sequence[int]
) -> dict[int, int]:
    """Deleted code blocks that came back as an inserted paragraph, and that insert.

    A fence whose code became text reads as a deleted fence and an inserted
    paragraph. Within one changed region, such a fence pairs with the first unpaired
    inserted paragraph whose plain text is at least `_PAIR_RATIO` alike to its code
    or to one of its lines.
    """
    restyled: dict[int, int] = {}
    for index in deletes:
        if match.sources[index][0].kind is not Kind.FENCE:
            continue
        code = match.baseline[index][0].text
        candidates = [code, *(line for line in code.split("\n") if line.strip())]
        found = next(
            (
                j
                for j in inserts
                if j not in restyled.values()
                and match.edited[j][0].family == "prose"
                and any(
                    SequenceMatcher(
                        None,
                        " ".join(_plain_text(block) for block in match.edited[j]),
                        candidate.strip(),
                    ).ratio()
                    >= _PAIR_RATIO
                    for candidate in candidates
                )
            ),
            None,
        )
        if found is not None:
            restyled[index] = found
    return restyled


def _plain_text(block: Block) -> str:
    """The text a Doc paragraph shows, without its Markdown."""
    inline = _MARKDOWN.parseInline(normalise(block.text))[0].children or []
    return "".join(_text_content(inline))


# Building the new source


class _UnplaceableError(Exception):
    """A Doc unit the source has no place for where the Doc puts it."""

    def __init__(self, block: Block, reason: str) -> None:
        super().__init__(reason)
        self.block = block
        self.reason = reason


class _Plan:
    """The splices `apply_edits` makes to one source page, and its reports.

    `lists` holds the offset after each line a new list was opened after, and
    whether that list is numbered, so the next item of its kind added there joins
    that list.
    """

    def __init__(self, source: str, blocks: tuple[Block, ...]) -> None:
        self.source = source
        self.lines = Lines(source)
        self.blocks = blocks
        self.items = list_item_lines(source)
        self.edits: list[Edit] = []
        self.deleted_lines: set[int] = set()
        self.reports: list[Report] = []
        self.lists: list[tuple[int, bool]] = []

    def report(
        self, kind: ReportKind, block: Block, message: str, *, quote: str = ""
    ) -> None:
        self.reports.append(
            Report(kind=kind, block=block, message=message, quote=quote)
        )

    def refuse(self, block: Block, reason: str, *, quote: str) -> None:
        """Report a region left unchanged, quoting the Doc's text of it."""
        self.report(
            ReportKind.REFUSED,
            block,
            f"{reason}; this part of the page is not changed",
            quote=quote,
        )

    def mark(self) -> tuple[int, int, int]:
        """Where the splices, reports and opened lists stand, for `rollback`."""
        return len(self.edits), len(self.reports), len(self.lists)

    def rollback(self, mark: tuple[int, int, int]) -> None:
        """Drop every splice, report and opened list made since `mark`."""
        edits, reports, lists = mark
        del self.edits[edits:], self.reports[reports:], self.lists[lists:]

    def splice(self, start: int, end: int, text: str) -> None:
        self.edits.append(Edit(start, end, text))

    # Changed blocks

    def change(self, unit: _Unit, baseline: _Group, edited: _Group) -> None:
        block, base, new = self.blocks[unit[0]], baseline[0], edited[0]
        if block.kind is Kind.FENCE:
            if new.text != base.text:
                self.report(
                    ReportKind.CODE_EDIT,
                    block,
                    "code edits are not applied; change the code in the source",
                )
            elif new.info != base.info:
                self.report(
                    ReportKind.CODE_EDIT,
                    block,
                    f"the code block's language {base.info or '(none)'!r} became"
                    f" {new.info or '(none)'!r} in the Doc; change it in the source",
                )
            return
        if (base.kind, base.depth) != (new.kind, new.depth):
            self.report(
                ReportKind.NOT_APPLIED,
                block,
                f"moved from {base.kind.value} at depth {base.depth} to"
                f" {new.kind.value} at depth {new.depth}; only its text is applied",
            )
        elif base.level != new.level:
            self.report(
                ReportKind.NOT_APPLIED,
                block,
                f"heading level {base.level} became {new.level} in the Doc;"
                " only its text is applied",
            )
        elif _starts_item(base) != _starts_item(new):
            self.report(
                ReportKind.NOT_APPLIED,
                block,
                "a list marker was added or removed in the Doc; only its text is"
                " applied",
            )
        if len(unit) == len(edited) and all(
            rendered_text(other, dialect=Dialect.EXPORT)
            == rendered_text(self.blocks[index], dialect=Dialect.SOURCE)
            for index, other in zip(unit, edited, strict=True)
        ):
            return
        if block.family == "prose":
            self._splice_paragraphs([unit], [baseline], [edited])
            return
        if block.kind in {Kind.HEADING, Kind.TABLE_CELL}:
            self._change_inline(block, base, new)
            return
        text = editor_text(new.text, markdown=block.kind not in PLAIN_KINDS)
        if text == block.text:
            return
        match block.kind:
            case Kind.CALLOUT:
                self.report(
                    ReportKind.NOT_APPLIED,
                    block,
                    f"a {block.text} callout cannot become {text!r} in the Doc",
                )
            case Kind.DESCRIPTION:
                self._change_description(block, text)
            case Kind.AUTHOR_NOTE:
                self._change_note(block, text)
            case Kind.TAB_LABEL if '"' in text:
                self.report(
                    ReportKind.NOT_APPLIED, block, f"tab label {text!r} holds a quote"
                )
            case Kind.TAB_LABEL:
                self.splice(*block.span, f'::tab{{label="{text}"}}')

    def change_paragraphs(
        self,
        units: Sequence[_Unit],
        baseline: Sequence[_Group],
        edited: Sequence[_Group],
    ) -> bool:
        """Splice a changed region of paragraphs as one text, if it is one run.

        It is when every unit on both sides is prose, the source paragraphs follow
        each other in one container (`_same_container`), and the Doc's paragraphs
        sit in that container too: each has the baseline's depth and one of its
        kinds, or was made with Enter at the end of the one before (`_entered`),
        and only the first has a list marker, as in the baseline.
        """
        groups = [*baseline, *edited]
        if any(group[0].family != "prose" for group in groups):
            return False
        if not all(
            self._same_container(self.blocks[before[-1]], self.blocks[after[0]])
            for before, after in itertools.pairwise(units)
        ):
            return False
        first = baseline[0][0]
        kinds = {group[0].kind for group in baseline}
        if not all(
            (
                group[0].kind in kinds
                and all(block.depth == first.depth for block in group)
            )
            or (index and _entered(edited[index - 1][-1], group[0]))
            for index, group in enumerate(edited)
        ):
            return False
        if [_starts_item(group[0]) for group in edited] != [
            _starts_item(first),
            *[False] * (len(edited) - 1),
        ]:
            return False
        self._splice_paragraphs(units, baseline, edited)
        return True

    def _splice_paragraphs(
        self,
        units: Sequence[_Unit],
        baseline: Sequence[_Group],
        edited: Sequence[_Group],
    ) -> None:
        sources = [tuple(self.blocks[index] for index in unit) for unit in units]
        start, end = sources[0][0].span[0], sources[-1][-1].span[1]
        text = _splice_text(self.source, sources, baseline, edited)
        if text != self.source[start:end]:
            self.splice(start, end, text)

    def _same_container(self, before: Block, block: Block) -> bool:
        """Whether paragraph `block` follows paragraph `before` in its container.

        `block` starts no list item, and only a blank line of that container lies
        between them.
        """
        if _starts_item(block) or before.continuation != block.prefix:
            return False
        between = self.source[before.span[1] : block.span[0]]
        return _JOIN_GAP_RE.fullmatch(between.removesuffix(block.prefix)) is not None

    def _change_inline(self, block: Block, baseline: Block, edited: Block) -> None:
        old = self.source[slice(*block.span)]
        text = _splice_text(self.source, [(block,)], [(baseline,)], [(edited,)])
        if text == old:
            return
        if block.kind is Kind.TABLE_CELL:
            span = block.span
            if block.cell is not None and block.cell.bold and not text:
                # An emptied bold header cell loses its `**` too.
                span = (span[0] - 2, span[1] + 2)
            self._change_cell(span, block.lines[0], self.source[slice(*span)], text)
            return
        self.splice(*block.span, text)
        if block.kind is Kind.HEADING:
            self.report(
                ReportKind.HEADING_ANCHOR,
                block,
                f"anchor #{heading_anchor(block.text)} is now #{heading_anchor(text)}",
            )

    def _change_cell(
        self, span: tuple[int, int], line_no: int, old: str, text: str
    ) -> None:
        """Splice a cell, keeping its width where the source pads it to a pipe."""
        start, end = span
        rest = self.source[end : self.lines.line_end(line_no)]
        pad = len(rest) - len(rest.lstrip(" "))
        room = _width(old) + pad - 1
        if pad and rest[pad : pad + 1] == "|" and _width(text) <= room:
            self.splice(start, end + pad - 1, text + " " * (room - _width(text)))
        else:
            self.splice(start, end, text)

    def _change_description(self, block: Block, text: str) -> None:
        if self.source[slice(*block.span)].startswith((">", "|")):
            self.report(
                ReportKind.FOLDED_DESCRIPTION,
                block,
                "a folded description is not rewritten; edit the front matter",
            )
            return
        dumped = yaml.safe_dump(
            {"description": text},
            allow_unicode=True,
            sort_keys=False,
            width=sys.maxsize,
        )
        value = dumped.removeprefix("description: ").removesuffix("\n")
        if "\n" in value:
            self.report(
                ReportKind.NOT_APPLIED, block, "the description does not fit one line"
            )
            return
        self.splice(*block.span, value)

    def _change_note(self, block: Block, text: str) -> None:
        if "-->" in text:
            self.report(ReportKind.NOT_APPLIED, block, "an author note cannot hold -->")
            return
        self.splice(*block.span, f"<!-- {text} -->")

    def relabel(self, unit: _Unit, group: _Group) -> bool:
        """Write `group` where the source unit it stands for was, if the source can.

        A note whose label the editor removed becomes its Doc paragraph, in place
        of a comment on lines of its own, after a blank line when text ends the
        line above, and after the line a trailing comment ends. A paragraph given
        the label becomes a comment in place of its text. One side is a note and
        the other a paragraph (`_apply_units`). Returns False for a Doc paragraph
        that starts a list item, or a note that would close itself.

        Raises:
            _UnplaceableError: the paragraph sits in a quote, which cannot hold a
                note.
        """
        old, new = self.blocks[unit[0]], group[0]
        if old.kind is Kind.AUTHOR_NOTE:
            if _starts_item(new):
                return False
            texts = [editor_text(leaf.text, markdown=True) for leaf in group]
            if not _is_hosted(old):
                start = old.span[0]
                if old.lines[0] and self.lines.lines[old.lines[0] - 1].strip(" \t>"):
                    # Text on the line above would take the paragraph in as its own.
                    start = self.lines.starts[old.lines[0]]
                    texts[0] = f"{old.prefix.rstrip()}\n{old.prefix}{texts[0]}"
                self.splice(start, old.span[1], _paragraphs(texts, old.continuation))
                return True
            self._unhost(old)
            self._append_after(old, texts, old.continuation)
            return True
        _refuse_quoted(new, old.continuation)
        text = editor_text(new.text, markdown=False)
        if "-->" in text:
            return False
        self.splice(old.span[0], self.blocks[unit[-1]].span[1], f"<!-- {text} -->")
        return True

    # Inserted blocks

    def insert(
        self, group: _Group, *, before: _Anchor | None, after: _Anchor | None
    ) -> bool:
        """Place a unit that exists only in the Doc beside an aligned neighbour.

        Each leaf of an added paragraph becomes a paragraph of its own. A new list
        item goes after the last block of the item before it, its note included, at
        that item's marker (`_item_owner`); a new list after a top-level paragraph,
        heading or note opens a list there. A top-level block typed below a list
        goes after the list item above it (`_list_end`). Returns False, reported,
        for a kind the source does not take from a Doc: a table row, a code block,
        a rule.

        Raises:
            _UnplaceableError: the source has no place for the unit where the Doc
                puts it.
        """
        block = group[0]
        if block.kind is Kind.TABLE_CELL:
            self.report(
                ReportKind.TABLE_SHAPE,
                block,
                "added table rows or columns are not applied",
            )
            return False
        if block.kind not in _PLACEABLE:
            self.report(
                ReportKind.STRUCTURAL_INSERT,
                block,
                f"an added {block.kind.value} is not applied",
            )
            return False
        texts = [editor_text(leaf.text, markdown=True) for leaf in group]
        if block.kind is Kind.HEADING:
            texts = [f"{block.prefix.strip()} {texts[0]}"]
        elif block.kind is Kind.AUTHOR_NOTE:
            text = editor_text(block.text, markdown=False)
            if "-->" in text:
                raise _UnplaceableError(block, "an Author note cannot hold -->")
            texts = [f"<!-- {text} -->"]

        if before and before.entered and before.source.family == "prose":
            _refuse_quoted(block, before.source.continuation)
            self._append_after(before.source, texts, before.source.continuation)
        elif before and _fits(block, before):
            _refuse_quoted(block, before.source.continuation)
            self._insert_after(block, before.source, texts)
        elif before and (owner := self._item_owner(block, before)):
            _refuse_quoted(block, owner.continuation)
            if _starts_item(block):
                self._insert_after(block, before.source, texts, item=owner)
            else:
                self._append_after(before.source, texts, owner.continuation)
        elif before and (end := self._list_end(block, before)) is not None:
            self.splice(end, end, _paragraph_gap("") + _paragraphs(texts, ""))
        elif after and _fits(block, after):
            _refuse_quoted(block, after.source.continuation)
            self._insert_before(block, after.source, texts)
        elif before and _opens_list(block, before):
            self._open_list(block, before.source, texts)
        elif any(
            anchor and anchor.source.kind is Kind.FENCE and anchor.source.depth
            for anchor in (before, after)
        ):
            raise _UnplaceableError(
                block,
                "a paragraph added next to a code block in a list cannot be placed",
            )
        else:
            raise _UnplaceableError(
                block, "an added paragraph sits in no container its neighbours share"
            )
        return True

    def _item_owner(self, block: Block, before: _Anchor) -> Block | None:
        """The first leaf of the list item a new list paragraph after `before` joins.

        A paragraph added after a leaf of a list item, after its note, or after
        anything nested deeper in that item, is in that item when it starts no item
        of its own, and the item after it when it does and its marker is of the
        same kind, numbered or bullet.
        """
        if block.kind is not Kind.LIST_ITEM:
            return None
        anchor = before.source
        if anchor.kind not in _PLACEABLE or anchor.depth != before.edited.depth:
            return None
        index = self.blocks.index(anchor)
        for candidate in reversed(self.blocks[: index + 1]):
            if candidate.depth > block.depth or _is_hosted(candidate):
                continue
            if candidate.depth < block.depth:
                return None
            if candidate.kind is Kind.LIST_ITEM and _starts_item(candidate):
                return candidate if _same_list_kind(block, candidate) else None
            if candidate.kind not in {Kind.LIST_ITEM, Kind.AUTHOR_NOTE}:
                return None
        return None

    def _list_end(self, block: Block, before: _Anchor) -> int | None:
        """Where a new top-level Doc block typed below a top-level list goes.

        Google exports a paragraph typed below a list item, with Enter twice, after
        a blank line and outside the list. It goes after the top-level item that
        holds `before`, which ends the list when that item is its last. None when
        `block` sits in a container or on the line after `before`, or when `before`
        is not text or a note of a top-level list, at one depth in the source and
        the Doc (a paragraph after a code block in a list comes back outside it).
        """
        anchor, edited = before.source, before.edited
        if block.depth or not edited.depth or anchor.depth != edited.depth:
            return None
        if anchor.kind not in _PLACEABLE or edited.kind not in _PLACEABLE:
            return None
        if block.lines[0] <= edited.lines[1]:
            return None
        line = self._line_after(anchor)
        ends = [
            stop
            for start, stop in self.items
            if start <= line < stop and _TOP_ITEM_RE.match(self.lines.lines[start])
        ]
        if not ends:
            return None
        return self.lines.line_end(max(ends) - 1)

    def _line_after(self, anchor: Block) -> int:
        """The source line that text placed after `anchor` follows.

        A comment in a table cell is a paragraph after the table in the Doc, so text
        after it follows the table.
        """
        last = anchor.lines[1] - 1
        for block in self.blocks:
            if (
                block.cell is not None
                and block.cell.lines[0] <= last < block.cell.lines[1]
            ):
                return block.cell.lines[1] - 1
        return last

    def _insert_after(
        self,
        block: Block,
        anchor: Block,
        texts: Sequence[str],
        *,
        item: Block | None = None,
    ) -> None:
        """Add `texts` after `anchor`'s line; a list item at the marker of `item`.

        `item` is the first leaf of the item the new one follows, `anchor` itself
        when it is none other.
        """
        if not _starts_item(block):
            self._append_after(anchor, texts, anchor.continuation)
            return
        item = item or anchor
        end = self.lines.line_end(self._line_after(anchor))
        text = _paragraphs(texts, item.continuation)
        self.splice(end, end, f"\n{item.prefix}{text}")

    def _open_list(self, block: Block, anchor: Block, texts: Sequence[str]) -> None:
        """Add list item `block` after `anchor`'s line, opening a list there.

        An item added after one of its kind this page already opened there joins
        its list.
        """
        end = self.lines.line_end(self._line_after(anchor))
        opened = (end, _is_numbered(block))
        gap = "\n" if opened in self.lists else "\n\n"
        self.lists.append(opened)
        text = _paragraphs(texts, block.continuation)
        self.splice(end, end, f"{gap}{block.prefix}{text}")

    def _append_after(
        self, anchor: Block, texts: Sequence[str], continuation: str
    ) -> None:
        """Add `texts` as paragraphs at `continuation` after `anchor`'s line."""
        end = self.lines.line_end(self._line_after(anchor))
        self.splice(
            end, end, _paragraph_gap(continuation) + _paragraphs(texts, continuation)
        )

    def _insert_before(self, block: Block, anchor: Block, texts: Sequence[str]) -> None:
        if _is_hosted(anchor):
            # A comment that ends a line sits on its host's line, so "before it" in
            # the Doc is after that line in the source.
            self._insert_after(block, anchor, texts)
            return
        start = self.lines.starts[anchor.lines[0]]
        continuation = anchor.continuation
        text = _paragraphs(texts, continuation)
        if _starts_item(block):
            self.splice(start, start, f"{anchor.prefix}{text}\n")
        else:
            self.splice(
                start, start, f"{continuation}{text}\n{continuation.rstrip()}\n"
            )

    # Deleted blocks

    def delete(self, units: Sequence[_Unit]) -> None:
        """Delete source units gone from the Doc, where the source can lose them."""
        doomed: set[int] = set()
        for unit in units:
            block = self.blocks[unit[0]]
            if block.kind is Kind.TABLE_CELL:
                self.report(
                    ReportKind.TABLE_SHAPE,
                    block,
                    "removed table rows or columns are not applied",
                )
            elif block.kind not in _PLACEABLE:
                self.report(
                    ReportKind.STRUCTURAL_DELETE,
                    block,
                    f"a removed {block.kind.value} is not applied",
                )
            else:
                doomed.update(unit)

        for start, end in callout_lines(self.source):
            body = [
                index
                for index, block in enumerate(self.blocks)
                if start < block.lines[0] < end
            ]
            if body and doomed.issuperset(body):
                for index in body:
                    self.report(
                        ReportKind.STRUCTURAL_DELETE,
                        self.blocks[index],
                        "removing every paragraph of a callout is not applied",
                    )
                doomed.difference_update(body)

        # Last first, so each check sees the final fate of every later block. A
        # comment ending a line goes with that line when the line goes.
        hosted = {index for index in doomed if _is_hosted(self.blocks[index])}
        for unit in sorted(units, reverse=True):
            if (
                unit[0] in doomed
                and unit[0] not in hosted
                and not self._delete_run(unit[0], unit[-1], doomed)
            ):
                doomed.difference_update(unit)
        for index in sorted(hosted):
            note = self.blocks[index]
            if note.lines[0] not in self.deleted_lines:
                self._unhost(note)

    def _unhost(self, note: Block) -> None:
        """Remove a note that ends a line of other text, and the space before it."""
        line_start = self.lines.starts[note.lines[0]]
        self.splice(line_start + len(note.prefix.rstrip()), note.span[1], "")

    def _delete_run(self, first: int, last: int, doomed: set[int]) -> bool:
        """Delete source leaves `first` to `last`, one unit's, if the source can."""
        block, end = self.blocks[first], self.blocks[last]
        later = [
            other
            for position, other in enumerate(self.blocks)
            if position > last and position not in doomed
        ]
        if any(other.lines[0] < end.lines[1] for other in later):
            self.report(
                ReportKind.NOT_APPLIED,
                block,
                "its line holds text that stays, so it is not removed",
            )
            return False
        if _starts_item(block) and later:
            item_end = max(
                (stop for start, stop in self.items if start == block.lines[0]),
                default=end.lines[1],
            )
            if later[0].lines[0] < item_end:
                self.report(
                    ReportKind.NOT_APPLIED,
                    block,
                    "removing the first paragraph of a list item that holds more"
                    " is not applied",
                )
                return False

        self._delete_lines(block.lines[0], end.lines[1])
        if block.kind is Kind.HEADING:
            self.report(
                ReportKind.HEADING_ANCHOR,
                block,
                f"heading removed with anchor #{heading_anchor(block.text)}",
            )
        return True

    def _delete_lines(self, first: int, last: int) -> None:
        """Delete lines `[first, last)` and one of the blank lines around them.

        Deletions run last first, so the line after them is the first line from
        `last` on that no deletion took.
        """
        lines = self.lines.lines

        def blank(line_no: int) -> bool:
            return (
                0 <= line_no < len(lines)
                and line_no not in self.deleted_lines
                and not lines[line_no].strip(" \t>")
            )

        after = last
        while after in self.deleted_lines:
            after += 1
        self.deleted_lines.update(range(first, last))
        if blank(first - 1) and blank(after):
            self.deleted_lines.add(first - 1)
        elif first == 0 and blank(after):
            self.deleted_lines.add(after)

    # Rendering

    def render(self) -> str:
        """Apply every splice, re-rendering each padded table a splice touched.

        A table in the padded form `_render_table` writes is re-rendered, so its
        columns stay aligned; any other table keeps its layout, with each cell
        spliced in place.
        """
        tables = sorted(
            {block.cell.lines for block in self.blocks if block.cell is not None}
        )
        edits = list(self._line_deletions())
        touched: dict[tuple[int, int], list[Edit]] = {}
        for edit in self.edits:
            # Text inserted at a table's end goes after the table.
            table = next(
                (
                    span
                    for span in tables
                    if self.lines.starts[span[0]]
                    <= edit.start
                    < self.lines.line_end(span[1] - 1)
                    and edit.end <= self.lines.line_end(span[1] - 1)
                ),
                None,
            )
            if table is None:
                edits.append(edit)
            else:
                touched.setdefault(table, []).append(edit)
        for (first, last), table_edits in touched.items():
            start = self.lines.starts[first]
            end = self.lines.line_end(last - 1)
            prefix = next(
                block.continuation
                for block in self.blocks
                if block.cell is not None and block.cell.lines == (first, last)
            )
            table = self.source[start:end]
            if _render_table(table, prefix=prefix) != table:
                edits.extend(table_edits)
                continue
            shifted = [
                Edit(edit.start - start, edit.end - start, edit.replacement)
                for edit in table_edits
            ]
            table = apply_text_edits(table, shifted)
            edits.append(Edit(start, end, _render_table(table, prefix=prefix)))
        return apply_text_edits(self.source, edits)

    def _line_deletions(self) -> Iterator[Edit]:
        """One splice per run of consecutive deleted lines."""
        lines = sorted(self.deleted_lines)
        for _, run in itertools.groupby(
            enumerate(lines), lambda item: item[1] - item[0]
        ):
            numbers = [line_no for _, line_no in run]
            start = self.lines.starts[numbers[0]]
            after = numbers[-1] + 1
            end = (
                self.lines.starts[after]
                if after < len(self.lines.lines)
                else len(self.source)
            )
            yield Edit(start, end, "")


def _paragraph_gap(continuation: str) -> str:
    """A paragraph break in a container whose paragraphs start with `continuation`."""
    return f"\n{continuation.rstrip()}\n{continuation}"


def _paragraphs(texts: Iterable[str], continuation: str) -> str:
    """`texts` as paragraphs of a container (`_paragraph_gap`)."""
    return _paragraph_gap(continuation).join(texts)


def _is_hosted(block: Block) -> bool:
    """Whether a block is an author note that ends a line of other text."""
    return block.kind is Kind.AUTHOR_NOTE and not _OWN_LINE_PREFIX_RE.fullmatch(
        block.prefix
    )


def _fits(block: Block, anchor: _Anchor) -> bool:
    """Whether a new Doc block sits in the same container as an aligned neighbour.

    The neighbour's source and export must agree on its depth, since the export loses
    containers (a paragraph after a fence in a list comes back outside the list). A
    new list item joins the neighbour's list only when both markers are of one kind,
    numbered or bullet.
    """
    source, edited = anchor.source, anchor.edited
    if source.kind not in _PLACEABLE or edited.kind not in _PLACEABLE:
        return False
    if source.depth != edited.depth or block.depth != edited.depth:
        return False
    if _starts_item(block) != _starts_item(edited):
        return False
    if _starts_item(block) and not _same_list_kind(block, source):
        return False
    if block.depth == 0:
        return True
    return Kind.AUTHOR_NOTE in {block.kind, edited.kind} or block.kind is edited.kind


def _entered(before: Block, block: Block) -> bool:
    """Whether Doc block `block` is a paragraph made with Enter at the end of `before`.

    Google exports it on the line after `before`, which ends in two spaces, and in
    the same container, so it belongs in the source container of `before`.
    """
    return block.after_break and before.lines[1] == block.lines[0]


def _opens_list(block: Block, before: _Anchor) -> bool:
    """Whether a new Doc block is the first item of a list after a top-level block.

    It starts an item of a list at the top level, and the neighbour before it is a
    top-level paragraph, heading or note in the source and in the Doc.
    """
    return (
        _starts_item(block)
        and block.depth == 1
        and before.source.depth == before.edited.depth == 0
        and before.source.kind in {Kind.PARAGRAPH, Kind.HEADING, Kind.AUTHOR_NOTE}
    )


def _refuse_quoted(block: Block, continuation: str) -> None:
    """Refuse an Author note written where `continuation` puts it in a quote.

    The source cannot hold a comment inside a `>` quote. A callout body is indented
    in the source, so a note may sit there.

    Raises:
        _UnplaceableError: `block` is a note and `continuation` holds a quote marker.
    """
    if block.kind is Kind.AUTHOR_NOTE and ">" in continuation:
        raise _UnplaceableError(block, "an Author note cannot sit in a quote")


def _starts_item(block: Block) -> bool:
    """Whether the block's prefix ends with a list marker (the first leaf of an item)."""
    return block.kind is not Kind.AUTHOR_NOTE and bool(
        _ITEM_START_RE.search(block.prefix)
    )


def _is_numbered(block: Block) -> bool:
    """Whether the block's prefix ends with a numbered list marker."""
    return bool(_ORDERED_START_RE.search(block.prefix))


def _same_list_kind(block: Block, other: Block) -> bool:
    """Whether two list items' markers are of one kind, numbered or bullet."""
    return _is_numbered(block) == _is_numbered(other)


def heading_anchor(heading: str) -> str:
    """The anchor the docs site gives a heading with Markdown text `heading`.

    The site (dfo-website `docsSlug`) takes the heading's rendered text, code spans
    included, lowercases and trims it, drops every character but ASCII letters,
    digits, `_`, `-` and whitespace, and turns each run of whitespace into `-`.
    """
    text = "".join(_text_content(_MARKDOWN.parseInline(heading)[0].children or []))
    dropped = _SLUG_DROP_RE.sub("", text.lower().strip())
    return _SLUG_SPACE_RE.sub("-", dropped)


def _text_content(tokens: Iterable[Token]) -> Iterator[str]:
    """The text an inline token stream shows: raw HTML and image alt text excluded."""
    for token in tokens:
        match token.type:
            case "text" | "code_inline":
                yield token.content
            case "softbreak" | "hardbreak":
                yield "\n"


@dataclass(frozen=True)
class _Part:
    """A piece of a spliced text: `text` as Markdown reads it, `written` as written.

    Kept source text is written as the source holds it; a kept soft line break
    (`join`) is `text` " " and `written` the source's newline and continuation
    prefix, and a kept hard or paragraph break is written as the source has it.
    """

    text: str
    written: str
    new: bool = False
    join: bool = False


# A hard break between the leaves of a paragraph, and a paragraph break.
_HARD_BREAK = "\n"
_PARAGRAPH_BREAK = "\n\n"
_BREAKS_RE = re.compile(r"\n+")


def _splice_text(
    source: str,
    sources: Sequence[_Group],
    baseline: Sequence[_Group],
    edited: Sequence[_Group],
) -> str:
    """The new text of a run of source paragraphs, with only the Doc's edits.

    `sources` are paragraphs of one container, or one heading or table cell, each a
    group of leaves; the result replaces the source from the first leaf's text to
    the last's. Each side reads as one text (`_run_text`): the lines of a leaf
    joined by a space, the leaves of a paragraph by a hard break token `\\n`, and
    paragraphs by `\\n\\n`. The baseline and edited texts, after `normalise`, are
    diffed token by token (`adapter.inline_tokens`). Each unchanged token is
    written as the source holds it, matched to the source by `adapter.token_key`,
    so escapes, link targets, entities, curly quotes, line breaks and hard breaks
    the editor did not touch stay. Changed tokens are written in the source
    dialect: straight quotes, only the escapes rendering needs, and each break as
    a paragraph break at the container's continuation prefix, so a break added in
    the Doc starts a paragraph and a removed one is a space. A source run the
    baseline does not match token for token is rewritten whole when an edit
    touches it. Each change is placed to keep the source's line breaks
    (`_placements`). Where a kept line break would still change how the text
    parses (a word that would open a list at a line start), the lines next to the
    change are joined (`_flattenings`), and failing that every line of the text.
    The text around a heading or cell (`_around`) counts for the escapes. When the
    spliced text would not render as the Doc's text, the Doc's text is written
    whole (`adapter.editor_text`).
    """
    first = sources[0][0]
    around = _around(first)
    paragraph = _paragraph_gap(first.continuation)
    edited_text = _run_text(edited)
    whole = paragraph.join(
        editor_text(block.text, markdown=True, around=around)
        for group in edited
        for block in group
    )

    # Each source line's text span, and the separator before it.
    spans: list[tuple[int, int]] = []
    separators: list[str] = []
    for number, group in enumerate(sources):
        for leaf_number, leaf in enumerate(group):
            lines = leaf.line_spans or (leaf.span,)
            if leaf.text != " ".join(source[start:end] for start, end in lines):
                return whole
            for line_number, span in enumerate(lines):
                separators.append(
                    " "
                    if line_number
                    else _HARD_BREAK
                    if leaf_number
                    else _PARAGRAPH_BREAK
                    if number
                    else ""
                )
                spans.append(span)
    line_starts: list[int] = []
    joins: set[int] = set()
    offset = 0
    for separator, (start, end) in zip(separators, spans, strict=True):
        if separator == " ":
            joins.add(offset)
        offset += len(separator)
        line_starts.append(offset)
        offset += end - start
    text = "".join(
        separator + source[start:end]
        for separator, (start, end) in zip(separators, spans, strict=True)
    )
    ours = inline_tokens(text)
    base = inline_tokens(_run_text(baseline))
    theirs = inline_tokens(edited_text)

    # Where each source token starts in `text`.
    starts = list(itertools.accumulate((len(token) for token in ours), initial=0))

    def at(offset: int) -> int:
        line = bisect.bisect_right(line_starts, offset) - 1
        return spans[line][0] + offset - line_starts[line]

    def kept(index: int) -> _Part:
        return _Part(
            ours[index],
            source[at(starts[index]) : at(starts[index + 1])],
            join=starts[index] in joins and ours[index] == " ",
        )

    aligned = SequenceMatcher(
        None, [_token(t) for t in ours], [_token(t) for t in base], autojunk=False
    ).get_opcodes()
    changes = [
        opcode
        for opcode in SequenceMatcher(
            None, [_space(t) for t in base], [_space(t) for t in theirs], autojunk=False
        ).get_opcodes()
        if opcode[0] != "equal"
    ]
    # The baseline tokens that stand for a kept line break of the source.
    base_joins = {
        b1 + offset
        for tag, s1, s2, b1, _ in aligned
        if tag == "equal"
        for offset in range(s2 - s1)
        if starts[s1 + offset] in joins and ours[s1 + offset] == " "
    }

    def assemble(
        placed: Sequence[_Opcode],
    ) -> tuple[list[_Part], list[str], list[tuple[int, int]]]:
        parts: list[_Part] = []
        edges: list[tuple[int, int]] = []
        position = 0
        for (first_token, last_token), replacement in _splice_regions(aligned, placed):
            parts.extend(kept(index) for index in range(position, first_token))
            fragment = straight_quotes("".join(theirs[slice(*replacement)]))
            edges.append((len(parts), len(parts) + bool(fragment)))
            if fragment:
                fragment = _BREAKS_RE.sub(_PARAGRAPH_BREAK, fragment)
                parts.append(_Part(fragment, fragment, new=True))
            position = last_token
        parts.extend(kept(index) for index in range(position, len(ours)))

        new = {index for index, part in enumerate(parts) if part.new}
        texts = drop_needless_escapes(
            [around[0], *(part.text for part in parts), around[1]],
            editable={index + 1 for index in new},
        )[1:-1]
        if first.kind is Kind.TABLE_CELL:
            texts = [
                _UNESCAPED_PIPE_RE.sub(r"\\|", text) if index in new else text
                for index, text in enumerate(texts)
            ]
        return parts, texts, edges

    placements = [
        assemble(placed)
        for placed in _placements(changes, base=base, theirs=theirs, joins=base_joins)
    ]
    parts, texts, edges = next(
        (
            assembled
            for assembled in placements
            if not _breaks_lines(assembled[0], assembled[1], flat=set())
        ),
        placements[0],
    )
    flat: Set[int] = set()
    if _breaks_lines(parts, texts, flat=flat):
        flat = next(
            (
                option
                for option in _flattenings(parts, edges)
                if not _breaks_lines(parts, texts, flat=option)
            ),
            {index for index, part in enumerate(parts) if part.join},
        )
    if not _renders_alike("".join(texts), edited_text, around=around):
        return whole
    return "".join(
        text.replace(_PARAGRAPH_BREAK, paragraph)
        if part.new
        else " "
        if index in flat
        else part.written
        for index, (part, text) in enumerate(zip(parts, texts, strict=True))
    )


def _run_text(groups: Sequence[_Group]) -> str:
    """The text of a run of paragraphs, each a group of leaves, as `_splice_text`
    reads it: leaves joined by a hard break token, paragraphs by a paragraph break.
    """
    return _PARAGRAPH_BREAK.join(
        _HARD_BREAK.join(normalise(block.text) for block in group) for group in groups
    )


def _placements(
    changes: Sequence[_Opcode],
    *,
    base: Sequence[str],
    theirs: Sequence[str],
    joins: Set[int],
) -> list[list[_Opcode]]:
    """Ways to place `changes` that keep the source's line breaks, best first.

    A change can slide one token over the white space at either edge when the
    result is the same text: deleting " and" is deleting "and ". An insertion
    that ends in a break, right after a kept break, slides before that break, so
    the source's break stays with the text after it. A change that would take a
    line break (a baseline token in `joins`) at its edge slides off it, so the
    break stays and the change sits on the space inside the line. An insertion at
    a line break may go at the end of one line or the start of the next; the
    second placement moves every such insertion to the other side.
    """

    def slid(change: _Opcode, step: int) -> _Opcode | None:
        # The token that leaves the change on one side must equal the one that
        # joins it on the other. The tokens beyond the change are equal already.
        tag, i1, i2, j1, j2 = change
        if step > 0:
            fits = i2 < len(base) and j2 < len(theirs)
            same = fits and _space(base[i1]) == _space(theirs[j1])
        else:
            fits = i1 > 0 and j1 > 0
            same = fits and _space(base[i2 - 1]) == _space(theirs[j2 - 1])
        if not same:
            return None
        return tag, i1 + step, i2 + step, j1 + step, j2 + step

    primary: list[_Opcode] = []
    other: list[_Opcode] = []
    for change in changes:
        _, i1, i2, _, _ = change
        if i1 < i2:
            step = 1 if i1 in joins else -1 if i2 - 1 in joins else 0
            moved = slid(change, step) if step else None
            primary.append(moved or change)
            other.append(moved or change)
            continue
        if i1 and _space(base[i1 - 1]) in {_HARD_BREAK, _PARAGRAPH_BREAK}:
            insertion = slid(change, -1) or change
        else:
            insertion = change
        i1 = insertion[1]
        primary.append(insertion)
        step = 1 if i1 in joins else -1 if i1 - 1 in joins else 0
        other.append((slid(insertion, step) if step else None) or insertion)
    return [primary] if other == primary else [primary, other]


def _breaks_lines(
    parts: Sequence[_Part], texts: Sequence[str], *, flat: Set[int]
) -> bool:
    """Whether keeping the soft line breaks of `parts` not in `flat` changes the text.

    It does when a line would be empty or start or end in white space, or when the
    lines parse differently from the text on one line (a word that would open a
    list at a line start).
    """
    if not any(part.join for part in parts):
        return False
    marked = "".join(
        "\0" if part.join and index not in flat else text
        for index, (part, text) in enumerate(zip(parts, texts, strict=True))
    )
    if any(not line or line != line.strip() for line in marked.split("\0")):
        return True
    return _render_flat(marked.replace("\0", "\n")) != _render_flat(
        marked.replace("\0", " ")
    )


def _flattenings(
    parts: Sequence[_Part], edges: Sequence[tuple[int, int]]
) -> Iterator[set[int]]:
    """Soft line breaks to drop around the changes, fewest first.

    `edges` holds the parts each change wrote, `[start, end)`, empty for a
    deletion. The break before each change, the one after it, then both.
    """
    joins = [index for index, part in enumerate(parts) if part.join]
    before = {
        max(join for join in joins if join < start)
        for start, _ in edges
        if any(join < start for join in joins)
    }
    after = {
        min(join for join in joins if join >= end)
        for _, end in edges
        if any(join >= end for join in joins)
    }
    yield before
    yield after
    yield before | after


def _around(block: Block) -> tuple[str, str]:
    """The source text before and after a block's text that bears on its rendering.

    A heading's marker, after which a closing `#` would be dropped, and a bold
    header cell's `**`.
    """
    if block.kind is Kind.HEADING:
        return "#" * block.level + " ", ""
    if block.cell is not None and block.cell.bold:
        return "**", "**"
    return "", ""


def _renders_alike(text: str, edited: str, *, around: tuple[str, str]) -> bool:
    """Whether spliced source `text` renders as the Doc's `edited` text.

    Both are read paragraph by paragraph, every break a paragraph break, each
    inside `around` (`_around`), as a block, with quotes made straight, since a
    splice writes typed quotes straight.
    """

    def render(inline: str) -> list[str]:
        before, after = around
        return [
            _MARKDOWN.render(straight_quotes(normalise(before + segment + after)))
            for segment in _BREAKS_RE.split(inline)
        ]

    return render(text) == render(edited)


def _space(token: str) -> str:
    """A token, or for white space the break it holds or one space."""
    if not token.isspace():
        return token
    if _PARAGRAPH_BREAK in token:
        return _PARAGRAPH_BREAK
    return _HARD_BREAK if _HARD_BREAK in token else " "


def _token(token: str) -> str:
    """`adapter.token_key`, with breaks kept apart from spaces."""
    return _space(token) if token.isspace() else token_key(token)


type _Opcode = tuple[str, int, int, int, int]
# A baseline token range, and the source range of a blob or the edited range of an
# edit; the other is None.
type _Atom = tuple[int, int, tuple[int, int] | None, tuple[int, int] | None]


def _splice_regions(
    aligned: Sequence[_Opcode], changes: Sequence[_Opcode]
) -> Iterator[tuple[tuple[int, int], tuple[int, int]]]:
    """The source token range each edit rewrites, and the edited range it takes.

    `aligned` are the opcodes from source to baseline tokens, `changes` the non-equal
    opcodes from baseline to edited tokens. A region is an edit widened to every
    source run the baseline does not match token for token (a "blob") that it
    touches, and merged with every edit those runs touch. A zero-width edit or blob
    touches a range it falls strictly inside, or another at its own point.
    """
    atoms: list[_Atom] = sorted(
        [(b1, b2, (s1, s2), None) for tag, s1, s2, b1, b2 in aligned if tag != "equal"]
        + [(i1, i2, None, (j1, j2)) for _, i1, i2, j1, j2 in changes],
        key=lambda atom: atom[:2],
    )
    groups: list[list[_Atom]] = []
    for atom in atoms:
        if groups:
            lo = min(other[0] for other in groups[-1])
            hi = max(other[1] for other in groups[-1])
            if (atom[0] < hi and lo < atom[1]) or lo == hi == atom[0] == atom[1]:
                groups[-1].append(atom)
                continue
        groups.append([atom])

    # The source token boundary at each baseline boundary, taken after (`after`) or
    # before (`before`) a blob that holds source tokens only.
    size = aligned[-1][4] if aligned else 0
    after = [0] * (size + 1)
    before: list[int | None] = [None] * (size + 1)
    for tag, s1, _, b1, b2 in aligned:
        if before[b1] is None:
            before[b1] = s1
        after[b1] = s1
        if tag == "equal":
            for offset in range(1, b2 - b1):
                after[b1 + offset] = before[b1 + offset] = s1 + offset
    end = aligned[-1][2] if aligned else 0
    if before[size] is None:
        before[size] = end
    after[size] = end

    for group in groups:
        edits = [atom[3] for atom in group if atom[3] is not None]
        if not edits:
            continue
        lo = min(atom[0] for atom in group)
        hi = max(atom[1] for atom in group)
        blobs = [atom[2] for atom in group if atom[2] is not None]
        first = min([after[lo], *(blob[0] for blob in blobs)])
        end_before = before[hi]
        assert end_before is not None, "no change ends inside a blob"
        last = max([first, end_before, *(blob[1] for blob in blobs)])
        replacement = (
            min([*(edit[0] for edit in edits), _shifted(changes, lo, low=True)]),
            max([*(edit[1] for edit in edits), _shifted(changes, hi, low=False)]),
        )
        yield (first, last), replacement


def _shifted(changes: Sequence[_Opcode], boundary: int, *, low: bool) -> int:
    """The edited token boundary at a baseline boundary that no change straddles.

    It moves by the length difference of the changes before it. A change ending at
    the boundary is before a region's start; at its end, a change that starts there
    is not.
    """
    shift = 0
    for _, i1, i2, _, j2 in changes:
        if i2 < boundary or (i2 == boundary and (low or i1 < boundary)):
            shift = j2 - i2
        else:
            break
    return boundary + shift


def _render_flat(text: str) -> str:
    """`text` rendered as Markdown blocks, with line breaks read as spaces."""
    return _MARKDOWN.render(text).replace("\n", " ")


# Tables


def _render_table(table: str, *, prefix: str) -> str:
    """Render a GFM table as mdformat-gfm does: padded cells, one space each side.

    `prefix` is the container prefix every row starts with, such as `"> "`.
    """
    header, delimiter, *body = (
        _row_cells(line.removeprefix(prefix)) for line in table.split("\n")
    )
    columns = len(header)
    aligns = [*map(_alignment, delimiter), *[""] * columns][:columns]
    rows = [header, *([*row, *[""] * columns][:columns] for row in body)]
    widths = [
        max(3, *(_width(row[column]) for row in rows)) for column in range(columns)
    ]

    def join(cells: Iterable[str]) -> str:
        return f"{prefix}| " + " | ".join(cells) + " |"

    def pad(text: str, column: int) -> str:
        space = widths[column] - _width(text)
        match aligns[column]:
            case "right":
                return " " * space + text
            case "center":
                return " " * (space // 2) + text + " " * (space - space // 2)
        return text + " " * space

    lines = [join(pad(cell, column) for column, cell in enumerate(row)) for row in rows]
    lines.insert(1, join(map(_delimiter, aligns, widths)))
    return "\n".join(lines)


def _row_cells(line: str) -> list[str]:
    line = line.strip()
    line = line.removeprefix("|")
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [cell.strip() for cell in _UNESCAPED_PIPE_RE.split(line)]


def _alignment(cell: str) -> str:
    match = _DELIMITER_CELL_RE.match(cell)
    if match is None:
        return ""
    left, right = bool(match.group("left")), bool(match.group("right"))
    if left and right:
        return "center"
    return "right" if right else "left" if left else ""


def _delimiter(align: str, width: int) -> str:
    left = ":" if align in {"left", "center"} else "-"
    right = ":" if align in {"right", "center"} else "-"
    return left + "-" * (width - 2) + right


def _width(text: str) -> int:
    """Terminal columns `text` takes: wide characters two, combining marks none."""
    return sum(
        0
        if unicodedata.combining(char)
        else 2
        if unicodedata.east_asian_width(char) in {"W", "F"}
        else 1
        for char in text
    )


# Merging


def _resolve_conflicts(merged: str, *, marker_size: int) -> MergeResult:
    """Merge each conflict of `git merge-file --diff3` output again (`_merge_lines`)."""
    markers: dict[str, str] = {
        "<" * marker_size + " upstream": "upstream",
        "|" * marker_size + " pushed": "pushed",
        "=" * marker_size: "editor",
    }
    closing = ">" * marker_size + " editor"
    out: list[str] = []
    clashes: list[Clash] = []
    sides: dict[str, list[str]] = {}
    side: str | None = None
    for line in _split_lines(merged):
        bare = line.rstrip("\r\n")
        if markers.get(bare) == "upstream" and side is None:
            side, sides = "upstream", {"upstream": [], "pushed": [], "editor": []}
        elif side is not None and markers.get(bare) in {"pushed", "editor"}:
            side = markers[bare]
        elif side == "editor" and bare == closing:
            lines, found = _merge_lines(
                sides["pushed"], upstream=sides["upstream"], editor=sides["editor"]
            )
            out.extend(lines)
            clashes.extend(found)
            side = None
        elif side is not None:
            sides[side].append(line)
        else:
            out.append(line)
    return MergeResult(text="".join(out), clashes=tuple(clashes))


def _split_lines(text: str) -> list[str]:
    """`text` split after each newline; `str.splitlines` also splits at U+2028."""
    return _LINE_RE.findall(text)


@dataclass(frozen=True)
class _LineChange:
    """Base lines `[start, end)` replaced by `lines` on one side of a merge."""

    start: int
    end: int
    lines: Sequence[str]
    editor: bool

    def collides(self, other: _LineChange) -> bool:
        """Whether the two changes cannot both apply.

        They collide when both change one base line, when one inserts strictly inside
        the lines the other changes, or when both insert at one point, since neither
        order is right. An insertion at either edge of a change sits beside it.
        """
        if self.start == self.end and other.start == other.end:
            return self.start == other.start
        return self.start < other.end and other.start < self.end


def _merge_lines(
    base: Sequence[str], *, upstream: Sequence[str], editor: Sequence[str]
) -> tuple[list[str], list[Clash]]:
    """Three-way merge of one conflict's lines; the editor wins where both changed.

    Lines both sides changed are merged again word by word (`_merge_words`), so
    edits to different words of one line both stay. Only words both sides changed
    clash; there the editor's words win, and the lines are returned as a `Clash`.
    """
    out: list[str] = []
    clashes: list[Clash] = []
    for chunk in _merge_chunks(base, upstream=upstream, editor=editor):
        if chunk.editor == chunk.upstream:
            out.extend(chunk.editor)
            continue
        merged, clash = _merge_words(
            "".join(chunk.base), "".join(chunk.upstream), "".join(chunk.editor)
        )
        if clash:
            clashes.append(
                Clash(editor_text=merged, upstream_text="".join(chunk.upstream))
            )
        out.append(merged)
    return out, clashes


def _merge_words(base: str, upstream: str, editor: str) -> tuple[str, bool]:
    """Three-way merge of a run of lines word by word, and whether words clashed.

    Where both sides changed a word (`_merge_tokens`), the editor's wins, unless one
    side changed only the white space after it (`_rewrapped`).
    """
    out: list[str] = []
    clash = False
    for chunk in _merge_chunks(
        _merge_tokens(base),
        upstream=_merge_tokens(upstream),
        editor=_merge_tokens(editor),
    ):
        if chunk.editor == chunk.upstream:
            out.extend(chunk.editor)
        elif (merged := _rewrapped(chunk)) is not None:
            out.extend(merged)
        else:
            clash = True
            out.extend(chunk.editor)
    return "".join(out), clash


def _rewrapped(chunk: _Chunk) -> list[str] | None:
    """Words both sides changed, merged where one side changed only white space.

    Word by word, when both sides changed as many words as the base holds: a word
    one side kept takes the other side's, and a word whose white space alone one
    side changed takes the other side's word with that white space, so an
    upstream rewrap stays beside an editor's word. None when any word clashes.
    """
    if not len(chunk.base) == len(chunk.upstream) == len(chunk.editor):
        return None
    merged = []
    for old, theirs, ours in zip(chunk.base, chunk.upstream, chunk.editor, strict=True):
        word, white = _split_white(old)
        their_word, their_white = _split_white(theirs)
        our_word, our_white = _split_white(ours)
        if theirs in {old, ours}:
            merged.append(ours)
        elif ours == old:
            merged.append(theirs)
        elif their_word == word and our_white == white:
            merged.append(our_word + their_white)
        elif our_word == word and their_white == white:
            merged.append(their_word + our_white)
        else:
            return None
    return merged


def _split_white(token: str) -> tuple[str, str]:
    """A merge token's word and the white space after it."""
    word = token.rstrip()
    return word, token[len(word) :]


def _merge_tokens(text: str) -> list[str]:
    """`adapter.inline_tokens` of `text`, each with the white space after it.

    White space alone is no item of the merge, so a word deleted on one side and a
    word inserted a few words on read as two changes, and an insertion between them lands where its side put it.
    """
    tokens: list[str] = []
    for token in inline_tokens(text):
        if tokens and token.isspace():
            tokens[-1] += token
        else:
            tokens.append(token)
    return tokens


@dataclass(frozen=True)
class _Chunk:
    """A run of a three-way merge: the base items and each side's result.

    Where the sides agree, or only one changed, both hold the merged result.
    """

    base: Sequence[str]
    upstream: Sequence[str]
    editor: Sequence[str]


def _merge_chunks(
    base: Sequence[str], *, upstream: Sequence[str], editor: Sequence[str]
) -> Iterator[_Chunk]:
    """Three-way merge of two sides' changes to `base`, as chunks in order."""
    changes = sorted(
        [
            *_line_changes(base, upstream, editor=False),
            *_line_changes(base, editor, editor=True),
        ],
        key=lambda change: (change.start, change.end),
    )
    groups: list[list[_LineChange]] = []
    for change in changes:
        if groups and any(change.collides(other) for other in groups[-1]):
            groups[-1].append(change)
        else:
            groups.append([change])

    position = 0
    for group in groups:
        start = min(change.start for change in group)
        end = max(change.end for change in group)
        if position < start:
            kept = base[position:start]
            yield _Chunk(kept, kept, kept)
        theirs = _side_lines(base, start, end, [c for c in group if not c.editor])
        ours = _side_lines(base, start, end, [c for c in group if c.editor])
        if any(c.editor for c in group) and any(not c.editor for c in group):
            yield _Chunk(base[start:end], theirs, ours)
        else:
            result = ours if group[0].editor else theirs
            yield _Chunk(base[start:end], result, result)
        position = end
    if position < len(base):
        kept = base[position:]
        yield _Chunk(kept, kept, kept)


def _line_changes(
    base: Sequence[str], other: Sequence[str], *, editor: bool
) -> Iterator[_LineChange]:
    """One side's changes to `base`; a run of replaced items is one change per item.

    The items are lines, or the tokens of the lines both sides changed.
    """
    matcher = SequenceMatcher(None, base, other, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace" and i2 - i1 == j2 - j1:
            for offset in range(i2 - i1):
                line = j1 + offset
                yield _LineChange(
                    i1 + offset, i1 + offset + 1, other[line : line + 1], editor=editor
                )
        elif tag != "equal":
            yield _LineChange(i1, i2, other[j1:j2], editor=editor)


def _side_lines(
    base: Sequence[str], start: int, end: int, changes: Sequence[_LineChange]
) -> list[str]:
    """Base lines `[start, end)` with one side's `changes` applied."""
    out: list[str] = []
    position = start
    for change in changes:
        out.extend(base[position : change.start])
        out.extend(change.lines)
        position = change.end
    out.extend(base[position:end])
    return out
