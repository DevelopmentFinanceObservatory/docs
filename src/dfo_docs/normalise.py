"""Normalise a fetched markdown file into the corpus dialect.

Operates on the fetched copy only; source repositories are read only.
`normalise_markdown` is the entry point manifest.py calls. The rest of this module is
its five transforms, exposed individually because each is independently testable and
because the trap in the admonition transform (see its docstring) is worth being able to
exercise in isolation.
"""

from __future__ import annotations

import posixpath
import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

from markdown_it import MarkdownIt
from markdown_it.token import Token

_INDENT = "    "

# A page's leading YAML front matter. The corpus keeps it, and the site strips it.
FRONTMATTER_RE = re.compile(r"\A---\r?\n(?P<body>.*?)\r?\n---\r?\n?", re.DOTALL)

_ADMONITION_TYPES = {
    "warning": "WARNING",
    "note": "NOTE",
    "tip": "TIP",
    "info": "NOTE",
    "abstract": "IMPORTANT",
}

_ADMONITION_MARKER_RE = re.compile(
    r'^!!!\s+(?P<type>\S+)(?:\s+"(?P<title>[^"]*)")?\s*$'
)
_HEADING_RE = re.compile(r"^#{1,6}(\s|$)")
_FENCE_RE = re.compile(r"^(?P<indent>\s*)```(?P<info>.*)$")

_TRANSCLUDE_RE = re.compile(r'^\s*--8<--\s+"(?P<target>[^"]+)"\s*$')

# The parser `strip_html_comments` asks what counts as an HTML comment. Tables are on
# so a comment in a GFM table cell is an inline token. `text_join` is off so a
# backslash-escaped or entity `<` stays its own token and never reads as an opener.
_MARKDOWN = MarkdownIt("commonmark").enable("table").disable("text_join")
# Every comment in an HTML block's raw text, including the short forms `<!-->` and
# `<!--->`.
_COMMENT_RE = re.compile(r"<!---?>|<!--[\s\S]*?-->")
# An HTML block opened by an element whose content HTML reads as text, where `<!--`
# opens no comment.
_RAW_TEXT_BLOCK_RE = re.compile(r"\s*<(?:script|style|textarea)(?:[\s>]|$)", re.I)

_PY_FENCE_TAG_RE = re.compile(r"^py(?P<rest>\s.*)?$")

_LINK_RE = re.compile(r"(?<!!)\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)\)")
_MKDOCS_DIR_LINK_RE = re.compile(
    r"^(?P<up>(?:\.\./)+)(?P<slug>[^/#]+)/(?P<fragment>#.*)?$"
)
_EXTENSIONLESS_SIBLING_RE = re.compile(r"^\./(?P<slug>[^/#.]+)(?P<fragment>#.*)?$")
_MD_LINK_TARGET_RE = re.compile(r"^(?P<path>[^#]+\.md)(?P<fragment>#.*)?$")


class NormaliseError(Exception):
    """A fetched file could not be normalised.

    Raised when a `--8<--` transclusion target is missing, or when a link resolves to a
    page `Source.exclude` holds out of the corpus and the source declares no `docs_url`
    to rewrite the link to.
    """


