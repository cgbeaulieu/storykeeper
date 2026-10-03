"""The literal half of retrieval: a small BM25 index over the same chunks.

This exists because of one specific weakness. ``bge-small`` is a 384-dimension
model trained on ordinary English, and invented proper nouns are exactly the
tokens it knows least about. Ask it for "Kestrel" and it will happily rank a
paragraph about a girl running across ice above the paragraph that actually says
*Kestrel Dunn*, because it understands "courier" far better than it understands
"Kestrel". In fiction that is backwards: the invented name is the most
information-dense word in the question.

BM25 has the opposite bias. Its IDF term makes a rare word the *most* valuable
thing a passage can contain, which is precisely the behaviour wanted here. The
two signals are blended in :mod:`storykeeper.search`.

The index is a plain CSR-style structure in a ``.npz`` plus a terms file - no
pickle, no database, nothing that can carry code across a version upgrade.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .textutil import TOKENIZER_VERSION, tokenize

LEXICON_FILE = "lexicon.npz"
TERMS_FILE = "lexicon-terms.txt"

# Standard BM25 constants. k1 controls how fast repeated terms stop helping; b
# controls how much a long passage is penalised for its length.
K1 = 1.5
B = 0.75


@dataclass
class Lexicon:
    terms: list[str]
    term_index: dict[str, int]
    ptr: np.ndarray        # (T+1,) int64  - start of each term's postings
    doc_ids: np.ndarray    # (P,)   int32  - chunk ids, ascending within a term
    tfs: np.ndarray        # (P,)   float32- term frequency in that chunk
    doc_len: np.ndarray    # (N,)   int32  - tokens per chunk
    df: np.ndarray         # (T,)   int32  - chunks containing each term
    n_docs: int
    avgdl: float

    def postings(self, term: str) -> tuple[np.ndarray, np.ndarray] | None:
        index = self.term_index.get(term)
        if index is None:
            return None
        lo, hi = int(self.ptr[index]), int(self.ptr[index + 1])
        return self.doc_ids[lo:hi], self.tfs[lo:hi]

    def document_frequency(self, term: str) -> int:
        index = self.term_index.get(term)
        return 0 if index is None else int(self.df[index])


def build_lexicon(texts: list[str]) -> Lexicon:
    """Tokenise every chunk and invert it."""
    postings: dict[str, dict[int, int]] = {}
    doc_len = np.zeros(len(texts), dtype=np.int32)

    for doc_id, text in enumerate(texts):
        tokens = tokenize(text)
        doc_len[doc_id] = len(tokens)
        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        for token, count in counts.items():
            postings.setdefault(token, {})[doc_id] = count

    terms = sorted(postings)
    term_index = {term: i for i, term in enumerate(terms)}
    total = sum(len(postings[t]) for t in terms)

    ptr = np.zeros(len(terms) + 1, dtype=np.int64)
    doc_ids = np.zeros(total, dtype=np.int32)
    tfs = np.zeros(total, dtype=np.float32)
    df = np.zeros(len(terms), dtype=np.int32)

    cursor = 0
    for i, term in enumerate(terms):
        entries = postings[term]
        ptr[i] = cursor
        df[i] = len(entries)
        for doc_id in sorted(entries):
            doc_ids[cursor] = doc_id
            tfs[cursor] = entries[doc_id]
            cursor += 1
    ptr[len(terms)] = cursor

    n_docs = len(texts)
    avgdl = float(doc_len.mean()) if n_docs else 0.0
    return Lexicon(terms, term_index, ptr, doc_ids, tfs, doc_len, df, n_docs, max(avgdl, 1.0))


def save_lexicon(index_dir: Path, lexicon: Lexicon) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    terms_tmp = index_dir / (TERMS_FILE + ".tmp")
    terms_tmp.write_text("\n".join(lexicon.terms), encoding="utf-8")

    npz_tmp = index_dir / (LEXICON_FILE + ".tmp")
    with open(npz_tmp, "wb") as fh:
        np.savez(
            fh,
            ptr=lexicon.ptr,
            doc_ids=lexicon.doc_ids,
            tfs=lexicon.tfs,
            doc_len=lexicon.doc_len,
            df=lexicon.df,
            avgdl=np.float64(lexicon.avgdl),
            tokenizer=np.int64(TOKENIZER_VERSION),
        )
    npz_tmp.replace(index_dir / LEXICON_FILE)
    terms_tmp.replace(index_dir / TERMS_FILE)


def load_lexicon(index_dir: Path, expected_docs: int) -> Lexicon | None:
    """Load the literal index, or None if it is missing or out of step."""
    npz_path = index_dir / LEXICON_FILE
    terms_path = index_dir / TERMS_FILE
    if not npz_path.exists() or not terms_path.exists():
        return None
    try:
        raw = terms_path.read_text(encoding="utf-8")
        terms = raw.split("\n") if raw else []
        with np.load(npz_path) as data:
            ptr = data["ptr"]
            doc_ids = data["doc_ids"]
            tfs = data["tfs"]
            doc_len = data["doc_len"]
            df = data["df"]
            avgdl = float(data["avgdl"])
            tokenizer = int(data["tokenizer"]) if "tokenizer" in data.files else 1
    except (OSError, ValueError, KeyError):
        return None

    if tokenizer != TOKENIZER_VERSION:
        return None  # words were split differently; the caller rebuilds it

    if len(doc_len) != expected_docs or len(terms) != len(df) or len(ptr) != len(terms) + 1:
        return None
    return Lexicon(
        terms=terms,
        term_index={term: i for i, term in enumerate(terms)},
        ptr=ptr,
        doc_ids=doc_ids,
        tfs=tfs,
        doc_len=doc_len,
        df=df,
        n_docs=expected_docs,
        avgdl=max(avgdl, 1.0),
    )


def bm25(lexicon: Lexicon, terms: list[str]) -> np.ndarray:
    """Score every chunk against these query terms."""
    scores = np.zeros(lexicon.n_docs, dtype=np.float32)
    if not lexicon.n_docs:
        return scores
    seen: set[str] = set()
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        found = lexicon.postings(term)
        if found is None:
            continue
        ids, tf = found
        df = float(lexicon.document_frequency(term))
        idf = math.log(1.0 + (lexicon.n_docs - df + 0.5) / (df + 0.5))
        lengths = lexicon.doc_len[ids].astype(np.float32)
        denominator = tf + K1 * (1.0 - B + B * lengths / lexicon.avgdl)
        scores[ids] += idf * (tf * (K1 + 1.0)) / np.maximum(denominator, 1e-8)
    return scores


def presence_fraction(lexicon: Lexicon, terms: list[str]) -> np.ndarray:
    """For each chunk, the fraction of these terms it literally contains.

    Used for the proper-noun boost. Unlike BM25 this does not care how often a
    name appears or how long the passage is - only whether the name is there at
    all, which is the question being asked when someone types "Kestrel".
    """
    scores = np.zeros(lexicon.n_docs, dtype=np.float32)
    unique = list(dict.fromkeys(terms))
    if not unique or not lexicon.n_docs:
        return scores
    for term in unique:
        found = lexicon.postings(term)
        if found is None:
            continue
        scores[found[0]] += 1.0
    return scores / len(unique)
