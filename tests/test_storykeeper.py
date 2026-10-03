"""Tests for Storykeeper.

Written against ``unittest`` from the standard library rather than pytest, so
that checking the tool works needs nothing installed beyond what the tool
already needs. Run them with:

    python -m unittest discover -s tests -v

The embedding model is stubbed out throughout. That is not only for speed: the
most important behaviour in this codebase is that retrieval still finds an
invented proper noun *when the semantic model is unhelpful*, and the only way to
test that honestly is to make the semantic model actively unhelpful.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storykeeper.chunk import chunk_document, find_sections
from storykeeper.config import ChunkingConfig, Config, load_config
from storykeeper.errors import StorykeeperError
from storykeeper.index import build, doc_type_for, load_for_search, load_store
from storykeeper.lexicon import bm25, build_lexicon, presence_fraction
from storykeeper.loaders import DocumentError, load_document, rtf_to_text
from storykeeper.search import Searcher, find_literal
from storykeeper.textutil import (
    fold_preserving_offsets,
    normalize_for_match,
    query_terms,
    tokenize,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class StubEmbedder:
    """A deterministic stand-in for the ONNX model.

    Every vector is derived from a hash of the text, so two different passages
    are near-orthogonal and cosine similarity carries no real meaning. Anything
    that still retrieves correctly under this embedder is being retrieved by the
    literal half of the search, which is exactly what needs proving.
    """

    def __init__(self, dim: int = 384):
        self.dim = dim
        self.calls = 0

    def _vector(self, text: str) -> np.ndarray:
        rng = np.random.default_rng(abs(hash(text.strip()[:200])) % (2**32))
        vector = rng.standard_normal(self.dim).astype(np.float32)
        return vector / np.linalg.norm(vector)

    @property
    def will_download(self) -> bool:
        return False

    def embed_passages(self, texts):
        self.calls += len(texts)
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([self._vector(t) for t in texts])

    def embed_query(self, text):
        return self._vector(text)


class TempProject(unittest.TestCase):
    """A throwaway library + index folder with a config pointing at them."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="storykeeper-test-"))
        self.library = self.root / "library"
        self.library.mkdir()
        (self.root / "storykeeper.toml").write_text(
            '[paths]\nlibrary = "library"\nindex = "index"\n', encoding="utf-8"
        )
        self.cfg = load_config(self.root / "storykeeper.toml")
        self.embedder = StubEmbedder(self.cfg.embedding.dim)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, relative: str, text: str) -> Path:
        path = self.library / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def index(self, **kwargs):
        return build(self.cfg, say=lambda _: None, embedder=self.embedder, **kwargs)

    def searcher(self) -> Searcher:
        store, lexicon = load_for_search(self.cfg)
        searcher = Searcher(self.cfg, store, lexicon)
        searcher._embedder = self.embedder
        return searcher


# ---------------------------------------------------------------------------
# text handling
# ---------------------------------------------------------------------------


class TestTextUtil(unittest.TestCase):
    def test_curly_quotes_fold_for_matching(self):
        self.assertEqual(normalize_for_match("Don’t"), "don't")
        self.assertEqual(normalize_for_match("“yes”"), '"yes"')

    def test_possessives_collapse_to_the_name(self):
        self.assertEqual(tokenize("Maren's sister"), ["maren", "sister"])
        self.assertEqual(tokenize("the Glasswrights' hall"), ["the", "glasswrights", "hall"])

    def test_query_terms_keep_original_capitalisation(self):
        pairs = query_terms("Who is Kestrel?")
        self.assertEqual([t for t, _ in pairs], ["who", "is", "kestrel"])
        self.assertEqual(pairs[2][1], "Kestrel")

    def test_offset_preserving_fold_never_moves_a_character(self):
        # An ellipsis and a curly dash both fold, and the citation offsets that
        # depend on this must not slide.
        sample = "She waited… and waited—then left."
        folded = fold_preserving_offsets(sample)
        self.assertEqual(len(folded), len(sample))
        self.assertIn("-then", folded)


# ---------------------------------------------------------------------------
# chunking
# ---------------------------------------------------------------------------