def normalise_markdown(
    text: str,
    *,
    repo_root: Path,
    page_path: Path | None = None,
    docs_root: Path | None = None,
    source_name: str | None = None,
    excluded: tuple[str, ...] = (),
    docs_url: str | None = None,
) -> str:
    """Transform one fetched markdown file's text into the corpus dialect.

    `repo_root` is the source repository's own root (not its docs directory), which is
    what a `--8<--` transclusion target resolves against. `page_path` is the fetched
    copy's own path, used only to check whether an extensionless sibling link (see
    `normalise_links`) resolves to a real file next to it; a caller that omits it skips
    that rule, which simply does not fire. `docs_root` is the source's docs directory
    that `page_path` sits under; given together with `page_path`, it lets the MkDocs
    directory-link rewrite (see `normalise_links`) tell a directory index apart from a
    normal page, which changes how many `../` segments the rewrite drops. Runs
    transclusion first, so injected content goes through the same admonition, comment,
    fence, and link transforms as everything else. It then converts admonitions to GFM
    alerts, drops HTML comments (author notes such as `<!-- TODO -->`, see
    `strip_html_comments`), retags `py` fences to `python`, and rewrites the MkDocs
    directory-form link dialect to a corpus-relative `.md` link. Comments go after the
    admonitions because an admonition body is indented four spaces, which CommonMark
    reads as code until it becomes a GFM alert. Mermaid, footnotes, `$$` math,
    `md_in_html`, and frontmatter carry no transform and pass through untouched.

    `source_name`, `excluded`, and `docs_url` (`Sidecar.excluded` and `Sidecar.docs_url`
    for the source `page_path` belongs to) are passed straight through to
    `normalise_links`, which is where a link into `excluded` is rewritten or raises. All
    three are only meaningful together with `page_path` and `docs_root`; see
    `normalise_links` for what happens when one of those two is missing.

    Raises:
        NormaliseError: a `--8<--` transclusion target does not exist under `repo_root`,
            an HTML comment opens and never closes or cannot be told apart from code,
            or a link resolves into `excluded` and `docs_url` is unset.
    """
    text = expand_transclusion(text, repo_root=repo_root)
    text = convert_admonitions(text)
    text = strip_html_comments(
        text, page=_page_label(page_path, docs_root=docs_root, source_name=source_name)
    )
    text = normalise_fence_tags(text)
    return normalise_links(
        text,
        page_path=page_path,
        docs_root=docs_root,
        source_name=source_name,
        excluded=excluded,
        docs_url=docs_url,
    )


def expand_transclusion(text: str, *, repo_root: Path) -> str:
    """Expand every `--8<-- "target"` line against `repo_root`.

    The target is resolved against the source repository's root, not the docs root,
    because source repositories transclude their own `CHANGELOG.md` and
    `CONTRIBUTING.md` from outside the docs tree. Never rewrites inside a fenced code
    block.

    Raises:
        NormaliseError: `target` does not exist under `repo_root`.
    """
    out_lines = []
    in_fence = False
    for line in text.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out_lines.append(line)
            continue

        match = _TRANSCLUDE_RE.match(line) if not in_fence else None
        if match is None:
            out_lines.append(line)
            continue

        target_name = match.group("target")
        # The target is resolved and confirmed to stay inside repo_root. It comes from
        # a fetched repository's markdown, so a `../` segment would otherwise read any
        # file the build can see and publish it to a public corpus.
        root = repo_root.resolve()
        target = (root / target_name).resolve()
        if not target.is_relative_to(root):
            raise NormaliseError(
                f"transclusion target {target_name!r} resolves outside {repo_root}"
            )
        if not target.is_file():
            raise NormaliseError(
                f"transclusion target {target_name!r} not found under {repo_root}"
            )
        out_lines.append(target.read_text())

    return "\n".join(out_lines)


def _page_label(
    page_path: Path | None, *, docs_root: Path | None, source_name: str | None
) -> str:
    """Name the page in an error, in the `'source': 'file'` form `normalise_links` uses."""
    if page_path is None:
        return "<page>"
    rel = page_path.relative_to(docs_root) if docs_root is not None else page_path
    label = repr(rel.as_posix())
    return f"{source_name!r}: {label}" if source_name is not None else label


def strip_html_comments(text: str, *, page: str = "<page>") -> str:
    """Drop every HTML comment outside code, leaving clean Markdown behind.

    A CommonMark parser (markdown-it-py, with GFM tables) decides what is a comment: an
    inline HTML token whose text begins with `<!--`, or a `<!-- ... -->` anywhere in an
    HTML block, including one opened by another tag such as `<div>`. A comment inside a
    fenced or indented code block or a code span is content and stays, as is `<!--` in
    a `<script>`, `<style>` or `<textarea>` block, which HTML reads as text. Leading
    YAML front matter is left as it is.

    A comment mid-line takes the spaces and tabs before it only when whitespace or the
    end of the text follows it, so a prose line or a table cell keeps no trailing gap
    and two words never join. A comment that opens a line's content, after only
    indentation and `>` markers, takes the whitespace after it instead, so the text that
    follows keeps its indentation. A line the removal leaves holding only indentation
    and `>` markers is dropped. Where that line was a comment block of its own between
    two non-blank lines, one blank line (carrying any `>` prefix) takes its place, so
    the blocks CommonMark saw stay separate. A comment line inside a larger HTML block
    goes without one, since a blank line would end that block. Where dropping a line
    would put two blank lines together, one goes.

    `page` names the page in the error, as `normalise_markdown` builds it.

    Raises:
        NormaliseError: a `<!--` outside code has no closing `-->`, or a comment's text
            also appears as code in the same block, so its place in the source is
            ambiguous.
    """
    frontmatter = FRONTMATTER_RE.match(text)
    head = text[: frontmatter.end()] if frontmatter is not None else ""
    body = text[len(head) :]
    spans = _comment_spans(body, page=page)
    if not spans:
        return text
    return head + _remove_spans(body, spans)


