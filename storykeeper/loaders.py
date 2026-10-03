"""Turning the files a novelist actually keeps into plain text.

Every loader is registered in :data:`LOADERS` against a file extension, and each
one returns a list of :class:`LoadedDoc`. Adding a new format is one function
plus one :func:`register_loader` call - nothing else in the codebase needs to
know about it.

Most of these are written against the standard library on purpose. A ``.docx``
is a zip containing XML, and so is an ``.odt``; reading them directly costs
about forty lines and saves a dependency that would have to keep working on a
writer's machine for years. PDF is the exception - it genuinely needs a
parser - and if that parser is missing, PDFs are skipped with a useful message
instead of a crash.
"""

from __future__ import annotations

import logging
import re
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from .textutil import clean_text, decode_bytes


class DocumentError(Exception):
    """This one file could not be read. Indexing continues without it."""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint


@dataclass
class LoadedDoc:
    """One document's worth of text.

    Most files produce exactly one of these. Containers - a Scrivener project
    is the live example - produce many, one per document in the binder, each
    with its own title and its own place in the hierarchy.
    """

    text: str
    title: str = ""
    section_prefix: str = ""
    doc_id: str = ""


Loader = Callable[[Path], list[LoadedDoc]]

#: extension (lowercase, with dot) -> loader
LOADERS: dict[str, Loader] = {}
#: extensions that name a *folder* rather than a file, e.g. ``.scriv``
CONTAINER_SUFFIXES: set[str] = set()


def register_loader(suffixes: Iterable[str], fn: Loader, *, container: bool = False) -> None:
    """Make a file type loadable. This is the whole extension mechanism."""
    for suffix in suffixes:
        suffix = suffix.lower()
        if not suffix.startswith("."):
            suffix = "." + suffix
        LOADERS[suffix] = fn
        if container:
            CONTAINER_SUFFIXES.add(suffix)


def supported_suffixes() -> list[str]:
    return sorted(LOADERS)


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in LOADERS


def load_document(path: Path) -> list[LoadedDoc]:
    """Read one file (or container folder) into text. Raises DocumentError."""
    loader = LOADERS.get(path.suffix.lower())
    if loader is None:
        raise DocumentError(f"Storykeeper does not know how to read {path.suffix} files.")
    try:
        docs = loader(path)
    except DocumentError:
        raise
    except (OSError, zipfile.BadZipFile, ET.ParseError, ValueError) as exc:
        raise DocumentError(
            f"The file could not be opened ({type(exc).__name__}: {exc}).",
            "It may be damaged, or still open and locked by another program. "
            "Close it and run 'storykeeper index' again.",
        ) from None
    out = []
    for doc in docs:
        doc.text = clean_text(doc.text)
        if doc.text.strip():
            out.append(doc)
    return out


# ---------------------------------------------------------------------------
# Plain text and Markdown
# ---------------------------------------------------------------------------

# Tolerates CRLF, because a note written on Windows has CRLF and this would
# otherwise leave "tags: [draft]" sitting in the middle of search results.
_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*\r?\n", re.S)


def load_text_file(path: Path) -> list[LoadedDoc]:
    text = decode_bytes(path.read_bytes())
    # Obsidian and static-site notes start with a YAML block that is metadata,
    # not writing. Keeping it would put "tags: [draft]" in the middle of search
    # results for no benefit.
    text = _FRONTMATTER.sub("", text, count=1)
    return [LoadedDoc(text=text, title=pretty_title(path))]


register_loader([".txt", ".text", ".md", ".markdown", ".mdown", ".mkd"], load_text_file)


# ---------------------------------------------------------------------------
# Word (.docx)
# ---------------------------------------------------------------------------

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_paragraph_text(para: ET.Element) -> str:
    parts: list[str] = []
    for node in para.iter():
        tag = node.tag
        if tag == _W + "t":
            parts.append(node.text or "")
        elif tag == _W + "tab":
            parts.append("\t")
        elif tag in (_W + "br", _W + "cr"):
            parts.append("\n")
        elif tag == _W + "noBreakHyphen":
            parts.append("-")
    return "".join(parts)


