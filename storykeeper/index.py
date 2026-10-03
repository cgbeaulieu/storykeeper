"""Building and storing the index, incrementally.

A writer works on their material every day. An indexer that re-reads two
hundred thousand words to pick up one edited chapter is one they will stop
running, and an index nobody runs is worse than no index at all - it answers
confidently out of last month's draft. So the unit of work here is the *file*, keyed on a hash of its
contents:

* **new** file          -> read, chunk, embed
* **edited** file       -> re-embed just that file
* **moved** file        -> the content hash still matches, so the vectors are
  kept and only the path and document type are rewritten
* **renamed** file      -> re-embedded, because the title is part of what was
  embedded
* **deleted** file      -> its chunks disappear from the index

The store is three flat files - a float32 matrix, a JSONL of chunk metadata,
and a manifest - plus the literal index from :mod:`storykeeper.lexicon`. At a
novelist's scale (tens of thousands of chunks, tens of megabytes) the whole thing is
rewritten on each run, which avoids tombstones, compaction and every class of
bug that comes with them.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .chunk import chunk_document
from .config import Config
from .embed import Embedder
from .errors import StorykeeperError
from .lexicon import build_lexicon, load_lexicon, save_lexicon
from .loaders import (
    CONTAINER_SUFFIXES,
    DocumentError,
    is_supported,
    load_document,
    pretty_title,
    unsupported_hint,
)

VECTORS_FILE = "vectors.f32"
META_FILE = "meta.jsonl"
MANIFEST_FILE = "manifest.json"
FORMAT_VERSION = 1

#: Files that are Storykeeper's own instructions to the writer, not the writer's
#: material. Indexing them would put "put your writing here" in search results.
_LIBRARY_DOCS = {"readme.md", "readme.txt", "read me.txt"}

_CHECKPOINT_EVERY = 25
_HASH_CHUNK = 1 << 20


@dataclass
class FileRecord:
    """One source file as the index knows it."""

    path: str        # posix-style, relative to the library folder
    hash: str
    size: int
    mtime: float
    doc_type: str
    title: str
    chunks: int = 0
    embed_sig: str = ""


@dataclass
class ScannedFile:
    path: Path
    relative: str
    hash: str
    size: int
    mtime: float
    doc_type: str
    title: str


@dataclass
class IndexReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    moved: list[tuple[str, str]] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: int = 0
    skipped: list[tuple[str, str, str]] = field(default_factory=list)
    chunks: int = 0
    embedded_chunks: int = 0
    seconds: float = 0.0
    rebuilt: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.moved or self.removed) or self.rebuilt


# ---------------------------------------------------------------------------
# Scanning the library
# ---------------------------------------------------------------------------


def hash_source(path: Path) -> tuple[str, int, float]:
    """Content hash for a file, or for every file inside a container folder."""
    digest = hashlib.sha256()
    if path.is_dir():
        size = 0
        mtime = 0.0
        for child in sorted(p for p in path.rglob("*") if p.is_file()):
            relative = child.relative_to(path).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            stat = child.stat()
            size += stat.st_size
            mtime = max(mtime, stat.st_mtime)
            with open(child, "rb") as fh:
                for block in iter(lambda: fh.read(_HASH_CHUNK), b""):
                    digest.update(block)
        return digest.hexdigest(), size, mtime

    stat = path.stat()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(_HASH_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest(), stat.st_size, stat.st_mtime


def doc_type_for(relative: Path, folders: dict[str, str]) -> str:
    """Work out what kind of material this is from the folder it sits in.

    The outermost matching folder wins, so ``characters/minor/kestrel.md`` is a
    character sheet and ``manuscript/characters/cut-scene.md`` is manuscript.
    """
    for part in relative.parts[:-1]:
        kind = folders.get(part.lower())
        if kind:
            return kind
    return "other"


def scan_library(cfg: Config, report: IndexReport) -> list[ScannedFile]:
    """Find everything indexable under the library folder."""
    root = cfg.library_dir
    if not root.exists():
        raise StorykeeperError(
            f"There is no library folder at {root}.",
            "Create it and put your writing inside, in subfolders like "
            "'manuscript' and 'characters'. See library/README.md.",
        )

    max_bytes = int(cfg.library.max_file_mb * 1024 * 1024)
    found: list[ScannedFile] = []

    for path in _walk(root, cfg.library.skip_hidden):
        relative_path = path.relative_to(root)
        relative = relative_path.as_posix()

        if len(relative_path.parts) == 1 and path.name.lower() in _LIBRARY_DOCS:
            continue  # Storykeeper's own note to the writer

        if not is_supported(path):
            hint = unsupported_hint(path)
            if hint:
                report.skipped.append((relative, hint[0], hint[1]))
            continue

        try:
            digest, size, mtime = hash_source(path)
        except OSError as exc:
            report.skipped.append((
                relative,
                f"Could not be read ({exc.strerror or exc}).",
                "It may be open in another program, or on a drive that is not "
                "connected. Close it and run 'storykeeper index' again.",
            ))
            continue

        if size > max_bytes:
            report.skipped.append((
                relative,
                f"Skipped because it is {size / 1024 / 1024:.0f} MB.",
                "Raise max_file_mb under [library] in storykeeper.toml if you "
                "really do want a file this large indexed.",
            ))
            continue

        found.append(
            ScannedFile(
                path=path,
                relative=relative,
                hash=digest,
                size=size,
                mtime=mtime,
                doc_type=doc_type_for(relative_path, cfg.library.doc_type_folders),
                title=pretty_title(path),
            )
        )

    found.sort(key=lambda f: f.relative)
    return found


def _walk(root: Path, skip_hidden: bool) -> Iterable[Path]:
    """Yield candidate files, treating container folders as single documents."""
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if skip_hidden and entry.name.startswith("."):
                continue
            if entry.is_dir():
                if entry.suffix.lower() in CONTAINER_SUFFIXES:
                    yield entry
                else:
                    stack.append(entry)
            elif entry.is_file():
                yield entry


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


@dataclass
class IndexStore:
    index_dir: Path
    dim: int
    embedding_model: str
    chunk_signature: str
    files: list[FileRecord] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    vectors: np.ndarray | None = None
    built_at: str = ""
    format: int = FORMAT_VERSION

    @property
    def chunk_count(self) -> int:
        return len(self.rows)

    def file_spans(self) -> dict[str, tuple[int, int]]:
        """Where each file's chunks live in the row/vector arrays."""
        spans: dict[str, tuple[int, int]] = {}
        cursor = 0
        for record in self.files:
            spans[record.path] = (cursor, cursor + record.chunks)
            cursor += record.chunks
        return spans