def _comment_spans(body: str, *, page: str) -> list[tuple[int, int, bool]]:
    """Return the sorted `(start, end, own_block)` of every HTML comment outside code.

    `own_block` is true for a comment CommonMark reads as a block of its own, which is
    what separates the blocks either side of it.
    """
    line_starts = [0, *(match.end() for match in re.finditer("\n", body))]

    def offset(line: int) -> int:
        return line_starts[line] if line < len(line_starts) else len(body)

    spans: list[tuple[int, int, bool]] = []
    for (first, last), comments, own_block in _comments_by_block(
        _MARKDOWN.parse(body), page
    ):
        lo, hi = offset(first), offset(last)
        for comment, expected in Counter(comments).items():
            found = [m.span() for m in _source_pattern(comment).finditer(body, lo, hi)]
            if len(found) != expected:
                raise NormaliseError(
                    f"{page}: HTML comment {comment[:60]!r} appears {len(found)} "
                    f"times in its block, but the parser reads {expected} of them as "
                    "comments and the rest as code. Reword one copy so each is unique"
                )
            spans.extend((start, end, own_block) for start, end in found)
    spans.sort()
    return spans


def _comments_by_block(
    tokens: list[Token], page: str
) -> Iterator[tuple[tuple[int, int], list[str], bool]]:
    """Yield each block's source line range, the comment texts parsed inside it, and
    whether the block is itself a comment rather than prose or other HTML."""
    for token in tokens:
        if token.map is None:
            continue
        line_range = (token.map[0], token.map[1])
        if token.type == "html_block" and not _RAW_TEXT_BLOCK_RE.match(token.content):
            _refuse_unclosed(_COMMENT_RE.sub("", token.content), page)
            own_block = token.content.lstrip().startswith("<!--")
            yield line_range, _COMMENT_RE.findall(token.content), own_block
        elif token.type == "inline":
            comments: list[str] = []
            for child in _inline_tokens(token.children or []):
                if child.type == "html_inline" and child.content.startswith("<!--"):
                    comments.append(child.content)
                elif child.type == "text":
                    _refuse_unclosed(child.content, page)
            if comments:
                yield line_range, comments, False


def _inline_tokens(tokens: list[Token]) -> Iterator[Token]:
    """Yield inline tokens depth-first, including those nested in an image's alt."""
    for token in tokens:
        yield token
        yield from _inline_tokens(token.children or [])


def _refuse_unclosed(text: str, page: str) -> None:
    """Raise if `text`, which holds no closed comment, still holds an opener."""
    opener = text.find("<!--")
    if opener != -1:
        raise NormaliseError(
            f"{page}: HTML comment {text[opener : opener + 60]!r} never closes with "
            "'-->'"
        )


def _source_pattern(comment: str) -> re.Pattern[str]:
    """Match `comment` in the source, where each continuation line may carry the
    indentation and `>` markers its container stripped from the token."""
    return re.compile(r"\n[ \t>]*".join(map(re.escape, comment.split("\n"))))


def _remove_spans(body: str, spans: list[tuple[int, int, bool]]) -> str:
    """Cut `spans` out of `body`, then tidy the lines the cuts touched."""
    stripped = ""
    touched_lines: set[int] = set()  # output line numbers a removal touched
    separator_lines: set[int] = set()  # the touched lines that held a comment block
    kept_from = 0
    for start, end, own_block in spans:
        stripped += body[kept_from:start]
        kept_from = end
        if _is_blankish(stripped[stripped.rfind("\n") + 1 :]):
            while kept_from < len(body) and body[kept_from] in " \t":
                kept_from += 1
        elif kept_from == len(body) or body[kept_from].isspace():
            stripped = stripped.rstrip(" \t")
        touched_lines.add(stripped.count("\n"))
        if own_block:
            separator_lines.add(stripped.count("\n"))
    stripped += body[kept_from:]

    lines = stripped.split("\n")
    out_lines: list[str] = []
    number = 0
    while number < len(lines):
        if number not in touched_lines or not _is_blankish(lines[number]):
            out_lines.append(lines[number])
            number += 1
            continue
        after = number
        while (
            after < len(lines) and after in touched_lines and _is_blankish(lines[after])
        ):
            after += 1
        before_blank = not out_lines or _is_blankish(out_lines[-1])
        after_blank = after == len(lines) or _is_blankish(lines[after])
        separates = not separator_lines.isdisjoint(range(number, after))
        if separates and not before_blank and not after_blank:
            out_lines.append(lines[number].rstrip())
        elif before_blank and after_blank and after < len(lines):
            if out_lines:
                out_lines.pop()
            else:
                after += 1
        number = after
    return "\n".join(out_lines)


