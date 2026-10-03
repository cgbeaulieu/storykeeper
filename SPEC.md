# Storykeeper — design spec

A **fully local** question-answering system over a novelist's own material:
manuscript, character sheets, worldbuilding, history, culture, locations, plot
outlines. Nothing leaves the machine. No API keys, no accounts, no telemetry.

It was built for a writer who did not want their unpublished work transmitted to
any AI company. That constraint is not negotiable and shapes every decision
below.

## The hard constraint

**No network calls at query time. Ever.**

One-time downloads at setup are fine (the embedding model, ~130 MB; the Ollama
model, 4–9 GB). After that the machine can be air-gapped and everything still
works. Any design that phones home during indexing or answering is wrong, no
matter how much better the answers would be.

This rules out: Anthropic/OpenAI/Google APIs, hosted vector DBs (Pinecone,
Weaviate Cloud), LangSmith or any tracing service, and telemetry-by-default
libraries. Note that ChromaDB posts anonymous telemetry unless explicitly
disabled — one reason the design below avoids it entirely.

## Architecture

Two halves:

1. **Retrieval** — a local ONNX embedding model turns the writer's documents
   into vectors; a query gets embedded the same way, and cosine similarity ranks
   passages. CPU-only, fast, free.
2. **Generation** — a local LLM served by Ollama at `http://localhost:11434`
   reads the retrieved passages and answers in prose, citing which file each
   claim came from.

```
your files ──► loaders ──► chunker ──► embedder ──► index/
                                                       │
question ──► embedder ──► search (semantic + literal) ─┘
                              │
                       top-k passages
                              │
                    prompt ──► Ollama ──► answer + citations
```

### Component decisions

| Piece | Choice | Why |
|---|---|---|
| Embeddings | `fastembed` + `BAAI/bge-small-en-v1.5` (384-dim, ONNX) | CPU-only, no torch, no CUDA, ~130 MB one-time download, then fully offline. |
| Vector store | Flat files: `vectors.f32` + `meta.jsonl` + `manifest.json` | A novelist's corpus is ~10–30k chunks. Brute-force numpy dot product over 30k×384 floats takes single-digit milliseconds. FAISS/Chroma/Qdrant are unnecessary dependencies and a telemetry risk. |
| LLM runtime | Ollama HTTP API on `localhost:11434` | The standard for local models, one-line install on Windows/Mac/Linux, handles GPU offload automatically, stable REST API. Installed once. |
| LLM model | Configurable; chosen by hardware (table below) | Depends entirely on the machine. Must not be hardcoded. |
| Language | Python 3.11+, with `fastembed`, `numpy`, `requests`, `pypdf` | Keep the dependency list short enough that setup can't rot. |

### Model tiers by hardware

Check RAM and GPU/VRAM, then pick. Sizes below are approximate — check
`ollama.com/library` for current tags rather than trusting these verbatim.

- **No dedicated GPU, 16 GB RAM** — a 7–8B model at Q4. Usable but slow (a few
  tokens/sec on CPU). Serviceable for lookup, weak for analysis.
- **8–12 GB VRAM** — a 12–14B model at Q4. The sweet spot; noticeably better
  reasoning over the notes.
- **16–24 GB VRAM** — a 24–32B model at Q4. Genuinely good.
- **Under 16 GB RAM, no GPU** — a 3–4B model. Set expectations honestly: it will
  retrieve well and summarize poorly.

Context window matters as much as parameter count here — retrieved passages plus
a question can run 8–16k tokens. Prefer a long-context model and **set `num_ctx`
explicitly in the Ollama call**: Ollama defaults to a small context and will
silently truncate the retrieved passages otherwise. That single omission is the
easiest way to ship a system that feels broken for no visible reason.

## What makes fiction different

A generic local RAG over a fixed document set is not enough. Four things are
specific to a novelist's material:

1. **The corpus is alive.** The writer works on it every day. Re-indexing from
   scratch each time is unacceptable. The manifest must track a content hash per
   file and re-embed only what changed, including handling deleted and renamed
   files.
2. **Proper nouns carry the meaning.** Fiction lives on invented names —
   characters, houses, cities, artifacts. Small embedding models are mediocre at
   rare tokens; a semantic search for "Kestrel" may rank poorly against a chunk
   that says "the girl." **Retrieval must be hybrid**: blend cosine similarity
   with a literal keyword/BM25-style score so exact name matches always surface.
   This is the most important quality decision in the build.
