"""Shared text handling: decoding, normalising, tokenising.

Two different kinds of normalisation live here and they must not be confused:

* :func:`clean_text` produces the text we *store and show*. It fixes line
  endings and strips control characters, and otherwise leaves the writing
  exactly as it was typed - curly quotes, em dashes, spacing and all. A citation
  has to quote what is actually in the file.

* :func:`normalize_for_match` produces the text we *search*. It folds curly
  quotes to straight ones, dashes to hyphens, and case to lower, so that typing
  ``don't`` finds ``don't``. It is never shown to anyone.
"""

from __future__ import annotations

import re
import unicodedata

# Characters a word processor substitutes silently. Folding these at match time
# is what stops a search for a straight apostrophe missing every line of
# dialogue in a manuscript written in Word.
_MATCH_FOLD = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "‒": "-", "―": "-", "−": "-",
    "…": "...", "\u00a0": " ", "\u2009": " ", "\u200a": " ",
    "\u202f": " ", "\u2007": " ", "\ufeff": "",
    "\u200b": "", "\u200c": "", "\u200d": "",
}
_MATCH_TABLE = str.maketrans(_MATCH_FOLD)

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TRAILING_WS = re.compile(r"[ \t]+(?=\n)")
_BLANK_RUN = re.compile(r"\n{4,}")

#: Words that are capitalised often enough to be useless as name evidence.
COMMON_WORDS = frozenset("""
a an the and or but if then than that this these those there here when where
who whom whose what which why how is are was were be been being am do does did
have has had can could will would shall should may might must not no nor of in
on at to for with by from as into about over under after before between during
i he she it we you they him her them his hers its their our your my me us
""".split())


def decode_bytes(data: bytes) -> str:
    """Decode a text file without ever raising.

    Tries the encodings a Windows/Mac writing setup actually produces, in the
    order that makes an incorrect guess least damaging.
    """
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def clean_text(text: str) -> str:
    """Normalise line endings and strip junk, preserving the writing itself."""
    text = text.replace("\ufeff", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(" ", "\n").replace(" ", "\n\n")
    text = text.replace("\x0c", "\n\n")  # page break -> paragraph break
    text = _CONTROL.sub("", text)
    text = _TRAILING_WS.sub("", text)
    text = _BLANK_RUN.sub("\n\n\n", text)
    return text.strip("\n")


def normalize_for_match(text: str) -> str:
    """Fold typography and case so literal search behaves the way people expect."""
    text = unicodedata.normalize("NFKC", text)
    return text.translate(_MATCH_TABLE).lower()


# The same fold, restricted to substitutions that swap one character for exactly
# one character. NFKC and the ellipsis expansion both change a string's length,
# which would slide every character offset after them - fine for ranking, fatal
# for a citation that promises to point at a real position in a real file.
_MATCH_TABLE_SAME_LENGTH = str.maketrans(
    {key: value for key, value in _MATCH_FOLD.items() if len(value) == 1}
)


def fold_preserving_offsets(text: str) -> str:
    """Fold typography and case without moving any character.

    Falls back to the original text in the rare cases where lowercasing changes
    a string's length (some Turkish and Lithuanian forms), because a slightly
    stricter search is better than a citation that points at the wrong word.
    """
    folded = text.translate(_MATCH_TABLE_SAME_LENGTH).lower()
    return folded if len(folded) == len(text) else text


# Any letter or digit in any script, so "Séverine" and "Zoë" stay whole words.
_TOKEN = re.compile(r"[^\W_]+(?:'[^\W_]+)*")

#: Raise this whenever :func:`tokenize` would split the same text differently.
#: A literal index saved under another version is rebuilt when it is loaded.
TOKENIZER_VERSION = 2


def tokenize(text: str) -> list[str]:
    """Split into lowercase word tokens for the literal-match index.

    Possessives are folded (``Maren's`` -> ``maren``) so that asking about
    "Maren's sister" still scores chunks that only ever say "Maren".
    """
    folded = normalize_for_match(text)
    out: list[str] = []
    for raw in _TOKEN.findall(folded):
        token = raw
        if token.endswith("'s") or token.endswith("s'"):
            token = token[:-2] if token.endswith("'s") else token[:-1]
        token = token.replace("'", "")
        if token:
            out.append(token)
    return out


def query_terms(query: str) -> list[tuple[str, str]]:
    """Tokenise a question, keeping the original spelling of each token.

    Returns ``(normalised, as_typed)`` pairs. The as-typed form is what tells us
    whether the writer capitalised a word, which is the strongest cheap signal
    that it is an invented name rather than an ordinary English word.
    """
    pairs: list[tuple[str, str]] = []
    for match in _TOKEN.finditer(unicodedata.normalize("NFKC", query).translate(_MATCH_TABLE)):
        raw = match.group(0)
        token = raw.lower()
        if token.endswith("'s"):
            token = token[:-2]
        elif token.endswith("s'"):
            token = token[:-1]
        token = token.replace("'", "")
        if token:
            pairs.append((token, raw))
    return pairs


def quoted_phrases(query: str) -> list[str]:
    """Pull out "quoted phrases" so they can be required as literal matches."""
    folded = query.translate(_MATCH_TABLE)
    return [p.strip() for p in re.findall(r'"([^"]{2,200})"', folded) if p.strip()]


def collapse(text: str, limit: int | None = None) -> str:
    """One-line form of a passage, for compact display."""
    flat = " ".join(text.split())
    if limit is not None and len(flat) > limit:
        return flat[: limit - 1].rstrip() + "…"
    return flat


def snippet_around(text: str, start: int, end: int, context: int) -> tuple[str, int]:
    """Return a window of ``text`` around ``[start, end)`` snapped to word edges."""
    left = max(0, start - context)
    right = min(len(text), end + context)
    if left > 0:
        space = text.find(" ", left, start)
        if space != -1:
            left = space + 1
    if right < len(text):
        space = text.rfind(" ", end, right)
        if space != -1:
            right = space
    return text[left:right], left
