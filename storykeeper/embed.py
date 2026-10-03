"""The local embedding model.

One ONNX model, downloaded once, run on the CPU. After the first successful
load Storykeeper records that the model is present and sets ``HF_HUB_OFFLINE``
on every subsequent run, so the library cannot reach for the network even to
check whether there is a newer revision. That check is the only network call
this stack would otherwise make, and the whole promise of the project is that
there aren't any.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

from .config import EmbeddingConfig
from .errors import StorykeeperError

_MARKER = ".storykeeper-models.json"


def _marker_path(cache_dir: Path) -> Path:
    return cache_dir / _MARKER


def model_is_cached(cache_dir: Path, model: str) -> bool:
    """Has this exact model loaded successfully on this machine before?"""
    marker = _marker_path(cache_dir)
    if not marker.exists():
        return False
    try:
        return bool(json.loads(marker.read_text(encoding="utf-8")).get(model))
    except (OSError, ValueError):
        return False


def _record_cached(cache_dir: Path, model: str) -> None:
    marker = _marker_path(cache_dir)
    data: dict[str, bool] = {}
    if marker.exists():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    data[model] = True
    try:
        marker.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass  # a read-only models folder is not worth failing an index run over


class Embedder:
    """Lazily-loaded wrapper around fastembed's TextEmbedding."""

    def __init__(self, cfg: EmbeddingConfig, cache_dir: Path):
        self.cfg = cfg
        self.cache_dir = cache_dir
        self._model = None

    # -- loading ------------------------------------------------------------

    @property
    def will_download(self) -> bool:
        return not model_is_cached(self.cache_dir, self.cfg.model)

    def _prepare_environment(self) -> None:
        # Off by default in these libraries, but say so explicitly rather than
        # trusting a default that could change in a future release.
        # Assigned outright rather than defaulted, so a stray value already in
        # the environment cannot switch any of these back on.
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["DO_NOT_TRACK"] = "1"
        os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

        offline = self.cfg.offline
        if offline == "always" or (offline == "auto" and not self.will_download):
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"

    def load(self) -> None:
        if self._model is not None:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._prepare_environment()

        try:
            from fastembed import TextEmbedding
        except ImportError:
            raise StorykeeperError(
                "The search engine's Python packages are not installed.",
                "Run the setup script again:\n"
                "    Windows:      setup.cmd\n"
                "    Mac / Linux:  ./setup.sh",
            ) from None

        kwargs: dict[str, object] = {"cache_dir": str(self.cache_dir)}
        if self.cfg.threads > 0:
            kwargs["threads"] = self.cfg.threads

        try:
            self._model = TextEmbedding(self.cfg.model, **kwargs)
        except Exception as exc:  # fastembed raises a variety of types
            raise self._load_error(exc) from None

        _record_cached(self.cache_dir, self.cfg.model)

    def _load_error(self, exc: Exception) -> StorykeeperError:
        text = f"{type(exc).__name__}: {exc}"
        lowered = text.lower()
        # fastembed 0.8 says "Model X is not supported" for a name it does not
        # know, before any download is attempted.
        unknown = "not supported" in lowered or "unknown model" in lowered
        network = any(word in lowered for word in
                      ("connection", "network", "resolve", "timed out", "offline", "proxy", "ssl"))
        # fastembed 0.8 also swallows the real network error and reports only
        # that the model "could not be loaded from any source". On a first run,
        # when a download was the whole point, that means no internet.
        if not unknown and (network or (self.will_download and "from any source" in lowered)):
            return StorykeeperError(
                "The search model has not been downloaded yet, and the internet "
                "could not be reached to fetch it.",
                "This is the one and only time Storykeeper needs a connection - "
                "about 130 MB, once. Connect and run 'storykeeper index' again. "
                "After that it never goes online, even to check for updates.",
            )
        if unknown or "not found" in lowered:
            return StorykeeperError(
                f"There is no search model called '{self.cfg.model}'.",
                "Check the 'model' line under [embedding] in storykeeper.toml. "
                "The default is BAAI/bge-small-en-v1.5.",
            )
        return StorykeeperError(
            f"The search model could not be loaded.\n  {text}",
            "If this keeps happening, delete the 'models' folder and run "
            "'storykeeper index' again to fetch a clean copy.",
        )

    # -- embedding ----------------------------------------------------------

    def _to_matrix(self, vectors) -> np.ndarray:
        matrix = np.asarray(list(vectors), dtype=np.float32)
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.maximum(norms, 1e-8)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        """Embed documents. Returns an (n, dim) L2-normalised float32 matrix."""
        if not texts:
            return np.zeros((0, self.cfg.dim), dtype=np.float32)
        self.load()
        assert self._model is not None
        matrix = self._to_matrix(
            self._model.passage_embed(texts, batch_size=self.cfg.batch_size)
        )
        self._check_dim(matrix)
        return matrix

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a question. Returns a (dim,) L2-normalised float32 vector."""
        self.load()
        assert self._model is not None
        matrix = self._to_matrix(self._model.query_embed([text]))
        self._check_dim(matrix)
        return matrix[0]

    def _check_dim(self, matrix: np.ndarray) -> None:
        if matrix.shape[1] != self.cfg.dim:
            raise StorykeeperError(
                f"The model '{self.cfg.model}' produces {matrix.shape[1]}-number "
                f"vectors, but storykeeper.toml says {self.cfg.dim}.",
                f"Set dim = {matrix.shape[1]} under [embedding] in "
                f"storykeeper.toml, then run 'storykeeper index --rebuild'.",
            )
