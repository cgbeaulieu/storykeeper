"""Loading and validating storykeeper.toml.

Every setting has a default here, so the tool still runs if the config file is
missing, truncated, or half-edited. ``storykeeper.local.toml`` is overlaid on
top of ``storykeeper.toml`` key by key, so a personal override only has to name
the settings it actually changes.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .errors import StorykeeperError

if sys.version_info < (3, 11):  # pragma: no cover - checked first in __main__.py
    raise StorykeeperError(
        f"Storykeeper needs Python 3.11 or newer, but this is Python "
        f"{sys.version_info.major}.{sys.version_info.minor}.",
        "Install a current Python from https://www.python.org/downloads/ "
        "and run the setup script again.",
    )

import tomllib

CONFIG_NAME = "storykeeper.toml"
LOCAL_CONFIG_NAME = "storykeeper.local.toml"

#: The complete set of document kinds. Anything not matching a known folder
#: becomes "other", which is still fully searchable.
DOC_TYPES = ("manuscript", "character", "history", "culture", "location", "plot", "other")


@dataclass
class PathsConfig:
    library: str = "library"
    index: str = "index"


@dataclass
class LibraryConfig:
    doc_type_folders: dict[str, str] = field(
        default_factory=lambda: {
            "manuscript": "manuscript", "manuscripts": "manuscript", "book": "manuscript",
            "draft": "manuscript", "drafts": "manuscript", "chapters": "manuscript",
            "characters": "character", "character": "character", "cast": "character",
            "people": "character",
            "history": "history", "timeline": "history", "timelines": "history",
            "backstory": "history",
            "culture": "culture", "worldbuilding": "culture", "world": "culture",
            "religion": "culture", "language": "culture", "politics": "culture",
            "factions": "culture",
            "locations": "location", "location": "location", "places": "location",
            "geography": "location", "maps": "location",
            "plot": "plot", "outline": "plot", "outlines": "plot",
            "structure": "plot", "beats": "plot",
            "notes": "other", "other": "other",
        }
    )
    skip_hidden: bool = True
    max_file_mb: float = 50.0


@dataclass
class EmbeddingConfig:
    model: str = "BAAI/bge-small-en-v1.5"
    dim: int = 384
    threads: int = 0
    batch_size: int = 32
    cache_dir: str = "models"
    offline: str = "auto"


@dataclass
class ChunkingConfig:
    target_chars: int = 1000
    max_chars: int = 1800
    overlap_chars: int = 150
    min_chars: int = 0

    def signature(self) -> str:
        """Chunk settings fingerprint. If it changes, the index is rebuilt."""
        return (f"t{self.target_chars}-m{self.max_chars}"
                f"-o{self.overlap_chars}-n{self.min_chars}")


@dataclass
class RetrievalConfig:
    k: int = 8
    candidates: int = 200
    semantic_weight: float = 0.62
    literal_weight: float = 0.38
    proper_noun_boost: float = 0.30
    phrase_boost: float = 0.18
    max_per_file: int = 3
    snippet_chars: int = 700
    doc_type_bonus: dict[str, float] = field(
        default_factory=lambda: {t: 0.0 for t in DOC_TYPES} | {"other": -0.01}
    )
    intent_bonus: float = 0.07
    intent_cues: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class LLMConfig:
    model: str = "llama3.1:8b"
    host: str = "http://localhost:11434"
    num_ctx: int = 8192
    temperature: float = 0.2
    top_p: float = 0.9
    timeout_seconds: int = 600
    max_context_chars: int = 14000
    keep_alive: str = "10m"


@dataclass
class Config:
    root: Path
    config_path: Path | None = None
    paths: PathsConfig = field(default_factory=PathsConfig)
    library: LibraryConfig = field(default_factory=LibraryConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    warnings: list[str] = field(default_factory=list)

    # Resolved absolute paths -------------------------------------------------
    @property
    def library_dir(self) -> Path:
        return self._resolve(self.paths.library)

    @property
    def index_dir(self) -> Path:
        return self._resolve(self.paths.index)

    @property
    def model_cache_dir(self) -> Path:
        return self._resolve(self.embedding.cache_dir)

    def _resolve(self, value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else (self.root / p)


_SECTIONS = ("paths", "library", "embedding", "chunking", "retrieval", "llm")


def _apply_section(target: Any, data: dict, where: str, warnings: list[str]) -> None:
    known = {f.name for f in fields(target)}
    for key, value in data.items():
        if key not in known:
            warnings.append(f"[{where}] '{key}' is not a Storykeeper setting - ignored.")
            continue
        current = getattr(target, key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged = dict(current)
            merged.update(value)
            setattr(target, key, merged)
        elif isinstance(current, (int, float)) and isinstance(value, (int, float)) \
                and not isinstance(current, bool):
            setattr(target, key, type(current)(value))
        elif type(current) is type(value):
            setattr(target, key, value)
        else:
            warnings.append(
                f"[{where}] '{key}' should be a {type(current).__name__}, "
                f"but the file has a {type(value).__name__} - using the default."
            )


def _read_toml(path: Path) -> dict:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise StorykeeperError(
            f"{path.name} has a formatting error and could not be read:\n  {exc}",
            "Open it in a plain text editor and check the line it mentions. If "
            "you get stuck, delete the file - Storykeeper works fine without it.",
        ) from None
    except OSError as exc:
        raise StorykeeperError(f"Could not read {path}: {exc}") from None


def find_root(start: Path | None = None) -> Path:
    """Walk upward looking for storykeeper.toml; fall back to the repo folder."""
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / CONFIG_NAME).exists():
            return candidate
    return Path(__file__).resolve().parent.parent


def load_config(config_path: str | Path | None = None) -> Config:
    """Load configuration, applying storykeeper.local.toml over the top."""
    if config_path:
        main = Path(config_path).expanduser().resolve()
        if not main.exists():
            raise StorykeeperError(
                f"No config file at {main}.",
                "Check the path you passed to --config, or leave it off to use "
                "the storykeeper.toml that ships with the program.",
            )
        root = main.parent
    else:
        root = find_root()
        main = root / CONFIG_NAME

    cfg = Config(root=root, config_path=main if main.exists() else None)

    for path in (main, root / LOCAL_CONFIG_NAME):
        if not path.exists():
            continue
        data = _read_toml(path)
        for name in _SECTIONS:
            if name not in data:
                continue
            if not isinstance(data[name], dict):
                cfg.warnings.append(f"[{name}] in {path.name} is not a section - ignored.")
                continue
            _apply_section(getattr(cfg, name), data[name], name, cfg.warnings)

    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    r = cfg.retrieval
    total = r.semantic_weight + r.literal_weight
    if total <= 0:
        raise StorykeeperError(
            "semantic_weight and literal_weight in storykeeper.toml are both "
            "zero, so nothing can be ranked.",
            "Set them back to roughly 0.62 and 0.38.",
        )
    # Normalise so the blend is always a weighted average regardless of what was
    # typed in. Someone writing 2 and 1 clearly means "twice as much meaning".
    r.semantic_weight /= total
    r.literal_weight /= total

    c = cfg.chunking
    if c.max_chars < c.target_chars:
        cfg.warnings.append(
            "[chunking] max_chars is smaller than target_chars - raising it to match."
        )
        c.max_chars = c.target_chars
    if c.overlap_chars >= c.target_chars:
        cfg.warnings.append("[chunking] overlap_chars must be smaller than target_chars.")
        c.overlap_chars = max(0, c.target_chars // 4)

    r.k = max(1, r.k)
    r.candidates = max(r.candidates, r.k)
    r.max_per_file = max(1, r.max_per_file)

    if cfg.llm.num_ctx < 2048:
        cfg.warnings.append(
            "[llm] num_ctx is very small; retrieved passages will be truncated."
        )

    cfg.embedding.offline = str(cfg.embedding.offline).lower()
    if cfg.embedding.offline not in ("auto", "always", "never"):
        cfg.warnings.append("[embedding] offline must be auto, always or never - using auto.")
        cfg.embedding.offline = "auto"

    for key in list(r.intent_cues):
        if key not in DOC_TYPES:
            cfg.warnings.append(
                f"[retrieval.intent_cues] '{key}' is not one of "
                f"{', '.join(DOC_TYPES)} - ignored."
            )
            r.intent_cues.pop(key)
    # Folder names are matched in lower case, so the map's keys must be too -
    # otherwise "Cast List" = "character" would silently never match.
    folders = {}
    for name, kind in cfg.library.doc_type_folders.items():
        kind = str(kind).lower()
        if kind not in DOC_TYPES:
            cfg.warnings.append(
                f"[library.doc_type_folders] '{name}' = '{kind}' - the kind must be "
                f"one of {', '.join(DOC_TYPES)}. Ignored."
            )
            continue
        folders[str(name).lower()] = kind
    cfg.library.doc_type_folders = folders

    _require_local_host(cfg.llm.host)

    for key in list(r.doc_type_bonus):
        if key not in DOC_TYPES:
            cfg.warnings.append(f"[retrieval.doc_type_bonus] '{key}' is not a document type.")
            r.doc_type_bonus.pop(key)


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _require_local_host(host: str) -> None:
    """Refuse any Ollama address that is not this computer.

    The prompt sent to Ollama contains passages of the writer's own text. An
    address pointing anywhere else - a typo, a pasted example, a server on the
    network - would send that text off the machine, which is the one thing this
    tool exists not to do.
    """
    try:
        parts = urlsplit(host)
        scheme = parts.scheme
        hostname = (parts.hostname or "").lower()
        parts.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError:
        scheme = hostname = ""
    if scheme in ("http", "https") and (
        hostname in _LOCAL_HOSTS or hostname.startswith("127.")
    ):
        return
    raise StorykeeperError(
        f"The Ollama address in the settings, {host!r}, is not this computer.",
        "Storykeeper only ever talks to Ollama on your own machine, so that your "
        "writing never leaves it. Set host under [llm] back to:\n"
        '    host = "http://localhost:11434"',
    )
