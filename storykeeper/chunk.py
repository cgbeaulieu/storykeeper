"""Cutting documents into passages along their real structure.

The rule that drives everything here: **a chunk never crosses a structural
boundary.** Headings, chapter titles, scene breaks and entry separators all end
a chunk. Length is only consulted *inside* a section, once the structure has run
out of things to say.

This matters more for a novelist's notes than for ordinary prose. A character
sheet that gets cut halfway down Maren's entry, with Kestrel's entry glued to
the bottom, produces an answer that is fluent, cited, and about the wrong
person. That failure is invisible to the reader and corrosive to trust, so the
chunker is deliberately conservative: it would rather emit two small passages
than one that mixes two people.

Chunks are slices of the original text, so ``start``/``end`` always point at
something real and a citation can be checked by hand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import ChunkingConfig

# --- structure markers -----------------------------------------------------

_ATX = re.compile(r"^(#{1,6})[ \t]+(\S.*?)[ \t]*#*$")
_UNDERLINE = re.compile(r"^[ \t]*(=+|-+)[ \t]*$")
_SCENE_BREAK = re.compile(
    r"^[ \t]*(?:"
    r"\*[ \t]*\*[ \t]*\*[ \t]*\**"   # * * *
    r"|\*{3,}"                        # ***
    r"|#[ \t]*"                       # a bare # used as a scene divider
    r"|[-_~=]{3,}"                    # --- ___ ~~~ ===
    r"|§+"                       # section sign
    r"|<>"
    r"|\.{4,}"
    r")[ \t]*$"
)
_CHAPTER = re.compile(
    r"^[ \t]*("
    r"(?:chapter|part|book|prologue|epilogue|interlude|act|scene)"
    r"\b[^\n]{0,70}"
    r")[ \t]*$",
    re.I,
)
_ENTRY_LABEL = re.compile(r"^[ \t]*(?:\*\*|__)?([A-Z][^\n:]{0,58}?)(?:\*\*|__)?[ \t]*:[ \t]*$")
_SENTENCE_END = re.compile(r"""[.!?]["'’”)\]]*\s+""")
_PARA_BREAK = re.compile(r"\n[ \t]*\n")

#: Merge key for text that sits under no heading at all.
_ROOT_KEY = "__root__"

#: Sheets of this kind are the ones where merging two entries is dangerous.
ENTRY_DOC_TYPES = frozenset({"character", "location"})


@dataclass
class Chunk:
    text: str
    section: str
    start: int
    end: int


@dataclass
class _Section:
    path: list[str]
    start: int
    end: int
    key: str = ""
    mergeable: bool = True


# ---------------------------------------------------------------------------
# Finding sections
# ---------------------------------------------------------------------------


def _line_offsets(text: str) -> tuple[list[str], list[int]]:
    lines = text.split("\n")
    offsets = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1
    return lines, offsets


def has_headings(text: str) -> bool:
    for line in text.split("\n"):
        if _ATX.match(line):
            return True
    return False


def _is_blank(lines: list[str], i: int) -> bool:
    return i < 0 or i >= len(lines) or not lines[i].strip()


def _looks_like_chapter(lines: list[str], i: int) -> bool:
    """A standalone chapter/scene title line, set off by blank lines."""
    line = lines[i]
    stripped = line.strip()
    if not stripped or len(stripped) > 80 or stripped.endswith((".", ",", ";", "!", "?")):
        return False
    if not _is_blank(lines, i - 1):
        return False
    if _CHAPTER.match(line):
        return True
    # A short all-caps line on its own is the other common manuscript
    # convention for a chapter title. Require blank lines on both sides so a
    # shouted line of dialogue does not split a scene in half.
    letters = [c for c in stripped if c.isalpha()]
    if (
        len(stripped) <= 60
        and letters
        and all(c.isupper() for c in letters)
        and _is_blank(lines, i + 1)
    ):
        return True
    return False