3. **Document type matters.** "What color are Maren's eyes" should prefer the
   character sheet; "how does the northern campaign end" should prefer the
   manuscript. Tag every chunk with a `doc_type` (`manuscript`, `character`,
   `history`, `culture`, `location`, `plot`, `other`) inferred from its folder,
   and allow filtering and weighting by it.
4. **No OCR problem.** The files are born-digital, so there is no need to repair
   split or misrecognised words — but still ship a plain literal search
   command, because "find every time I wrote X" is a real need.

## Ingest

Loaders must handle whatever the writer actually uses. Build a pluggable loader
registry covering:

- `.txt`, `.md` — trivial
- `.docx` — unzip and parse `word/document.xml` with stdlib to avoid a
  dependency
- `.rtf` — Scrivener's native per-document storage format
- `.scriv` — a Scrivener project is a **folder**, not a file:
  `Files/Data/<uuid>/content.rtf` per document, with titles and hierarchy in
  `<name>.scrivx` (XML). Parse the `.scrivx` so chunks carry real document
  titles instead of UUIDs.
- `.odt`, `.pdf` — PDF needs a parser (`pypdf`); everything else is stdlib
- Google Docs — there is no local file. The writer has to export. Say so
  plainly rather than half-supporting it.

Preserve structure on the way in: chapter and scene boundaries in the manuscript,
one entity per chunk in character and location sheets. A chunk that splits a
character sheet mid-entry produces confidently wrong answers about the wrong
person.

## Chunking

Roughly 800–1200 characters with ~150 characters of overlap, but **prefer
structural boundaries over the character count** — split on headings, scene
breaks, and blank-line-delimited entries first, falling back to length-based
splitting only inside an oversized section. Every chunk stores: source path,
doc_type, title, section/chapter, and character offsets, so a citation can point
at something real.

## Answering

The prompt template must enforce three things, because a small local model will
happily invent otherwise:

1. **Answer only from the retrieved passages.** If they don't cover it, say so.
2. **Cite the source file and section for each claim.**
3. **Distinguish manuscript from notes.** What is on the page and what is in the
   plan for the page are different facts, and conflating them is exactly the
   error that would burn a writer.

Ship a visible `--show-sources` mode so the writer can always see the raw
retrieved passages behind an answer. Trust in this tool comes from making it
auditable, not from making it sound confident.

### Known limitation — state it plainly in the README

