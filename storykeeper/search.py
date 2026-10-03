"""Hybrid retrieval: meaning and letters, blended.

Semantic search alone is the wrong tool for fiction. The embedding model has
never seen "Kestrel Dunn" and has no idea it is a person; it has seen "courier"
ten million times. Ask it who Kestrel is and it will confidently rank the
paragraph about a girl running across ice above the paragraph that says her
name, because that paragraph is *about* couriers in a way it can measure.

Literal search alone is the wrong tool too. Ask "how does the guild choose its
next master" and nothing in the notes uses those words - the passage says
"the sitting master names three candidates".

So both run on every query, over the same chunks, and their scores are blended:

    score = w_semantic x cosine + w_literal x bm25
            + proper-noun boost   (does the passage literally contain the
                                   unusual names in the question?)
            + phrase boost        (does it contain a "quoted phrase"?)
            + document-type nudge (does the question sound like it wants a
                                   character sheet rather than a chapter?)

The two main signals are min-max normalised per query before blending, because
cosine similarity lives in a narrow band around 0.7 and BM25 is unbounded;
without that, whichever number happens to be larger wins every time regardless
of the weights. The raw, interpretable values are kept on each hit so that
``--show-sources`` can show the real cosine rather than a rescaled one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from .config import Config
from .embed import Embedder
from .errors import StorykeeperError
from .index import IndexStore, _match_text, load_for_search
from .lexicon import Lexicon, bm25, presence_fraction
from .textutil import (
    COMMON_WORDS,
    fold_preserving_offsets,
    normalize_for_match,
    query_terms,
    quoted_phrases,
)


@dataclass
class Hit:
    """One retrieved passage, with its working shown."""

    row: dict
    score: float
    semantic: float          # raw cosine similarity, -1..1
    literal: float           # raw BM25
    names_matched: list[str] = field(default_factory=list)
    phrase_hit: bool = False
    type_bonus: float = 0.0

    @property
    def path(self) -> str:
        return self.row["path"]

    @property
    def doc_type(self) -> str:
        return self.row["doc_type"]

    @property
    def title(self) -> str:
        return self.row.get("title", "")

    @property
    def section(self) -> str:
        return self.row.get("section", "")

    @property
    def text(self) -> str:
        return self.row["text"]

    def citation(self) -> str:
        """How this passage is referred to in an answer."""
        where = self.section or self.title
        return f"{self.path} ({where})" if where else self.path


def _normalise(values: np.ndarray) -> np.ndarray:
    """Squash to 0..1 so two differently-scaled signals can be added."""
    if values.size == 0:
        return values
    low = float(values.min())
    high = float(values.max())
    if high - low < 1e-9:
        return np.zeros_like(values)
    return (values - low) / (high - low)


class Searcher:
    """Everything needed to answer a query, held in memory."""

    def __init__(self, cfg: Config, store: IndexStore, lexicon: Lexicon):
        self.cfg = cfg
        self.store = store
        self.lexicon = lexicon
        self._embedder: Embedder | None = None
        self._match_cache: list[str] | None = None

    @classmethod
    def open(cls, cfg: Config) -> "Searcher":
        store, lexicon = load_for_search(cfg)
        return cls(cfg, store, lexicon)

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = Embedder(self.cfg.embedding, self.cfg.model_cache_dir)
        return self._embedder

    @property
    def match_texts(self) -> list[str]:
        if self._match_cache is None:
            self._match_cache = [normalize_for_match(_match_text(r)) for r in self.store.rows]
        return self._match_cache

    # -- the parts of a query ------------------------------------------------

    def name_terms(self, query: str) -> list[str]:
        """The words in the question that look like invented proper nouns.

        Two independent pieces of evidence, either of which is enough:
        capitalisation that is not just the start of a sentence, and rarity in
        the corpus itself. Rarity is the better signal - a name the writer
        invented appears in a handful of chunks and nowhere else in the language - but it
        needs the name to be indexed already, so capitalisation covers the rest.
        """
        rare_cutoff = max(3, int(0.01 * self.lexicon.n_docs))
        found: list[str] = []
        for position, (token, as_typed) in enumerate(query_terms(query)):
            if token in COMMON_WORDS:
                continue
            frequency = self.lexicon.document_frequency(token)
            if frequency == 0:
                continue
            capitalised = as_typed[:1].isupper() and position > 0
            if capitalised or frequency <= rare_cutoff:
                found.append(token)
        return found

    def type_bonuses(self, query: str) -> dict[str, float]:
        """Small nudges from the shape of the question."""
        lowered = " " + normalize_for_match(query) + " "
        tokens = {token for token, _ in query_terms(query)}
        bonuses = dict(self.cfg.retrieval.doc_type_bonus)
        for doc_type, cues in self.cfg.retrieval.intent_cues.items():
            for cue in cues:
                cue = cue.lower()
                hit = (cue in lowered) if " " in cue else (cue in tokens)
                if hit:
                    bonuses[doc_type] = bonuses.get(doc_type, 0.0) + self.cfg.retrieval.intent_bonus
                    break
        return bonuses

    # -- the search itself ---------------------------------------------------

    def search(
        self,
        query: str,
        *,
        k: int | None = None,
        doc_types: Sequence[str] | None = None,
        use_semantic: bool = True,
    ) -> list[Hit]:
        query = query.strip()
        if not query:
            raise StorykeeperError("Ask a question, or search for some text.")

        retrieval = self.cfg.retrieval
        k = k or retrieval.k
        rows = self.store.rows
        count = len(rows)

        terms = [token for token, _ in query_terms(query)]
        literal_raw = bm25(self.lexicon, terms)

        if use_semantic:
            vector = self.embedder.embed_query(query)
            semantic_raw = (self.store.vectors @ vector).astype(np.float32)
        else:
            semantic_raw = np.zeros(count, dtype=np.float32)

        if use_semantic:
            score = (
                retrieval.semantic_weight * _normalise(semantic_raw)
                + retrieval.literal_weight * _normalise(literal_raw)
            )
        else:
            score = _normalise(literal_raw)

        names = self.name_terms(query)
        if names and retrieval.proper_noun_boost:
            score = score + retrieval.proper_noun_boost * presence_fraction(self.lexicon, names)

        bonuses = self.type_bonuses(query)
        if bonuses:
            nudge = np.array(
                [bonuses.get(row["doc_type"], 0.0) for row in rows], dtype=np.float32
            )
            score = score + nudge

        allowed = set(doc_types) if doc_types else None
        if allowed is not None:
            mask = np.array([row["doc_type"] in allowed for row in rows])
            if not mask.any():
                raise StorykeeperError(
                    f"Nothing in the index is of type {', '.join(sorted(allowed))}.",
                    "Check the folder names inside your library folder - the "
                    "folder a file sits in is what decides its type.",
                )
            score = np.where(mask, score, -np.inf)

        # Only the strongest candidates pay the cost of literal phrase checking.
        shortlist = self._shortlist(score, retrieval.candidates)
        phrases = quoted_phrases(query)
        if not phrases and len(terms) <= 5 and len(query) >= 4:
            phrases = [normalize_for_match(query)]
        phrase_hits: set[int] = set()
        if phrases and retrieval.phrase_boost:
            for index in shortlist:
                haystack = self.match_texts[index]
                if any(phrase in haystack for phrase in phrases):
                    phrase_hits.add(index)
                    score[index] += retrieval.phrase_boost

        order = sorted(shortlist, key=lambda i: float(score[i]), reverse=True)
        chosen = self._apply_file_cap(order, k, retrieval.max_per_file)

        name_set = set(names)
        hits: list[Hit] = []
        for index in chosen:
            row = rows[index]
            haystack = self.match_texts[index]
            hits.append(
                Hit(
                    row=row,
                    score=float(score[index]),
                    semantic=float(semantic_raw[index]),
                    literal=float(literal_raw[index]),
                    names_matched=[n for n in name_set if n in haystack],
                    phrase_hit=index in phrase_hits,
                    type_bonus=float(bonuses.get(row["doc_type"], 0.0)),
                )
            )
        return hits

    def _shortlist(self, score: np.ndarray, size: int) -> list[int]:
        finite = np.flatnonzero(np.isfinite(score))
        if finite.size <= size:
            return finite.tolist()
        subset = score[finite]
        top = np.argpartition(-subset, size - 1)[:size]
        return finite[top].tolist()

    def _apply_file_cap(self, order: list[int], k: int, cap: int) -> list[int]:
        """Keep one long file from filling every slot, without ever starving k.

        A manuscript chapter can easily be the ten best matches for a question
        about that chapter, which is true and useless - the answer is better
        when it also sees the character sheet and the outline. Passages over the
        cap are not thrown away, only deferred; if there is nothing else to fill
        the slots they come back.
        """
        rows = self.store.rows
        chosen: list[int] = []
        overflow: list[int] = []
        per_file: dict[str, int] = {}
        for index in order:
            path = rows[index]["path"]
            if per_file.get(path, 0) < cap:
                per_file[path] = per_file.get(path, 0) + 1
                chosen.append(index)
                if len(chosen) >= k:
                    return chosen
            else:
                overflow.append(index)
        for index in overflow:
            if len(chosen) >= k:
                break
            chosen.append(index)
        return chosen


# ---------------------------------------------------------------------------
# Literal search - no model, no embeddings, no LLM
# ---------------------------------------------------------------------------


@dataclass
class LiteralMatch:
    row: dict
    offset: int          # absolute position in the source document
    local: int           # position within this passage
    length: int


def find_literal(
    store: IndexStore,
    needle: str,
    *,
    doc_types: Sequence[str] | None = None,
    limit: int = 200,
) -> list[LiteralMatch]:
    """Every occurrence of a piece of text, in indexed order.

    Passages overlap slightly by design, so the same sentence can appear in two
    chunks. Matches are de-duplicated by their real position in the source file,
    which is what makes "how many times did I write this" answerable.
    """
    target = fold_preserving_offsets(needle)
    if not target.strip():
        raise StorykeeperError("Give some text to search for.")

    allowed = set(doc_types) if doc_types else None
    seen: set[tuple[str, int]] = set()
    matches: list[LiteralMatch] = []

    for row in store.rows:
        if allowed is not None and row["doc_type"] not in allowed:
            continue
        haystack = fold_preserving_offsets(row["text"])
        start = haystack.find(target)
        while start != -1:
            absolute = int(row.get("start", 0)) + start
            key = (row["path"], absolute)
            if key not in seen:
                seen.add(key)
                matches.append(
                    LiteralMatch(row=row, offset=absolute, local=start, length=len(target))
                )
                if len(matches) >= limit:
                    return matches
            start = haystack.find(target, start + 1)
    return matches