def _looks_like_entry_header(line: str) -> bool:
    """First line of a new entry in a heading-less sheet.

    Deliberately narrow. Getting this wrong in the permissive direction glues
    two characters together, which is the exact failure the chunker exists to
    prevent, so anything that reads like ordinary prose is refused.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 70:
        return False
    if _ENTRY_LABEL.match(line):
        return True
    if stripped.endswith((".", ",", ";", "!", "?", '"')):
        return False
    words = stripped.replace("*", "").replace("_", "").split()
    if not words or len(words) > 8:
        return False
    alpha = [w for w in words if w[0].isalpha()]
    if not alpha:
        return False
    return all(w[0].isupper() for w in alpha)


def find_sections(text: str, *, entry_mode: bool = False) -> list[_Section]:
    """Split text into structural sections, each with its heading path."""
    lines, offsets = _line_offsets(text)
    end_of_text = len(text)

    sections: list[_Section] = []
    stack: list[tuple[int, str]] = []
    body_start = 0
    entry_key: str | None = None
    entry_serial = 0

    def close(at: int) -> None:
        nonlocal body_start
        if at > body_start and text[body_start:at].strip():
            path = [title for _, title in stack]
            if entry_key is not None:
                key, mergeable = entry_key, False
            else:
                key, mergeable = (path[0] if path else _ROOT_KEY), True
            sections.append(
                _Section(path=path, start=body_start, end=at, key=key, mergeable=mergeable)
            )
        body_start = at

    def push_heading(level: int, title: str) -> None:
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))

    i = 0
    while i < len(lines):
        line = lines[i]
        line_start = offsets[i]
        next_start = offsets[i + 1] if i + 1 < len(lines) else end_of_text

        atx = _ATX.match(line)
        if atx:
            close(line_start)
            entry_key = None
            push_heading(len(atx.group(1)), atx.group(2).strip())
            body_start = next_start
            i += 1
            continue

        underline = _UNDERLINE.match(line) if i > 0 else None
        if underline and lines[i - 1].strip() and not _ATX.match(lines[i - 1]):
            # Setext heading: the previous line was its text, so retract it out
            # of the section that was just being accumulated.
            close(offsets[i - 1])
            entry_key = None
            push_heading(1 if underline.group(1)[0] == "=" else 2, lines[i - 1].strip())
            body_start = next_start
            i += 1
            continue

        if entry_mode and _is_blank(lines, i - 1) and _looks_like_entry_header(line):
            close(line_start)
            entry_serial += 1
            entry_key = f"__entry{entry_serial}__"
            stack = [(1, line.strip().rstrip(":").strip("*_ "))]
            body_start = line_start  # keep the entry's own name inside the chunk
            i += 1
            continue

        if _SCENE_BREAK.match(line):
            close(line_start)
            body_start = next_start
            i += 1
            continue

        if _looks_like_chapter(lines, i):
            close(line_start)
            entry_key = None
            push_heading(1, line.strip())
            body_start = next_start
            i += 1
            continue

        i += 1

    close(end_of_text)
    return sections


def _only_headings_between(text: str, start: int, end: int) -> bool:
    """True if the gap between two sections holds nothing but heading lines.

    A heading is a boundary worth respecting only when there is enough on each
    side of it to be worth separating. A scene break is different - it is the
    writer saying "time passed here" - so it is never bridged.
    """
    for line in text[start:end].split("\n"):
        if not line.strip():
            continue
        if not (_ATX.match(line) or _UNDERLINE.match(line)):
            return False
    return True


def _has_content(text: str) -> bool:
    """Is there actually anything here, or just a scene divider and whitespace?

    This is the only filter applied unconditionally. A line like ``* * *`` or a
    stray em dash is not writing and does not belong in search results, but
    "Eyes: grey" is only ten characters and is exactly the kind of thing this
    tool exists to find - so shortness alone is never a reason to discard a
    passage.
    """
    return sum(character.isalnum() for character in text) >= 3


def _common_prefix(a: list[str], b: list[str]) -> list[str]:
    out: list[str] = []
    for left, right in zip(a, b):
        if left != right:
            break
        out.append(left)
    return out


def merge_small_sections(
    text: str, sections: list[_Section], cfg: ChunkingConfig
) -> list[_Section]:
    """Join adjacent sections that belong to the same entity and are both small.

    A character sheet with ``## Appearance`` / ``## Voice`` / ``## Wants`` under
    one name would otherwise become a handful of 200-character passages, each
    too thin to embed meaningfully and each answering only a fragment of "tell
    me about Maren". Merging is allowed only when the sections share a top-level
    heading, so two different people can never end up in one passage.
    """
    if not sections:
        return sections
    merged: list[_Section] = [sections[0]]
    for section in sections[1:]:
        previous = merged[-1]
        if (
            previous.mergeable
            and section.mergeable
            and previous.key == section.key
            and section.end - previous.start <= cfg.target_chars
            and _only_headings_between(text, previous.end, section.start)
        ):
            previous.end = section.end
            previous.path = _common_prefix(previous.path, section.path) or previous.path[:1]
            continue
        merged.append(section)
    return merged


# ---------------------------------------------------------------------------
# Packing a section into chunks
# ---------------------------------------------------------------------------


def _split_oversized(text: str, start: int, end: int, cfg: ChunkingConfig) -> list[tuple[int, int]]:
    """Break one over-long paragraph at sentence ends, then by force."""
    spans: list[tuple[int, int]] = []
    body = text[start:end]
    points = [start]
    for match in _SENTENCE_END.finditer(body):
        points.append(start + match.end())
    points.append(end)

    current = points[0]
    last = points[0]
    for point in points[1:]:
        if point - current > cfg.target_chars and last > current:
            spans.append((current, last))
            current = last
        last = point
    if end > current:
        spans.append((current, end))

    # Anything still too long has no sentence breaks in it at all - a wall of
    # text, or a table. Cut it on whitespace rather than mid-word.
    out: list[tuple[int, int]] = []
    for span_start, span_end in spans:
        while span_end - span_start > cfg.max_chars:
            cut = text.rfind(" ", span_start + cfg.target_chars // 2, span_start + cfg.max_chars)
            if cut == -1:
                cut = span_start + cfg.max_chars
            out.append((span_start, cut))
            span_start = cut + 1
        if span_end > span_start:
            out.append((span_start, span_end))
    return out


def pack_section(text: str, section: _Section, cfg: ChunkingConfig) -> list[tuple[int, int]]:
    """Turn one section into chunk spans, with overlap only inside the section."""
    start, end = section.start, section.end
    if not text[start:end].strip():
        return []
    if end - start <= cfg.max_chars:
        return [(start, end)]

    bounds = [start]
    for match in _PARA_BREAK.finditer(text, start, end):
        bounds.append(match.end())
    bounds.append(end)

    paragraphs: list[tuple[int, int]] = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b <= a:
            continue
        if b - a > cfg.max_chars:
            paragraphs.extend(_split_oversized(text, a, b, cfg))
        else:
            paragraphs.append((a, b))

    spans: list[tuple[int, int]] = []
    current_start: int | None = None
    current_end = start
    for a, b in paragraphs:
        if current_start is None:
            current_start, current_end = a, b
            continue
        if b - current_start <= cfg.target_chars:
            current_end = b
        else:
            spans.append((current_start, current_end))
            current_start, current_end = a, b
    if current_start is not None:
        spans.append((current_start, current_end))

    # Overlap: reach backwards into the previous chunk so a sentence that
    # straddles the seam is readable from both sides. Snapped to a word break,
    # and never past the start of the section - overlap must not leak the
    # previous character's entry into this one.
    if cfg.overlap_chars > 0:
        overlapped: list[tuple[int, int]] = []
        for index, (a, b) in enumerate(spans):
            if index > 0:
                reach = max(start, a - cfg.overlap_chars)
                space = text.find(" ", reach, a)
                a = space + 1 if space != -1 else reach
            overlapped.append((a, b))
        spans = overlapped
    return spans


def chunk_document(
    text: str,
    *,
    doc_type: str = "other",
    cfg: ChunkingConfig | None = None,
    section_prefix: str = "",
) -> list[Chunk]:
    """Split one document into citable passages."""
    cfg = cfg or ChunkingConfig()
    if not text.strip():
        return []

    entry_mode = doc_type in ENTRY_DOC_TYPES and not has_headings(text)
    sections = find_sections(text, entry_mode=entry_mode)
    if not entry_mode:
        sections = merge_small_sections(text, sections, cfg)

    chunks: list[Chunk] = []
    for section in sections:
        label = " > ".join(p for p in section.path if p)
        if section_prefix:
            label = f"{section_prefix} > {label}" if label else section_prefix
        for start, end in pack_section(text, section, cfg):
            body = text[start:end]
            if not _has_content(body) or len(body.strip()) < cfg.min_chars:
                continue
            # Trim surrounding blank lines, and move the offsets with them - a
            # citation is only worth anything if it points at the exact
            # characters the passage was taken from.
            lead = len(body) - len(body.lstrip("\n"))
            trimmed = body.strip("\n")
            chunks.append(
                Chunk(
                    text=trimmed,
                    section=label,
                    start=start + lead,
                    end=start + lead + len(trimmed),
                )
            )
    return chunks