RAG retrieves the top-k relevant passages. It does **not** read the whole
manuscript. So it is strong at *recall* ("everything I've written about the
northern houses") and weak at *exhaustive audit* ("find every contradiction in
my timeline"). Continuity checking needs a different pass — chapter-by-chapter
sweeps against an extracted fact table — and is explicitly out of scope for v1.
Do not let the README imply otherwise; overpromising here is how the tool loses
a writer's trust in week two.

## CLI

```
storykeeper index                 # build/update the index (incremental)
storykeeper ask "question"        # one-shot question, prints answer + citations
storykeeper chat                  # interactive session, keeps conversation history
storykeeper find "literal text"   # exact search, no LLM, no embeddings
storykeeper status                # what's indexed, when, how many chunks, which model
```

Also ship a `--no-llm` flag on `ask` that prints only the retrieved passages.
Useful when the local model is slow, and it makes the retrieval layer
independently valuable even on weak hardware.

## Setup, from the writer's side

Assume the user is not a developer. The README must too. Target path:

1. Install Python (link, version, "check Add to PATH")
2. Install Ollama (link), then one command to pull the model
3. `git clone` — or download the ZIP; offer both
4. One setup command that creates the venv and installs dependencies
5. Drop files into `library/`, in subfolders by type
6. `storykeeper index`, then `storykeeper chat`

Provide `setup.cmd` for Windows and `setup.sh` for Mac/Linux covering step 4.
On Windows, also provide double-click wrappers for the everyday commands, so a
writer never has to open a terminal after setup. Every error the tool can
produce should say what to do about it — "Ollama isn't running, start it and try
again," not a traceback.

## Repo layout

```
storykeeper/
  README.md              writer-facing: install, use, troubleshoot
  SPEC.md                this file
  CLAUDE.md              working instructions for an AI assistant in this repo
  LICENSE
  requirements.txt
  setup.cmd / setup.sh   one-time setup
  finish-setup.cmd       Windows: download the configured model, check it all works
  index-my-writing.cmd   Windows: double-click to index
  ask-storykeeper.cmd    Windows: double-click to chat
  storykeeper.cmd / .sh  launchers that use the private .venv
  storykeeper.toml       config: library path, model name, k, weights
  storykeeper/           the package (cli, loaders, chunk, embed, index, search, llm, chat)
  tests/                 stdlib unittest suite
  library/               the writer's documents — GITIGNORED, never committed
  index/                 built index — GITIGNORED
```

**`library/` and `index/` are gitignored from the first commit.** The entire
point of this project is that the manuscript stays on the writer's machine;
committing it to a public GitHub repo would be a total failure of the brief.
Ship a `library/README.md` explaining the folder convention so the directory
survives cloning while staying empty.

---

# Build notes — v1

Everything above is the design. This section records what was actually built,
what was decided along the way, and what is still open.

## Status

v1 is complete and working end to end: `index`, `ask`, `chat`, `find`, `status`,
`--show-sources`, `--no-llm`, incremental re-indexing, hybrid retrieval, and the
Ollama answer loop. The test suite (`python -m unittest discover -s tests`)
covers loaders, chunking, offsets, incremental indexing and ranking.

Tested against a synthetic corpus generated for the purpose — ten files across
all seven document types, in `.md`, `.txt`, `.docx` and `.rtf`, plus a separate
Scrivener project fixture — and since then on one real writer's library on
Windows.

## Dependency telemetry review

CLAUDE.md requires that every dependency be checked for network behaviour and
the finding recorded here. The runtime list is `fastembed`, `numpy`, `requests`
and `pypdf`.

| Package | Finding | What was done about it |
|---|---|---|
| `numpy` | No network behaviour of any kind. | Nothing needed. |
| `requests` | No telemetry, but **honours `HTTP_PROXY`/`HTTPS_PROXY` from the environment** — on a machine where those are set, the localhost Ollama call would be handed to an outside proxy. | The Ollama session sets `trust_env = False` (`llm.py`). |
| `fastembed` | No telemetry of its own. Pulls in `huggingface_hub`, which sends a user-agent on downloads and contacts the Hub on load to check for a newer model revision. | `HF_HUB_DISABLE_TELEMETRY`, `DO_NOT_TRACK` and `HF_HUB_DISABLE_IMPLICIT_TOKEN` are set before import. After the first successful load, `models/.storykeeper-models.json` records that the model is present and `HF_HUB_OFFLINE=1` is set on every run after that, so even the revision check cannot happen (`embed.py`). |
| `onnxruntime` (via fastembed) | No network calls; runs the model locally. | Nothing needed. |
| `pypdf` | Pure Python, no dependencies of its own, no network behaviour. | Installed by default since the first real library turned out to contain PDFs. The loader still degrades with instructions, rather than crashing, if it is missing. |

ChromaDB was avoided as planned — it posts anonymous telemetry unless explicitly
disabled, and nothing here needs it.

**Verified behaviourally**, not merely by reading documentation: with
`HF_ENDPOINT` and all three proxy variables pointed at a dead port, both `index`
and `ask` complete normally. That exercises the embedding path and the Ollama
path together. The stronger check is available to any user at any time —
unplug the network and use it.

## Decisions taken during the build

**Hybrid scoring.** Cosine and BM25 are each min-max normalised per query before
blending at 0.62 / 0.38. Blending them raw does not work: cosine sits in a
narrow band near 0.7 while BM25 is unbounded, so whichever is numerically larger
wins regardless of the weights. On top of the blend sit three additive terms — a
proper-noun boost (0.30 × the fraction of the question's unusual names that the
passage literally contains), a phrase boost for quoted spans, and a small
document-type nudge from the shape of the question. The raw cosine and BM25 are
kept on every hit so `--show-sources` shows real numbers rather than rescaled
ones.

**"Unusual name" detection needs no list of names.** A query token counts as a
name if it is capitalised mid-sentence and is not a common word, *or* if its
document frequency in the corpus is at or below `max(3, 1% of chunks)`. Rarity
in the writer's own corpus is the better of the two signals — an invented name
appears in a handful of chunks and nowhere else in the language — and it is free
to compute from an index that already exists.

**Titles and section headings are embedded and indexed along with the passage.**
A character sheet's body says "she" throughout, with the name appearing only in
the heading. The embedded text is `title - section\n\nbody`, and the literal
index sees the same string. One consequence worth knowing: renaming a file
re-embeds it, because the title is part of what was embedded, while *moving* a
file between folders does not, because only its document type changed. Both are
handled and both are tested.

**The index is rewritten whole on every run** rather than patched in place. At a
novelist's scale that is tens of megabytes and takes milliseconds, and it
removes tombstones, compaction, and every bug that lives in them. Reused files
are written first, so a mid-run checkpoint can never discard vectors already
paid for.

**`min_chars` defaults to 0.** It was 40, which silently discarded any passage
shorter than that — including "Eyes: grey", which is exactly the kind of line
this tool exists to find. Short passages are now always kept. The only
unconditional filter is that a chunk must contain at least three alphanumeric
characters, which drops scene dividers and stray punctuation and nothing else.

**Chunk offsets are exact.** Every chunk is a slice of the source text and
carries the offsets to prove it, so a citation can be checked by hand. Two bugs
here were caught by the tests and fixed: stripping leading newlines without
moving the offset with them, and folding `…` to `...` — which changes a string's
length — before computing a match position. Literal search now uses a strictly
length-preserving fold, and a test asserts that every reported offset points at
the expected characters in the original file.

**Two deviations from the repo layout sketched above:**

1. The Unix launcher is `storykeeper.sh`, not `storykeeper`, because the latter
   collides with the package folder of the same name. On Windows,
   `.\storykeeper` resolves to `storykeeper.cmd` in both PowerShell and Command
   Prompt, whereas a bare `storykeeper` does not — the package folder shadows
   it. The README uses the forms that actually work on each system.
2. There is a `tests/` folder, written against `unittest` rather than pytest, so
   that verifying the tool needs nothing beyond what the tool already needs.

## Decided per install

These cannot be decided in the repo, because they depend on the writer's
machine and habits. CLAUDE.md walks an assistant through settling them.

- **Hardware → model.** The model is a config value with no hardcoding
  anywhere, and the README carries the tier table, but the shipped default
  (`llama3.1:8b`, `num_ctx = 8192`) is a guess at a typical 16 GB machine. It
  should be set to match the actual computer. The first real install — Windows,
  an 8 GB graphics card — used `mistral-nemo:12b`.
- **File formats.** Loaders exist for `.txt`, `.md`, `.docx`, `.rtf`, `.rtfd`,
  `.odt`, `.scriv` and `.pdf`. `.doc`, `.pages`, `.gdoc` and `.one` are
  recognised and refused with instructions for exporting. The Scrivener loader
  is built against the v3 `Files/Data/<UUID>/content.rtf` layout with a
  fallback to the v2 `Files/Docs/<ID>.rtf` layout, and has been tested against
  a fixture rather than a real project — test a real one early if the writer
  uses Scrivener.
- **Folder names.** The `doc_type_folders` map in `storykeeper.toml` assumes the
  suggested folder names. If the writer already has a scheme of their own,
  adding their folder names to that map is a one-line change and far better
  than asking them to reorganise around the tool.

## Still open

- **Real questions as the acceptance test.** The retrieval weights,
  `intent_cues` and `k` are all config values precisely so they can be tuned
  against the questions writers actually ask. Until a set of those is
  collected, they are set by judgement rather than evidence. Record them below,
  in the writer's own words, as they arrive.
- **Drafting in the writer's voice** is out of scope. It is a separate and much
  harder project on a local model.

### Acceptance questions

*None recorded yet.*

## Known limits of what was built

- Retrieval is top-k, so the recall-versus-audit distinction above holds exactly
  as written. The README states it plainly and does not hedge.
- The document-type nudge is a keyword heuristic, deliberately small (0.07) so
  that it breaks ties rather than overriding the search. It is the weakest part
  of the ranking and the first thing to revisit against real questions.
- Chat history is capped at four turns, and passages retrieved for earlier turns
  are not re-sent. On a local model, this turn's evidence is worth more than
  last turn's.
- In Word documents, tracked *insertions* are read and tracked *deletions* are
  not; comments are ignored. That is the right default, but worth knowing.
- `find` searches the index, not the files on disk, so it is only as current as
  the last `index` run. Both `find` and `status` say so when files have changed.
- In a character or location sheet *without headings*, an entry starts at a
  short title-case line after a blank line, or at a bare label such as
  `Maren Vesh:`. A line with text after its colon (`Height: Tall`) is read as an
  attribute of the entry above, so a name written as `Maren Vesh: the
  harbourmaster` does not start a new entry. Headings avoid the question.
- Reuse during indexing is keyed on each file's content hash, so a change to how
  files are read or chunked raises `FORMAT_VERSION` in `index.py`, and the next
  `index` re-reads and re-embeds everything once. On a large library that run
  takes minutes rather than seconds. A tokenizer change only rebuilds the
  literal index, which happens automatically on the next load.