def index_exists(index_dir: Path) -> bool:
    return (index_dir / MANIFEST_FILE).exists()


def load_store(cfg: Config, *, require: bool = True) -> IndexStore | None:
    """Read the index from disk. Returns None (or raises) when there isn't one."""
    index_dir = cfg.index_dir
    manifest_path = index_dir / MANIFEST_FILE
    if not manifest_path.exists():
        if require:
            raise StorykeeperError(
                "Nothing has been indexed yet.",
                "Put your writing in the library folder and run:\n"
                "    storykeeper index",
            )
        return None

    try:
        return _read_store(index_dir, manifest_path)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise StorykeeperError(
            f"The index is damaged and could not be read ({exc}).",
            "Rebuild it from scratch - your writing is untouched:\n"
            "    storykeeper index --rebuild",
        ) from None


def _read_store(index_dir: Path, manifest_path: Path) -> IndexStore:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    store = IndexStore(
        index_dir=index_dir,
        dim=int(manifest.get("dim", 0)),
        embedding_model=manifest.get("embedding_model", ""),
        chunk_signature=manifest.get("chunk_signature", ""),
        built_at=manifest.get("built_at", ""),
        format=int(manifest.get("format", 0)),
        files=[FileRecord(**record) for record in manifest.get("files", [])],
    )

    rows: list[dict] = []
    meta_path = index_dir / META_FILE
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    store.rows = rows

    vectors_path = index_dir / VECTORS_FILE
    if vectors_path.exists() and store.dim:
        raw = np.fromfile(vectors_path, dtype=np.float32)
        if raw.size % store.dim == 0:
            store.vectors = raw.reshape(-1, store.dim)
    if store.vectors is None:
        store.vectors = np.zeros((0, store.dim or 1), dtype=np.float32)
    return store


def _store_is_consistent(store: IndexStore) -> bool:
    expected = sum(record.chunks for record in store.files)
    return (
        store.format == FORMAT_VERSION
        and expected == len(store.rows)
        and store.vectors is not None
        and store.vectors.shape[0] == len(store.rows)
    )