def _docx_heading_level(para: ET.Element) -> int:
    """Return a Markdown heading level for a styled paragraph, else 0.

    Word's own outline styles are the only structure a .docx reliably carries,
    and turning them into Markdown headings means the chunker can use the same
    code path it uses for .md notes.
    """
    style = para.find(f"{_W}pPr/{_W}pStyle")
    if style is None:
        return 0
    val = (style.get(_W + "val") or "").lower()
    if val in ("title", "heading", "heading1"):
        return 1
    if val == "subtitle":
        return 2
    match = re.fullmatch(r"heading\s*(\d)", val)
    return int(match.group(1)) if match else 0


def load_docx(path: Path) -> list[LoadedDoc]:
    with zipfile.ZipFile(path) as archive:
        try:
            xml = archive.read("word/document.xml")
        except KeyError:
            raise DocumentError(
                "This does not look like a Word document inside.",
                "If you renamed another file to .docx, rename it back.",
            ) from None
    body = ET.fromstring(xml).find(_W + "body")
    if body is None:
        return []

    lines: list[str] = []
    for element in body.iter(_W + "p"):
        text = _docx_paragraph_text(element).strip()
        level = _docx_heading_level(element)
        if level and text:
            lines.append("")
            lines.append("#" * level + " " + text)
            lines.append("")
        elif text:
            lines.append(text)
        else:
            lines.append("")
    return [LoadedDoc(text="\n".join(lines), title=pretty_title(path))]


register_loader([".docx"], load_docx)


# ---------------------------------------------------------------------------
# OpenDocument (.odt)
# ---------------------------------------------------------------------------

_TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