class TestChunking(unittest.TestCase):
    cfg = ChunkingConfig()

    def test_chunks_are_exact_slices_of_the_source(self):
        text = "# One\n\n" + ("Some prose about the river. " * 60) + "\n\n# Two\n\nMore prose.\n"
        for chunk in chunk_document(text, doc_type="manuscript", cfg=self.cfg):
            self.assertEqual(chunk.text, text[chunk.start:chunk.end].strip("\n"))

    def test_headings_become_the_section_path(self):
        text = "# Maren Vesh\n\n## Appearance\n\nGrey eyes.\n"
        chunks = chunk_document(text, doc_type="character", cfg=self.cfg)
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].section.startswith("Maren Vesh"))

    def test_two_characters_never_share_a_chunk(self):
        """The failure this chunker exists to prevent."""
        text = (
            "Maren Vesh\n\n"
            "Grey eyes. Bad at lying. Wants the truth to be survivable.\n\n"
            "Kestrel Dunn\n\n"
            "Red hair under a cap. Nineteen. Runs the Winter Crossing.\n"
        )
        chunks = chunk_document(text, doc_type="character", cfg=self.cfg)
        self.assertEqual(len(chunks), 2)
        for chunk in chunks:
            has_maren = "Maren" in chunk.text
            has_kestrel = "Kestrel" in chunk.text
            self.assertFalse(has_maren and has_kestrel, f"entries merged: {chunk.text!r}")

    def test_sibling_sections_of_one_entity_do_merge(self):
        text = (
            "# Maren Vesh\n\n## Appearance\n\nGrey eyes.\n\n"
            "## Voice\n\nShort sentences.\n\n## Wants\n\nThe truth.\n"
        )
        chunks = chunk_document(text, doc_type="character", cfg=self.cfg)
        self.assertEqual(len(chunks), 1)
        self.assertIn("Grey eyes", chunks[0].text)
        self.assertIn("Short sentences", chunks[0].text)

    def test_scene_breaks_are_never_bridged(self):
        text = "# Chapter One\n\n" + "A. " * 40 + "\n\n* * *\n\n" + "B. " * 40 + "\n"
        chunks = chunk_document(text, doc_type="manuscript", cfg=self.cfg)
        self.assertEqual(len(chunks), 2)
        self.assertNotIn("B.", chunks[0].text)

    def test_all_caps_chapter_line_splits_a_plain_text_manuscript(self):
        text = "CHAPTER THREE\n\nSnow came early.\n\nCHAPTER FOUR\n\nThen it stopped.\n"
        sections = find_sections(text)
        titles = [s.path[0] for s in sections if s.path]
        self.assertEqual(titles, ["CHAPTER THREE", "CHAPTER FOUR"])

    def test_overlap_stays_inside_its_section(self):
        text = "# A\n\n" + ("alpha " * 400) + "\n\n# B\n\n" + ("beta " * 20) + "\n"
        chunks = chunk_document(text, doc_type="manuscript", cfg=self.cfg)
        for chunk in chunks:
            self.assertFalse("alpha" in chunk.text and "beta" in chunk.text)

    def test_oversized_paragraph_is_split_without_losing_text(self):
        body = " ".join(f"Sentence number {i}." for i in range(400))
        chunks = chunk_document("# Long\n\n" + body, doc_type="manuscript", cfg=self.cfg)
        self.assertGreater(len(chunks), 1)
        joined = " ".join(c.text for c in chunks)
        self.assertIn("Sentence number 399.", joined)


# ---------------------------------------------------------------------------
# loaders
# ---------------------------------------------------------------------------