def _is_blankish(line: str) -> bool:
    """True for a line holding only whitespace and blockquote `>` markers."""
    return line.strip(" \t>") == ""


def convert_admonitions(text: str) -> str:
    """Convert `!!!` admonitions to GFM alerts.

    `warning`, `note`, and `tip` map to `WARNING`, `NOTE`, and `TIP`; `info` becomes
    `NOTE`; `abstract` becomes `IMPORTANT`. A title folds into the body as a bold lead
    sentence on the body's first line. The admonition type is matched
    case-insensitively; any other type is left untouched, as is any `!!!` line inside
    a fenced code block.

    The corpus carries two body shapes, and indentation cannot be used to tell them
    apart on its own. It can only confirm the indented shape once it has been seen.
    Both are read:

    - **Indented** (the shape Python-Markdown's extension actually requires): the body
      is every line from directly after the marker that is blank or indented by four
      spaces, stopping at the first blank-trimmed, non-indented line or end of file.
      Leading and trailing blank lines in that run are dropped; blank lines in the
      middle are kept as paragraph breaks.
    - **Unindented** (what closes the block early and leaves a loose paragraph beneath
      an empty box on the live site): the body is the single paragraph immediately
      following the marker (the contiguous run of non-blank lines up to the first
      blank line, heading, fence open, or end of file). This is deliberately
      conservative. Every unindented admonition in the corpus today is a single
      paragraph, and stopping at the first paragraph boundary avoids folding unrelated
      prose into the alert on some future file that isn't.

    An admonition with no body at all (marker followed immediately by a heading,
    fence, another marker, or end of file) still renders the title, since dropping it
    silently would lose text the author wrote.
    """
    lines = text.split("\n")
    out_lines: list[str] = []
    in_fence = False
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out_lines.append(line)
            i += 1
            continue

        match = _ADMONITION_MARKER_RE.match(line) if not in_fence else None
        alert_kind = (
            _ADMONITION_TYPES.get(match.group("type").lower()) if match else None
        )

        if match is None or alert_kind is None:
            out_lines.append(line)
            i += 1
            continue

        body_lines, next_i = _extract_admonition_body(lines, i)
        out_lines.extend(_render_alert(alert_kind, match.group("title"), body_lines))
        i = next_i

    return "\n".join(out_lines)


def _extract_admonition_body(
    lines: list[str], marker_index: int
) -> tuple[list[str], int]:
    """Return the admonition body after `lines[marker_index]`, and where it ends."""
    n = len(lines)

    peek = marker_index + 1
    while peek < n and lines[peek].strip() == "":
        peek += 1
    if peek >= n or not lines[peek].startswith(_INDENT):
        return _extract_unindented_body(lines, marker_index)
    return _extract_indented_body(lines, marker_index)


def _extract_indented_body(
    lines: list[str], marker_index: int
) -> tuple[list[str], int]:
    n = len(lines)
    end = marker_index + 1
    while end < n and (lines[end].strip() == "" or lines[end].startswith(_INDENT)):
        end += 1

    raw = lines[marker_index + 1 : end]
    while raw and raw[0].strip() == "":
        raw.pop(0)
    while raw and raw[-1].strip() == "":
        raw.pop()
        end -= 1  # leave trailing blank lines for the outer loop to re-emit as-is

    body = [line[len(_INDENT) :] if line.startswith(_INDENT) else line for line in raw]
    return body, end


def _extract_unindented_body(
    lines: list[str], marker_index: int
) -> tuple[list[str], int]:
    n = len(lines)
    end = marker_index + 1
    while end < n:
        line = lines[end]
        if line.strip() == "" or _HEADING_RE.match(line) or _FENCE_RE.match(line):
            break
        end += 1

    return lines[marker_index + 1 : end], end