def _odt_element_text(node: ET.Element) -> str:
    parts: list[str] = [node.text or ""]
    for child in node:
        tag = child.tag
        if tag == _TEXT_NS + "s":
            count = int(child.get(_TEXT_NS + "c") or 1)
            parts.append(" " * count)
        elif tag == _TEXT_NS + "tab":
            parts.append("\t")
        elif tag == _TEXT_NS + "line-break":
            parts.append("\n")
        else:
            parts.append(_odt_element_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def load_odt(path: Path) -> list[LoadedDoc]:
    with zipfile.ZipFile(path) as archive:
        try:
            xml = archive.read("content.xml")
        except KeyError:
            raise DocumentError("This does not look like an OpenDocument file inside.") from None
    root = ET.fromstring(xml)

    lines: list[str] = []
    for node in root.iter():
        if node.tag == _TEXT_NS + "h":
            text = _odt_element_text(node).strip()
            level = int(node.get(_TEXT_NS + "outline-level") or 1)
            if text:
                lines += ["", "#" * min(level, 6) + " " + text, ""]
        elif node.tag == _TEXT_NS + "p":
            lines.append(_odt_element_text(node).strip())
    return [LoadedDoc(text="\n".join(lines), title=pretty_title(path))]


register_loader([".odt"], load_odt)


# ---------------------------------------------------------------------------
# Rich Text (.rtf) - Scrivener's per-document storage format
# ---------------------------------------------------------------------------

_RTF_TOKEN = re.compile(
    r"\\([a-zA-Z]{1,32})(-?\d{1,10})?[ ]?"   # control word, optional argument
    r"|\\'([0-9a-fA-F]{2})"                   # \'hh  byte escape
    r"|\\([^a-zA-Z])"                         # escaped literal, e.g. \{ \} \\
    r"|([{}])"                                # group open/close
    r"|[\r\n]+"                               # raw newlines are not text in RTF
    r"|([^\\{}\r\n]+)"                        # a run of plain text
)

# Control words whose whole group is metadata: fonts, colours, styles, embedded
# pictures, revision bookkeeping. None of it is writing. A hyperlink is a
# ``\field`` holding the address in ``\fldinst`` and the words on the page in
# ``\fldrslt``, so only the address is skipped.
_RTF_SKIP_GROUPS = frozenset("""
fonttbl colortbl stylesheet listtable listoverridetable rsidtbl generator info
pict object objdata result themedata colorschememapping latentstyles datastore
xmlnstbl mmathPr filetbl revtbl userprops bkmkstart bkmkend header footer
headerl headerr footerl footerr footnote ftnsep xe tc fldinst nonshppict
shppict do shpinst
""".split())

_RTF_LITERALS = {
    "par": "\n", "line": "\n", "sect": "\n\n", "page": "\n\n",
    "tab": "\t", "cell": "\t", "nestcell": "\t", "row": "\n", "nestrow": "\n",
    "lquote": "\u2018", "rquote": "\u2019",
    "ldblquote": "\u201c", "rdblquote": "\u201d",
    "bullet": "\u2022", "endash": "\u2013", "emdash": "\u2014",
    "emspace": " ", "enspace": " ", "qmspace": " ",
    # Escaped symbols: non-breaking space, non-breaking hyphen, optional
    # hyphen, index subentry, formula. A backslash before a line break is a
    # paragraph break - TextEdit, and so Mac Scrivener, writes one per paragraph.
    "~": "\u00a0", "_": "-", "-": "", ":": "", "|": "",
    "\n": "\n", "\r": "\n",
}


def rtf_to_text(data: bytes) -> str:
    """De-RTF a document. Handles what Scrivener, Word and TextEdit emit.

    RTF is byte-oriented with escapes, so the source is decoded as latin-1 to
    keep every byte addressable, and ``\\'hh`` escapes are mapped through the
    document's own code page afterwards.
    """
    source = data.decode("latin-1", errors="replace")
    codepage = "cp1252"
    match = re.search(r"\\ansicpg(\d+)", source[:2048])
    if match:
        candidate = "cp" + match.group(1)
        try:
            b"".decode(candidate)
            codepage = candidate
        except LookupError:
            pass

    out: list[str] = []
    pending: list[int] = []          # \'hh bytes awaiting decode as a group
    depth = 0
    skip_until_depth: int | None = None
    unicode_skip = 1
    skip_chars = 0

    def flush_bytes() -> None:
        if pending:
            out.append(bytes(pending).decode(codepage, errors="replace"))
            pending.clear()

    for token in _RTF_TOKEN.finditer(source):
        word, arg, hexbyte, literal, brace, text = token.groups()

        if brace == "{":
            flush_bytes()
            depth += 1
            continue
        if brace == "}":
            flush_bytes()
            depth -= 1
            if skip_until_depth is not None and depth < skip_until_depth:
                skip_until_depth = None
            continue

        skipping = skip_until_depth is not None

        if word is not None:
            flush_bytes()
            if word == "u" and arg is not None:
                if not skipping:
                    code = int(arg)
                    if code < 0:
                        code += 65536
                    out.append(chr(code))
                skip_chars = unicode_skip
                continue
            if word == "uc" and arg is not None:
                unicode_skip = max(0, int(arg))
                continue
            if word in _RTF_SKIP_GROUPS:
                if skip_until_depth is None:
                    skip_until_depth = depth
                continue
            if not skipping and word in _RTF_LITERALS:
                out.append(_RTF_LITERALS[word])
            continue

        if hexbyte is not None:
            if skip_chars > 0:
                skip_chars -= 1
            elif not skipping:
                pending.append(int(hexbyte, 16))
            continue

        if literal is not None:
            flush_bytes()
            if literal == "*":
                # \*\something - an optional destination we do not understand.
                if skip_until_depth is None:
                    skip_until_depth = depth
            elif not skipping and literal in "{}\\":
                out.append(literal)
            elif not skipping and literal in _RTF_LITERALS:
                out.append(_RTF_LITERALS[literal])
            continue

        if text is not None:
            flush_bytes()
            if skip_chars > 0:
                consumed = min(skip_chars, len(text))
                skip_chars -= consumed
                text = text[consumed:]
            if text and not skipping:
                out.append(text)

    flush_bytes()
    return "".join(out)


def load_rtf(path: Path) -> list[LoadedDoc]:
    return [LoadedDoc(text=rtf_to_text(path.read_bytes()), title=pretty_title(path))]


register_loader([".rtf"], load_rtf)


def load_rtfd(path: Path) -> list[LoadedDoc]:
    """A TextEdit document with pictures: a folder holding TXT.rtf and the images.

    On a Mac it looks like one file, so it is titled after the bundle - not
    after the TXT.rtf inside it, which every one of these has.
    """
    inner = path / "TXT.rtf"
    if not inner.is_file():
        raise DocumentError(
            "This .rtfd document has no text inside that Storykeeper can find.",
            "Open it in TextEdit and use File > Save As to save a copy as "
            "Rich Text (.rtf), then put that copy in your library folder.",
        )
    return [LoadedDoc(text=rtf_to_text(inner.read_bytes()), title=pretty_title(path))]


register_loader([".rtfd"], load_rtfd, container=True)


# ---------------------------------------------------------------------------
# Scrivener projects (.scriv) - a folder, not a file
# ---------------------------------------------------------------------------

def _scriv_binder_items(node: ET.Element, trail: list[str]) -> list[tuple[str, str, list[str]]]:
    """Walk the binder, returning (id, title, ancestor titles) per text item."""
    found: list[tuple[str, str, list[str]]] = []
    for item in node.findall("BinderItem"):
        item_type = item.get("Type", "")
        title_node = item.find("Title")
        title = (title_node.text or "").strip() if title_node is not None else ""
        if item_type == "TrashFolder":
            continue
        item_id = item.get("UUID") or item.get("ID") or ""
        if item_type in ("Text", "Folder") and item_id:
            found.append((item_id, title, list(trail)))
        children = item.find("Children")
        if children is not None:
            found.extend(_scriv_binder_items(children, trail + ([title] if title else [])))
    return found


def _scriv_read_content(project: Path, item_id: str) -> str:
    """Find one binder item's text. Scrivener 3 and 2 store it differently."""
    candidates = [
        project / "Files" / "Data" / item_id / "content.rtf",
        project / "Files" / "Data" / item_id / "content.txt",
        project / "Files" / "Docs" / f"{item_id}.rtf",
        project / "Files" / "Docs" / f"{item_id}.txt",
    ]
    for candidate in candidates:
        if candidate.exists():
            data = candidate.read_bytes()
            return rtf_to_text(data) if candidate.suffix == ".rtf" else decode_bytes(data)
    return ""


def load_scrivener(path: Path) -> list[LoadedDoc]:
    scrivx = sorted(path.glob("*.scrivx"))
    if not scrivx:
        raise DocumentError(
            "This folder ends in .scriv but has no Scrivener project file inside.",
            "Open it in Scrivener once to check it is not damaged, or point "
            "Storykeeper at an exported copy of your work instead.",
        )
    root = ET.parse(scrivx[0]).getroot()
    binder = root.find("Binder")
    if binder is None:
        raise DocumentError("The Scrivener project file has no binder in it.")

    docs: list[LoadedDoc] = []
    for item_id, title, trail in _scriv_binder_items(binder, []):
        text = _scriv_read_content(path, item_id).strip()
        if not text:
            continue
        # Give the chunker the binder title as a real heading, so a passage from
        # "Chapter 3 / The Crossing" is cited by that name and not by a UUID.
        heading = "# " + (title or "Untitled")
        docs.append(
            LoadedDoc(
                text=f"{heading}\n\n{text}",
                title=title or "Untitled",
                section_prefix=" > ".join(trail),
                doc_id=item_id,
            )
        )
    if not docs:
        raise DocumentError("The Scrivener project has no text in it yet.")
    return docs


register_loader([".scriv"], load_scrivener, container=True)


# ---------------------------------------------------------------------------
# PDF - the one format that needs an outside library
# ---------------------------------------------------------------------------


def load_pdf(path: Path) -> list[LoadedDoc]:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        raise DocumentError(
            "Reading PDFs needs one extra piece that is not installed.",
            "Run the setup script again - setup.cmd on Windows, ./setup.sh on "
            "Mac or Linux. It installs the PDF reader and leaves your writing "
            "alone. Until then, Storykeeper will simply skip PDFs.",
        ) from None
    # pypdf logs its own warnings about slightly malformed files straight to
    # the console. Problems that matter are raised and reported per file below.
    logging.getLogger("pypdf").setLevel(logging.ERROR)

    # pypdf raises its own error types for damaged and password-protected
    # files, and they share no useful base class with anything else here.
    try:
        reader = PdfReader(str(path))
        # Many PDFs are "encrypted" only to restrict printing or copying, with
        # an empty password to open them. Those read normally.
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentError(
                "This PDF is password-protected.",
                "Save an unprotected copy and put that in your library folder.",
            )
        pages = []
        for number, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(f"## Page {number}\n\n{text}")
    except DocumentError:
        raise
    except Exception as exc:  # noqa: BLE001 - see comment above
        raise DocumentError(
            f"This PDF could not be read ({type(exc).__name__}: {exc}).",
            "It may be damaged. If it opens normally on your computer, try "
            "printing it to a new PDF and putting that copy in the library.",
        ) from None
    if not pages:
        raise DocumentError(
            "No text could be pulled out of this PDF.",
            "It is probably a scan - a picture of a page rather than words. "
            "Storykeeper cannot read those.",
        )
    return [LoadedDoc(text="\n\n".join(pages), title=pretty_title(path))]


register_loader([".pdf"], load_pdf)


# ---------------------------------------------------------------------------
# Formats we deliberately refuse, with an explanation
# ---------------------------------------------------------------------------

_UNSUPPORTED_HINTS = {
    ".doc": (
        "Old-style Word documents (.doc) cannot be read directly.",
        "Open it in Word and use File > Save As to save a copy as .docx, "
        "then put that copy in your library folder.",
    ),
    ".pages": (
        "Apple Pages documents cannot be read directly.",
        "Open it in Pages and use File > Export To > Word, then put the .docx "
        "in your library folder.",
    ),
    ".gdoc": (
        "This is a shortcut to a Google Doc, not the document itself - the "
        "writing lives on Google's servers, not on your computer.",
        "In Google Docs use File > Download > Microsoft Word (.docx) and put "
        "the downloaded file in your library folder. Storykeeper has no way to "
        "read it without a copy on this machine, and reaching out to fetch one "
        "is exactly what this tool is built not to do.",
    ),
    ".one": (
        "OneNote notebooks cannot be read directly.",
        "In OneNote use File > Export to save a section as .docx, then put that "
        "in your library folder.",
    ),
    ".odf": ("This looks like an OpenDocument file with an unusual extension.",
             "Rename it to .odt if it is a text document."),
}


def unsupported_hint(path: Path) -> tuple[str, str] | None:
    return _UNSUPPORTED_HINTS.get(path.suffix.lower())


# ---------------------------------------------------------------------------


def pretty_title(path: Path) -> str:
    """A human title from a filename: ``maren_vesh-notes.md`` -> ``Maren Vesh Notes``."""
    stem = re.sub(r"[_\-]+", " ", path.stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    if not stem:
        return path.name
    # Leave deliberate capitalisation alone; only fix all-lowercase filenames.
    if stem.islower():
        stem = " ".join(w.capitalize() for w in stem.split())
    return stem