def save_store(store: IndexStore, *, rebuild_lexicon: bool = True) -> None:
    """Write all four index files, each replaced atomically."""
    try:
        _write_store(store, rebuild_lexicon=rebuild_lexicon)
    except OSError as exc:
        raise StorykeeperError(
            f"The index could not be saved ({exc}).",
            "Check the disk is not full. On Windows, a sync program such as "
            "OneDrive or a virus scanner can briefly lock files in the index "
            "folder - wait a moment and run the same command again. Your "
            "writing is untouched either way.",
        ) from None


def _write_store(store: IndexStore, *, rebuild_lexicon: bool) -> None:
    index_dir = store.index_dir
    index_dir.mkdir(parents=True, exist_ok=True)

    vectors = store.vectors if store.vectors is not None else np.zeros((0, store.dim), np.float32)
    vectors = np.ascontiguousarray(vectors, dtype=np.float32)

    vectors_tmp = index_dir / (VECTORS_FILE + ".tmp")
    with open(vectors_tmp, "wb") as fh:
        fh.write(vectors.tobytes())

    meta_tmp = index_dir / (META_FILE + ".tmp")
    with open(meta_tmp, "w", encoding="utf-8", newline="\n") as fh:
        for row in store.rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    manifest = {
        "format": FORMAT_VERSION,
        "embedding_model": store.embedding_model,
        "dim": store.dim,
        "chunk_signature": store.chunk_signature,
        "built_at": store.built_at or _now(),
        "chunk_count": len(store.rows),
        "file_count": len(store.files),
        "files": [asdict(record) for record in store.files],
    }
    manifest_tmp = index_dir / (MANIFEST_FILE + ".tmp")
    manifest_tmp.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")

    vectors_tmp.replace(index_dir / VECTORS_FILE)
    meta_tmp.replace(index_dir / META_FILE)
    manifest_tmp.replace(index_dir / MANIFEST_FILE)

    if rebuild_lexicon:
        save_lexicon(index_dir, build_lexicon([_match_text(row) for row in store.rows]))


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _match_text(row: dict) -> str:
    """What the literal index sees: the passage plus its title and section.

    The title matters. A character sheet's body often says "she" throughout,
    with the name appearing only in the heading, and a literal search for that
    name has to find it anyway.
    """
    return f"{row.get('title', '')}\n{row.get('section', '')}\n{row.get('text', '')}"


def embed_text(row: dict) -> str:
    """What the embedding model sees. Kept in step with :func:`_match_text`."""
    header = " - ".join(part for part in (row.get("title"), row.get("section")) if part)
    return f"{header}\n\n{row['text']}" if header else row["text"]


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def chunk_file(scanned: ScannedFile, cfg: Config, report: IndexReport) -> list[dict] | None:
    """Load and chunk one file into metadata rows. None means it was skipped."""
    try:
        documents = load_document(scanned.path)
    except DocumentError as exc:
        report.skipped.append((scanned.relative, exc.message, exc.hint))
        return None

    rows: list[dict] = []
    for document in documents:
        title = document.title or scanned.title
        for chunk in chunk_document(
            document.text,
            doc_type=scanned.doc_type,
            cfg=cfg.chunking,
            section_prefix=document.section_prefix,
        ):
            rows.append({
                "path": scanned.relative,
                "doc_type": scanned.doc_type,
                "title": title,
                "section": chunk.section,
                "start": chunk.start,
                "end": chunk.end,
                "text": chunk.text,
            })
    return rows