def _render_alert(alert_kind: str, title: str | None, body: list[str]) -> list[str]:
    out = [f"> [!{alert_kind}]"]

    if title:
        lead = title.strip()
        if lead and lead[-1] not in ".!?":
            lead += "."
        rest = f" {body[0]}" if body and body[0].strip() != "" else ""
        body = [f"**{lead}**{rest}", *body[1:]] if body else [f"**{lead}**"]

    out.extend(f"> {line}" if line else ">" for line in body)
    return out


def normalise_fence_tags(text: str) -> str:
    """Retag `py` fences to `python`. Every other fence tag is left alone."""
    lines = text.split("\n")
    out_lines = []
    in_fence = False

    for line in lines:
        match = _FENCE_RE.match(line)
        out_line = line
        if match is not None:
            if not in_fence:
                info = match.group("info")
                retagged = _PY_FENCE_TAG_RE.sub(
                    lambda m: f"python{m.group('rest') or ''}", info
                )
                if retagged != info:
                    out_line = f"{match.group('indent')}```{retagged}"
            in_fence = not in_fence
        out_lines.append(out_line)

    return "\n".join(out_lines)


class _PageDepth(NamedTuple):
    """How deep `page_path` sits under `docs_root`, for the directory-link rewrite."""

    is_index: bool
    depth: int


class _ExclusionContext(NamedTuple):
    """What a link into `Sidecar.excluded` needs to be rewritten or reported.

    `page_rel_dir` is the linking page's own directory, posix-relative to `docs_root`
    (`"."` at the docs root), against which a target is resolved before checking
    `excluded` membership. `linking_file` is the linking page itself, in the same
    docs-root-relative form, used only to name it in a raised `NormaliseError`.
    """

    source_name: str
    linking_file: str
    page_rel_dir: str
    excluded: tuple[str, ...]
    docs_url: str | None


def normalise_links(
    text: str,
    *,
    page_path: Path | None = None,
    docs_root: Path | None = None,
    source_name: str | None = None,
    excluded: tuple[str, ...] = (),
    docs_url: str | None = None,
) -> str:
    """Rewrite the MkDocs directory-form link dialect to a corpus-relative `.md` link.

    `[text](../slug/#anchor)` becomes `[text](slug.md#anchor)` relative to the current
    page. The leading `../` run is an artifact of MkDocs' directory URLs (every
    non-index page is served from its own directory, and an index page one level
    shallower still), not a real filesystem hop, so one segment is dropped for a
    normal page and none for a directory index. Telling the two apart, and knowing how
    deep the page itself sits, needs both `page_path` and `docs_root`; without both,
    this falls back to treating every page as a normal (non-index) page, which is
    today's behaviour. When the rewritten target would need more `../` segments than
    the page's own directory depth allows, the link escapes the source's subtree
    entirely (the case a root-level `index.md` hits), and it is left unrewritten for
    the link checker to report. Plain `[Caching](caching.md)` links already carry
    `.md` and are left untouched, as is anything that isn't a `../`-prefixed
    directory-style target.

    A third, undocumented dialect is a bare extensionless sibling link such as
    `[World Bank](./world-bank)`. A blanket "append `.md`" rule for it would also
    corrupt a scheme-less external link such as `[Comtrade database](comtrade.un.org)`,
    so `./<slug>` is only rewritten to `./<slug>.md` when `page_path` is given and
    `<slug>.md` exists next to it on disk; a broken sibling link (the target file does
    not exist under that name) is left alone so a link checker can still report it.
    Without `page_path` this rule does not fire at all. Never rewrites inside a fenced
    code block.

    A plain `.md` link that survives every rule above is normally left untouched. If it
    resolves, relative to `page_path`, to a file `excluded` lists (`Sidecar.excluded`,
    the pages `Source.exclude` held out of this corpus), it is rewritten instead into an
    absolute URL on the source's own site: `docs_url` (`Sidecar.docs_url`) joined to the
    target's directory-URL form (`.md` stripped, a trailing `/` added), with any anchor
    fragment carried through unchanged. This needs `page_path`, `docs_root`,
    `source_name`, and a non-empty `excluded` together; any one missing and the rule
    does not fire, same as the two rules above. When it would fire but `docs_url` is
    unset, raises `NormaliseError` naming `source_name`, the linking file, and the
    target, before this or any other page is written.

    Raises:
        NormaliseError: a link resolves into `excluded` and `docs_url` is unset.
    """
    page_dir = page_path.parent if page_path is not None else None
    page_depth: _PageDepth | None = None
    if page_path is not None and docs_root is not None:
        rel = page_path.relative_to(docs_root)
        page_depth = _PageDepth(
            is_index=rel.name == "index.md", depth=len(rel.parent.parts)
        )

    exclusion_ctx: _ExclusionContext | None = None
    if (
        excluded
        and source_name is not None
        and page_path is not None
        and docs_root is not None
    ):
        rel = page_path.relative_to(docs_root)
        exclusion_ctx = _ExclusionContext(
            source_name=source_name,
            linking_file=rel.as_posix(),
            page_rel_dir=rel.parent.as_posix(),
            excluded=excluded,
            docs_url=docs_url,
        )

    lines = text.split("\n")
    out_lines = []
    in_fence = False

    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        if in_fence:
            out_lines.append(line)
            continue
        out_lines.append(
            _LINK_RE.sub(
                lambda m: _rewrite_link(
                    m,
                    page_dir=page_dir,
                    page_depth=page_depth,
                    exclusion_ctx=exclusion_ctx,
                ),
                line,
            )
        )

    return "\n".join(out_lines)