class TestLoaders(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="storykeeper-loaders-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_markdown_frontmatter_is_dropped(self):
        path = self.dir / "note.md"
        path.write_text("---\ntags: [draft]\n---\n\nReal writing here.\n", encoding="utf-8")
        docs = load_document(path)
        self.assertNotIn("tags:", docs[0].text)
        self.assertIn("Real writing here.", docs[0].text)

    def test_damaged_pdf_is_skipped_with_a_reason_not_a_crash(self):
        path = self.dir / "notes.pdf"
        path.write_bytes(b"%PDF-1.4\nthis is not really a pdf\n")
        with self.assertRaises(DocumentError) as caught:
            load_document(path)
        self.assertTrue(caught.exception.hint)

    def test_rtf_control_words_and_escapes(self):
        source = (
            rb"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0\froman Times;}}"
            rb"{\*\generator Test;}"
            rb"\f0\fs24 Caf\'e9 at the crossing.\par " + rb"Second line.\par}"
        )
        text = rtf_to_text(source)
        self.assertIn("Café at the crossing.", text)
        self.assertIn("Second line.", text)
        self.assertNotIn("fonttbl", text)
        self.assertNotIn("generator", text)

    def test_docx_headings_become_markdown(self):
        path = self.dir / "chapter.docx"
        w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        body = (
            f'<?xml version="1.0"?><w:document xmlns:w="{w}"><w:body>'
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
            "<w:r><w:t>Chapter Four</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>The watch house was one room.</w:t></w:r></w:p>"
            "</w:body></w:document>"
        )
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", body)
        text = load_document(path)[0].text
        self.assertIn("# Chapter Four", text)
        self.assertIn("The watch house was one room.", text)

    def test_scrivener_uses_binder_titles_and_skips_trash(self):
        project = self.dir / "Book.scriv"
        (project / "Files" / "Data" / "AAA").mkdir(parents=True)
        (project / "Files" / "Data" / "ZZZ").mkdir(parents=True)
        (project / "Book.scrivx").write_text(
            '<?xml version="1.0"?><ScrivenerProject><Binder>'
            '<BinderItem UUID="TOP" Type="DraftFolder"><Title>Draft</Title><Children>'
            '<BinderItem UUID="AAA" Type="Text"><Title>The Low Bridge</Title></BinderItem>'
            "</Children></BinderItem>"
            '<BinderItem UUID="TRASH" Type="TrashFolder"><Title>Trash</Title><Children>'
            '<BinderItem UUID="ZZZ" Type="Text"><Title>Cut scene</Title></BinderItem>'
            "</Children></BinderItem>"
            "</Binder></ScrivenerProject>",
            encoding="utf-8",
        )
        (project / "Files" / "Data" / "AAA" / "content.rtf").write_bytes(
            rb"{\rtf1\ansi The pilings stood clear of the water.\par}"
        )
        (project / "Files" / "Data" / "ZZZ" / "content.rtf").write_bytes(
            rb"{\rtf1\ansi A scene that was cut.\par}"
        )
        docs = load_document(project)
        titles = [d.title for d in docs]
        self.assertIn("The Low Bridge", titles)
        self.assertNotIn("Cut scene", titles)
        self.assertIn("Draft", docs[0].section_prefix)


# ---------------------------------------------------------------------------
# the literal index
# ---------------------------------------------------------------------------


class TestLexicon(unittest.TestCase):
    def setUp(self) -> None:
        self.texts = [
            "The girl ran across the ice, a courier without a name.",
            "Kestrel Dunn is a courier who runs the Winter Crossing.",
            "The guild does not elect its master by any ordinary vote.",
            "A courier arrives at the door with a letter.",
        ]
        self.lexicon = build_lexicon(self.texts)

    def test_rare_name_outranks_a_common_word(self):
        scores = bm25(self.lexicon, ["kestrel"])
        self.assertEqual(int(np.argmax(scores)), 1)
        common = bm25(self.lexicon, ["courier"])
        self.assertGreater(scores.max(), common.max())

    def test_presence_fraction_counts_terms_not_repeats(self):
        fraction = presence_fraction(self.lexicon, ["kestrel", "courier"])
        self.assertAlmostEqual(float(fraction[1]), 1.0)
        self.assertAlmostEqual(float(fraction[0]), 0.5)
        self.assertAlmostEqual(float(fraction[2]), 0.0)


# ---------------------------------------------------------------------------
# incremental indexing
# ---------------------------------------------------------------------------


class TestIncrementalIndex(TempProject):
    def populate(self) -> None:
        self.write("manuscript/chapter-01.md", "# Chapter One\n\nThe river ran shallow.\n")
        self.write("characters/maren.md", "# Maren Vesh\n\nGrey eyes and a burn scar.\n")
        self.write("plot/outline.md", "# Outline\n\nIlvar dies in chapter twenty.\n")

    def test_first_run_indexes_everything(self):
        self.populate()
        report = self.index()
        self.assertEqual(len(report.added), 3)
        self.assertEqual(report.chunks, 3)
        self.assertEqual(self.embedder.calls, 3)

    def test_second_run_embeds_nothing(self):
        self.populate()
        self.index()
        self.embedder.calls = 0
        report = self.index()
        self.assertEqual(self.embedder.calls, 0)
        self.assertEqual(report.unchanged, 3)
        self.assertFalse(report.changed)

    def test_edit_re_embeds_only_that_file(self):
        self.populate()
        self.index()
        self.embedder.calls = 0
        self.write("characters/maren.md", "# Maren Vesh\n\nGrey eyes, and a scar she hides.\n")
        report = self.index()
        self.assertEqual(report.updated, ["characters/maren.md"])
        self.assertEqual(self.embedder.calls, 1)

    def test_move_between_folders_keeps_the_vectors(self):
        self.populate()
        self.index()
        self.embedder.calls = 0
        source = self.library / "plot" / "outline.md"
        target = self.library / "history" / "outline.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))

        report = self.index()
        self.assertEqual(report.moved, [("plot/outline.md", "history/outline.md")])
        self.assertEqual(self.embedder.calls, 0, "a move must not cost an embedding")

        store = load_store(self.cfg)
        row = next(r for r in store.rows if r["path"] == "history/outline.md")
        self.assertEqual(row["doc_type"], "history", "document type must follow the folder")

    def test_rename_re_embeds_because_the_title_changed(self):
        self.populate()
        self.index()
        self.embedder.calls = 0
        shutil.move(
            str(self.library / "characters" / "maren.md"),
            str(self.library / "characters" / "maren-vesh.md"),
        )
        report = self.index()
        self.assertEqual(report.moved, [("characters/maren.md", "characters/maren-vesh.md")])
        # The title is part of what gets embedded, so this one is not free.
        self.assertEqual(self.embedder.calls, 1)

    def test_delete_removes_the_passages(self):
        self.populate()
        self.index()
        (self.library / "plot" / "outline.md").unlink()
        report = self.index()
        self.assertEqual(report.removed, ["plot/outline.md"])
        store = load_store(self.cfg)
        self.assertEqual(store.chunk_count, 2)
        self.assertNotIn("plot/outline.md", [r["path"] for r in store.rows])

    def test_vectors_rows_and_manifest_stay_in_step(self):
        self.populate()
        self.index()
        self.write("culture/guild.md", "# Guild\n\nThe master packs the bag.\n")
        (self.library / "manuscript" / "chapter-01.md").unlink()
        self.index()
        store = load_store(self.cfg)
        self.assertEqual(store.vectors.shape[0], len(store.rows))
        self.assertEqual(sum(f.chunks for f in store.files), len(store.rows))

    def test_changing_chunk_settings_forces_a_rebuild(self):
        self.populate()
        self.index()
        self.cfg.chunking.target_chars = 400
        self.embedder.calls = 0
        report = self.index()
        self.assertTrue(report.rebuilt)
        self.assertEqual(self.embedder.calls, 3)

    def test_unreadable_file_is_reported_not_fatal(self):
        self.populate()
        (self.library / "manuscript" / "broken.docx").write_bytes(b"not a zip at all")
        report = self.index()
        self.assertTrue(any("broken.docx" in path for path, _, _ in report.skipped))
        self.assertEqual(report.chunks, 3)

    def test_library_readme_is_not_indexed(self):
        self.populate()
        self.write("README.md", "# Put your writing here\n\nDrop files into these folders.\n")
        report = self.index()
        self.assertEqual(len(report.added), 3)


class TestDocType(unittest.TestCase):
    def test_outermost_matching_folder_wins(self):
        folders = {"manuscript": "manuscript", "characters": "character"}
        self.assertEqual(
            doc_type_for(Path("manuscript/characters/cut-scene.md"), folders), "manuscript"
        )
        self.assertEqual(doc_type_for(Path("characters/minor/kestrel.md"), folders), "character")
        self.assertEqual(doc_type_for(Path("scraps/idea.md"), folders), "other")

    def test_folder_names_match_regardless_of_case(self):
        self.assertEqual(
            doc_type_for(Path("Characters/kestrel.md"), {"characters": "character"}),
            "character",
        )


# ---------------------------------------------------------------------------
# retrieval
# ---------------------------------------------------------------------------


class TestHybridSearch(TempProject):
    def setUp(self) -> None:
        super().setUp()
        self.write(
            "manuscript/chapter-01.md",
            "# Chapter One\n\nThe girl had not given a name. She ran back toward the "
            "ferry, a courier in a hurry, before anyone could ask her anything.\n",
        )
        self.write(
            "characters/cast.txt",
            "Kestrel Dunn\n\nA courier, nineteen, from somewhere south of Hollowmere. "
            "Red hair kept under a cap.\n\n"
            "Ilvar Thane\n\nMaster of the Glasswrights' Guild, sixty-one.\n",
        )
        self.write(
            "culture/guild.md",
            "# The Glasswrights' Guild\n\nThe sitting master names three candidates "
            "and the oldest journeyman strikes one name from the list.\n",
        )
        self.index()

    def test_invented_name_surfaces_even_when_meaning_search_is_useless(self):
        """The reason this project has a literal index at all."""
        hits = self.searcher().search("Who is Kestrel?", k=3)
        self.assertIn("Kestrel", hits[0].text)
        self.assertEqual(hits[0].doc_type, "character")

    def test_name_terms_recognise_a_rare_capitalised_word(self):
        searcher = self.searcher()
        self.assertIn("kestrel", searcher.name_terms("Who is Kestrel?"))
        self.assertNotIn("who", searcher.name_terms("Who is Kestrel?"))

    def test_document_type_filter_is_obeyed(self):
        hits = self.searcher().search("Kestrel", k=5, doc_types=["culture"])
        self.assertTrue(hits)
        self.assertTrue(all(h.doc_type == "culture" for h in hits))

    def test_filtering_to_an_absent_type_says_so(self):
        with self.assertRaises(StorykeeperError):
            self.searcher().search("Kestrel", doc_types=["history"])

    def test_no_semantic_mode_still_ranks(self):
        hits = self.searcher().search("Glasswrights", k=2, use_semantic=False)
        self.assertTrue(hits)
        self.assertTrue(any("Glasswrights" in h.text for h in hits))

    def test_one_file_cannot_take_every_slot(self):
        for number in range(6):
            self.write(
                "manuscript/long.md" if number == 0 else f"manuscript/other-{number}.md",
                "# Section\n\nKestrel crossed the ice again and again.\n",
            )
        self.write(
            "manuscript/long.md",
            "".join(f"# Scene {i}\n\nKestrel crossed the ice.\n\n" for i in range(8)),
        )
        self.index()
        self.cfg.retrieval.max_per_file = 2
        hits = self.searcher().search("Kestrel", k=6)
        from collections import Counter
        counts = Counter(h.path for h in hits)
        self.assertLessEqual(counts["manuscript/long.md"], 2)


class TestLiteralFind(TempProject):
    def test_overlapping_passages_do_not_double_count(self):
        body = " ".join(f"Filler sentence {i}." for i in range(120))
        self.write(
            "manuscript/long.md",
            f"# Chapter\n\n{body} The Ninefold Court met once. {body}\n",
        )
        self.index()
        store = load_store(self.cfg)
        matches = find_literal(store, "Ninefold Court")
        self.assertEqual(len(matches), 1)

    def test_search_is_case_and_typography_insensitive(self):
        self.write("manuscript/a.md", "# A\n\nShe said “don’t” and left.\n")
        self.index()
        store = load_store(self.cfg)
        self.assertEqual(len(find_literal(store, "DON'T")), 1)

    def test_offsets_point_at_the_real_position(self):
        self.write("manuscript/a.md", "# A\n\nThe Winter Crossing is open.\n")
        self.index()
        store = load_store(self.cfg)
        match = find_literal(store, "Winter Crossing")[0]
        source = (self.library / "manuscript" / "a.md").read_text(encoding="utf-8")
        self.assertEqual(source[match.offset:match.offset + match.length], "Winter Crossing")


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


class TestConfig(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="storykeeper-cfg-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_local_file_overrides_setting_by_setting(self):
        (self.root / "storykeeper.toml").write_text(
            '[llm]\nmodel = "llama3.1:8b"\nnum_ctx = 8192\n', encoding="utf-8"
        )
        (self.root / "storykeeper.local.toml").write_text(
            '[llm]\nmodel = "qwen2.5:14b"\n', encoding="utf-8"
        )
        cfg = load_config(self.root / "storykeeper.toml")
        self.assertEqual(cfg.llm.model, "qwen2.5:14b")
        self.assertEqual(cfg.llm.num_ctx, 8192, "untouched settings must survive")

    def test_weights_are_normalised_to_a_weighted_average(self):
        (self.root / "storykeeper.toml").write_text(
            "[retrieval]\nsemantic_weight = 2.0\nliteral_weight = 1.0\n", encoding="utf-8"
        )
        cfg = load_config(self.root / "storykeeper.toml")
        self.assertAlmostEqual(cfg.retrieval.semantic_weight, 2 / 3)
        self.assertAlmostEqual(cfg.retrieval.literal_weight, 1 / 3)

    def test_unknown_setting_warns_but_does_not_stop_anything(self):
        (self.root / "storykeeper.toml").write_text(
            '[llm]\nmodel = "x"\nnonsense = 3\n', encoding="utf-8"
        )
        cfg = load_config(self.root / "storykeeper.toml")
        self.assertEqual(cfg.llm.model, "x")
        self.assertTrue(any("nonsense" in w for w in cfg.warnings))

    def test_broken_toml_explains_itself(self):
        (self.root / "storykeeper.toml").write_text("[llm\nmodel =", encoding="utf-8")
        with self.assertRaises(StorykeeperError) as caught:
            load_config(self.root / "storykeeper.toml")
        self.assertIn("storykeeper.toml", caught.exception.message)
        self.assertTrue(caught.exception.hint)

    def test_ollama_host_must_be_this_computer(self):
        # The prompt carries passages of the writer's own text; an address
        # anywhere else would send it off the machine.
        for host in ("http://localhost:11434", "http://127.0.0.1:11434",
                     "http://[::1]:11434"):
            (self.root / "storykeeper.toml").write_text(
                f'[llm]\nhost = "{host}"\n', encoding="utf-8"
            )
            self.assertEqual(load_config(self.root / "storykeeper.toml").llm.host, host)
        for host in ("https://ollama.example.com", "http://192.168.1.20:11434",
                     "http://localhost.example.com:11434", "localhost:11434"):
            (self.root / "storykeeper.toml").write_text(
                f'[llm]\nhost = "{host}"\n', encoding="utf-8"
            )
            with self.assertRaises(StorykeeperError, msg=host):
                load_config(self.root / "storykeeper.toml")

    def test_custom_folder_names_are_case_insensitive_and_checked(self):
        (self.root / "storykeeper.toml").write_text(
            '[library]\ndoc_type_folders = { "Cast List" = "Character", '
            'Sketches = "sketch" }\n',
            encoding="utf-8",
        )
        cfg = load_config(self.root / "storykeeper.toml")
        folders = cfg.library.doc_type_folders
        self.assertEqual(folders["cast list"], "character")
        self.assertEqual(folders["characters"], "character", "defaults must survive")
        self.assertNotIn("sketches", folders)
        self.assertTrue(any("Sketches" in w for w in cfg.warnings))


# ---------------------------------------------------------------------------
# the prompt
# ---------------------------------------------------------------------------


class TestPrompt(unittest.TestCase):
    def _hit(self, doc_type: str, text: str):
        from storykeeper.search import Hit
        return Hit(
            row={"path": f"{doc_type}/x.md", "doc_type": doc_type, "title": "X",
                 "section": "S", "text": text},
            score=1.0, semantic=0.7, literal=1.0,
        )

    def test_passages_are_labelled_manuscript_or_notes(self):
        from storykeeper.answer import build_prompt
        cfg = Config(root=Path("."))
        prompt = build_prompt(
            cfg, "does Ilvar die?",
            [self._hit("plot", "Ilvar dies at the end of chapter twenty."),
             self._hit("manuscript", "Ilvar met her at the door.")],
        )
        body = prompt.messages[-1]["content"]
        self.assertIn("NOTES - plot outline", body)
        self.assertIn("MANUSCRIPT", body)

    def test_context_is_trimmed_to_fit_num_ctx(self):
        from storykeeper.answer import build_prompt
        cfg = Config(root=Path("."))
        cfg.llm.num_ctx = 2048
        cfg.llm.max_context_chars = 100_000
        hits = [self._hit("manuscript", "word " * 500) for _ in range(20)]
        prompt = build_prompt(cfg, "what happens?", hits)
        self.assertTrue(prompt.truncated)
        self.assertLess(len(prompt.used), len(hits))

    def test_no_passages_still_produces_a_safe_instruction(self):
        from storykeeper.answer import build_prompt
        prompt = build_prompt(Config(root=Path(".")), "anything?", [])
        self.assertIn("No passages", prompt.messages[-1]["content"])
        self.assertIn("Do not answer from your own knowledge",
                      prompt.messages[-1]["content"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