def build(
    cfg: Config,
    *,
    rebuild: bool = False,
    dry_run: bool = False,
    say: Callable[[str], None] = print,
    embedder: Embedder | None = None,
) -> IndexReport:
    """Bring the index up to date with the library. This is `storykeeper index`."""
    started = time.time()
    report = IndexReport(rebuilt=rebuild)

    scanned = scan_library(cfg, report)
    if not scanned and not index_exists(cfg.index_dir):
        raise StorykeeperError(
            f"There is nothing to index - {cfg.library_dir} has no readable files in it.",
            "Put your chapters and notes in there, in subfolders like "
            "'manuscript' and 'characters', then run 'storykeeper index' again.\n"
            "Storykeeper reads: " + ", ".join(sorted(s for s in _readable_suffixes())),
        )

    old = None if rebuild else load_store(cfg, require=False)
    if old is not None and not _store_is_consistent(old):
        say("The existing index was left half-written, so it is being rebuilt from scratch.")
        old = None
        report.rebuilt = True
    if old is not None and (
        old.embedding_model != cfg.embedding.model
        or old.dim != cfg.embedding.dim
        or old.chunk_signature != cfg.chunking.signature()
    ):
        say("Settings have changed since the last index, so everything is being re-read.")
        old = None
        report.rebuilt = True

    old_by_path: dict[str, FileRecord] = {}
    old_by_hash: dict[str, list[FileRecord]] = {}
    spans: dict[str, tuple[int, int]] = {}
    if old is not None:
        old_by_path = {record.path: record for record in old.files}
        for record in old.files:
            old_by_hash.setdefault(record.hash, []).append(record)
        spans = old.file_spans()

    live_paths = {item.relative for item in scanned}
    claimed: set[str] = set()

    reused: list[tuple[ScannedFile, FileRecord]] = []
    to_embed: list[ScannedFile] = []

    for item in scanned:
        previous = old_by_path.get(item.relative)
        if previous is not None and previous.hash == item.hash:
            if (previous.embed_sig or previous.title) == item.title:
                reused.append((item, previous))
                if previous.doc_type == item.doc_type and previous.title == item.title:
                    report.unchanged += 1
                else:
                    report.updated.append(item.relative)
                continue
            to_embed.append(item)
            report.updated.append(item.relative)
            continue

        donor = _find_donor(old_by_hash.get(item.hash, []), live_paths, claimed)
        if donor is not None and (donor.embed_sig or donor.title) == item.title:
            claimed.add(donor.path)
            reused.append((item, donor))
            report.moved.append((donor.path, item.relative))
            continue

        to_embed.append(item)
        if previous is not None:
            report.updated.append(item.relative)
        elif donor is not None:
            report.moved.append((donor.path, item.relative))
            claimed.add(donor.path)
        else:
            report.added.append(item.relative)

    for record in (old.files if old is not None else []):
        if record.path not in live_paths and record.path not in claimed:
            report.removed.append(record.path)

    if dry_run:
        report.seconds = time.time() - started
        report.chunks = old.chunk_count if old is not None else 0
        return report

    if old is None and not to_embed and not reused:
        raise StorykeeperError(
            f"There is nothing readable in {cfg.library_dir}.",
            "Storykeeper reads: " + ", ".join(sorted(_readable_suffixes())),
        )

    store = IndexStore(
        index_dir=cfg.index_dir,
        dim=cfg.embedding.dim,
        embedding_model=cfg.embedding.model,
        chunk_signature=cfg.chunking.signature(),
    )

    # Reused files go in first, so a checkpoint written part-way through a long
    # embedding run never loses vectors that were already paid for.
    kept_vectors: list[np.ndarray] = []
    for item, record in reused:
        start, end = spans[record.path]
        assert old is not None and old.vectors is not None
        rows = [dict(row) for row in old.rows[start:end]]
        for row in rows:
            row["path"] = item.relative
            row["doc_type"] = item.doc_type
            row["title"] = item.title
        store.rows.extend(rows)
        kept_vectors.append(old.vectors[start:end])
        store.files.append(
            FileRecord(
                path=item.relative, hash=item.hash, size=item.size, mtime=item.mtime,
                doc_type=item.doc_type, title=item.title, chunks=len(rows),
                embed_sig=record.embed_sig or record.title,
            )
        )
    store.vectors = (
        np.vstack(kept_vectors) if kept_vectors else np.zeros((0, store.dim), dtype=np.float32)
    )

    if to_embed:
        _embed_files(to_embed, store, cfg, report, say, embedder)
    elif report.changed:
        say("Nothing to re-read.")

    store.built_at = _now()
    report.chunks = store.chunk_count
    save_store(store)
    report.seconds = time.time() - started
    return report


def _find_donor(
    candidates: list[FileRecord], live_paths: set[str], claimed: set[str]
) -> FileRecord | None:
    """An indexed file with identical content whose old path is now gone."""
    for record in candidates:
        if record.path not in live_paths and record.path not in claimed:
            return record
    return None