def _rewrite_link(
    match: re.Match[str],
    *,
    page_dir: Path | None,
    page_depth: _PageDepth | None,
    exclusion_ctx: _ExclusionContext | None,
) -> str:
    target = match.group("target")

    dialect = _MKDOCS_DIR_LINK_RE.match(target)
    if dialect is not None:
        up_count = dialect.group("up").count("../")
        # A directory index renders one level shallower than a normal page, so it
        # consumes one fewer `../` segment than a normal page does. Without page_depth
        # (no docs_root given), every page is treated as a normal page, matching the
        # pre-existing behaviour.
        new_up_count = (
            up_count if page_depth is not None and page_depth.is_index else up_count - 1
        )
        if page_depth is not None and new_up_count > page_depth.depth:
            # The rewritten target would climb above the page's own directory depth,
            # i.e. escape the source's subtree entirely. Leave it for the link checker.
            return match.group(0)
        new_up = "../" * new_up_count
        fragment = dialect.group("fragment") or ""
        new_target = f"{new_up}{dialect.group('slug')}.md{fragment}"
        return f"[{match.group('text')}]({new_target})"

    if page_dir is not None:
        sibling = _EXTENSIONLESS_SIBLING_RE.match(target)
        if sibling is not None and (page_dir / f"{sibling.group('slug')}.md").is_file():
            fragment = sibling.group("fragment") or ""
            new_target = f"./{sibling.group('slug')}.md{fragment}"
            return f"[{match.group('text')}]({new_target})"

    if exclusion_ctx is not None:
        rewritten = _rewrite_excluded_link(match, target, exclusion_ctx)
        if rewritten is not None:
            return rewritten

    return match.group(0)


def _rewrite_excluded_link(
    match: re.Match[str], target: str, ctx: _ExclusionContext
) -> str | None:
    """Rewrite `target` to `ctx.docs_url` if it resolves into `ctx.excluded`, or return
    None if it does not (including every non-`.md` target, which `excluded` never
    lists).

    Raises:
        NormaliseError: `target` resolves into `ctx.excluded` and `ctx.docs_url` is
            None.
    """
    parsed = _MD_LINK_TARGET_RE.match(target)
    if parsed is None:
        return None

    raw_path = parsed.group("path")
    if "://" in raw_path or raw_path.startswith("/"):
        return None

    candidate = posixpath.normpath(posixpath.join(ctx.page_rel_dir, raw_path))
    if candidate not in ctx.excluded:
        return None

    if ctx.docs_url is None:
        raise NormaliseError(
            f"{ctx.source_name!r}: {ctx.linking_file!r} links to {target!r}, which "
            f"sources.yaml excludes from the corpus, and the sidecar declares no "
            f"docs_url to rewrite it to"
        )

    fragment = parsed.group("fragment") or ""
    directory_url = f"{candidate[: -len('.md')]}/"
    new_target = f"{ctx.docs_url.rstrip('/')}/{directory_url}{fragment}"
    return f"[{match.group('text')}]({new_target})"
