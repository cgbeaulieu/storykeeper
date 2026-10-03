"""Printing things a writer can read.

No colour, no boxes, no progress spinners. This runs in whatever terminal the
writer happens to open, on whatever operating system they use, and the one
thing worse than plain output is mangled output.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Sequence

from .errors import StorykeeperError
from .search import Hit, LiteralMatch
from .textutil import collapse, snippet_around

_KIND = {
    "manuscript": "manuscript",
    "character": "character notes",
    "history": "history notes",
    "culture": "culture notes",
    "location": "place notes",
    "plot": "plot notes",
    "other": "notes",
}


def width(default: int = 88) -> int:
    try:
        return max(48, min(shutil.get_terminal_size().columns, 100))
    except OSError:
        return default


def setup_console() -> None:
    """Make sure curly quotes and dashes survive on a legacy Windows console."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def rule(char: str = "-") -> str:
    return char * width()


def say(message: str = "") -> None:
    print(message)


def warn(message: str) -> None:
    print(f"Note: {message}", file=sys.stderr)


def fail(error: StorykeeperError) -> None:
    """The only way a Storykeeper problem is ever shown to the user."""
    print(f"\n{error.message}", file=sys.stderr)
    if error.hint:
        print(f"\n{error.hint}", file=sys.stderr)
    print(file=sys.stderr)


def kind_of(hit: Hit) -> str:
    return _KIND.get(hit.doc_type, hit.doc_type)


def source_line(number: int, hit: Hit, *, scores: bool = False) -> str:
    where = hit.section or hit.title
    location = f"{hit.path}" + (f"  >  {where}" if where else "")
    line = f"[{number}] {location}   ({kind_of(hit)})"
    if scores:
        detail = f"match {hit.score:.2f}  meaning {hit.semantic:.2f}  words {hit.literal:.1f}"
        if hit.names_matched:
            detail += f"  names: {', '.join(sorted(hit.names_matched))}"
        if hit.phrase_hit:
            detail += "  exact phrase"
        line += f"\n    {detail}"
    return line


def render_sources(
    hits: Sequence[Hit],
    *,
    chars: int = 700,
    scores: bool = False,
    heading: str = "Passages used",
) -> str:
    if not hits:
        return "Nothing in your library matched that."
    out = [f"{heading}:", ""]
    for number, hit in enumerate(hits, 1):
        out.append(source_line(number, hit, scores=scores))
        text = hit.text.strip()
        if len(text) > chars:
            text = text[:chars].rstrip() + " ..."
        out.extend(_indent(text))
        out.append("")
    return "\n".join(out).rstrip()


def _indent(text: str, prefix: str = "    ") -> list[str]:
    """Re-wrap a passage to the terminal.

    Line breaks inside a paragraph belong to the writer's own file, not to this
    terminal, so they are collapsed before wrapping. Blank lines are kept -
    those are structure, and the whole point of showing a passage is that it
    looks like what is in the file.
    """
    import re
    import textwrap

    limit = width() - len(prefix)
    lines: list[str] = []
    for paragraph in re.split(r"\n[ \t]*\n", text):
        if not paragraph.strip():
            continue
        if lines:
            lines.append("")
        flat = " ".join(paragraph.split())
        lines.extend(
            textwrap.wrap(flat, limit, initial_indent=prefix, subsequent_indent=prefix)
        )
    return lines


def render_matches(matches: Sequence[LiteralMatch], needle: str, context: int) -> str:
    """Output for `storykeeper find` - one line of context per occurrence."""
    if not matches:
        return ""
    out: list[str] = []
    current_path = None
    for match in matches:
        row = match.row
        if row["path"] != current_path:
            current_path = row["path"]
            out.append("")
            out.append(f"{current_path}   ({_KIND.get(row['doc_type'], row['doc_type'])})")
        window, offset = snippet_around(
            row["text"], match.local, match.local + match.length, context
        )
        relative = match.local - offset
        marked = (
            window[:relative]
            + ">>" + window[relative:relative + match.length] + "<<"
            + window[relative + match.length:]
        )
        where = row.get("section") or row.get("title") or ""
        label = f"  {where}: " if where else "  "
        out.append(f"{label}...{collapse(marked, 220)}...")
    return "\n".join(out).lstrip("\n")