def _embed_files(
    items: list[ScannedFile],
    store: IndexStore,
    cfg: Config,
    report: IndexReport,
    say: Callable[[str], None],
    embedder: Embedder | None = None,
) -> None:
    embedder = embedder or Embedder(cfg.embedding, cfg.model_cache_dir)
    if embedder.will_download:
        say("Downloading the search model (about 130 MB). This happens once.")

    total = len(items)
    say(f"Reading {total} file{'s' if total != 1 else ''}...")

    pending_vectors: list[np.ndarray] = [store.vectors] if store.vectors.size else []
    since_checkpoint = 0

    for number, item in enumerate(items, 1):
        rows = chunk_file(item, cfg, report)
        if rows is None:
            _forget(report, item.relative)
            continue
        if not rows:
            report.skipped.append((
                item.relative,
                "No text was found in it.",
                "If this file does have writing in it, it may be in a format "
                "Storykeeper reads badly. Try saving a copy as .docx or .txt.",
            ))
            _forget(report, item.relative)
            continue

        vectors = embedder.embed_passages([embed_text(row) for row in rows])
        store.rows.extend(rows)
        pending_vectors.append(vectors)
        store.files.append(
            FileRecord(
                path=item.relative, hash=item.hash, size=item.size, mtime=item.mtime,
                doc_type=item.doc_type, title=item.title, chunks=len(rows),
                embed_sig=item.title,
            )
        )
        report.embedded_chunks += len(rows)
        say(f"  [{number}/{total}] {item.relative}  ({len(rows)} passage"
            f"{'s' if len(rows) != 1 else ''})")

        since_checkpoint += 1
        if since_checkpoint >= _CHECKPOINT_EVERY and number < total:
            store.vectors = np.vstack(pending_vectors)
            pending_vectors = [store.vectors]
            store.built_at = _now()
            save_store(store, rebuild_lexicon=False)
            since_checkpoint = 0

    store.vectors = (
        np.vstack(pending_vectors) if pending_vectors
        else np.zeros((0, store.dim), dtype=np.float32)
    )


def _forget(report: IndexReport, relative: str) -> None:
    """A file we meant to index turned out to be unreadable - undo the tally."""
    if relative in report.added:
        report.added.remove(relative)
    if relative in report.updated:
        report.updated.remove(relative)
    report.moved = [pair for pair in report.moved if pair[1] != relative]


def _readable_suffixes() -> set[str]:
    from .loaders import supported_suffixes
    return set(supported_suffixes())


# ---------------------------------------------------------------------------
# Reading it back
# ---------------------------------------------------------------------------


def stale_summary(cfg: Config, store: IndexStore) -> str:
    """A one-line warning if the library has moved on, or "" if it hasn't.

    Deliberately cheap - modification times and sizes only, no hashing and no
    reading - because this runs before every literal search and must never be
    the slow part of a command that is supposed to feel instant.
    """
    known = {record.path: record for record in store.files}
    changed = 0
    added = 0
    try:
        seen: set[str] = set()
        for path in _walk(cfg.library_dir, cfg.library.skip_hidden):
            relative_path = path.relative_to(cfg.library_dir)
            relative = relative_path.as_posix()
            if not is_supported(path):
                continue
            if len(relative_path.parts) == 1 and path.name.lower() in _LIBRARY_DOCS:
                continue
            seen.add(relative)
            record = known.get(relative)
            if record is None:
                added += 1
            elif path.is_file():
                stat = path.stat()
                if stat.st_size != record.size or stat.st_mtime > record.mtime + 1:
                    changed += 1
        missing = len(set(known) - seen)
    except OSError:
        return ""

    if not (added or changed or missing):
        return ""
    parts = []
    if added:
        parts.append(f"{added} new")
    if changed:
        parts.append(f"{changed} changed")
    if missing:
        parts.append(f"{missing} no longer there")
    return (
        f"{', '.join(parts)} file(s) since the index was last built - "
        f"run 'storykeeper index' to include them."
    )


def load_for_search(cfg: Config):
    """Load the index and its literal companion, rebuilding the latter if stale."""
    store = load_store(cfg, require=True)
    assert store is not None
    if not store.rows:
        raise StorykeeperError(
            "The index is empty.",
            "Put your writing in the library folder and run 'storykeeper index'.",
        )
    if store.vectors is None or store.vectors.shape[0] != len(store.rows):
        raise StorykeeperError(
            "The index is damaged - it has a different number of passages than vectors.",
            "Rebuild it; your writing is untouched:\n    storykeeper index --rebuild",
        )
    if store.embedding_model != cfg.embedding.model:
        raise StorykeeperError(
            f"The index was built with '{store.embedding_model}' but "
            f"storykeeper.toml now says '{cfg.embedding.model}'.",
            "Run 'storykeeper index --rebuild' to rebuild it with the new model.",
        )

    lexicon = load_lexicon(cfg.index_dir, len(store.rows))
    if lexicon is None:
        lexicon = build_lexicon([_match_text(row) for row in store.rows])
        try:
            save_lexicon(cfg.index_dir, lexicon)
        except OSError:
            pass
    return store, lexicon
