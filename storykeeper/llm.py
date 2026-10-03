"""Talking to Ollama on localhost.

Deliberately thin: one HTTP session, two endpoints, and a lot of care about
error messages, because "Ollama isn't running" is by far the most common thing
that will go wrong on a writer's machine and a Python traceback is not an
answer.

The host itself is checked in :mod:`storykeeper.config` to be this computer, and
redirects are never followed, so a misconfigured or misbehaving server cannot
bounce the request somewhere else.

The session is created with ``trust_env=False``. That looks like a detail and
isn't: ``requests`` would otherwise honour ``HTTP_PROXY``/``HTTPS_PROXY`` from
the environment, and on a machine where those are set, a request to
``localhost:11434`` can be handed to an outside proxy. On this project that is
not a performance question, it is the whole promise of the tool.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from .config import LLMConfig
from .errors import StorykeeperError

_START_HINT = (
    "Start it and try again:\n"
    "  Windows / Mac: open the Ollama app from your applications\n"
    "  Any system:    run 'ollama serve' in a terminal and leave it open\n"
    "\n"
    "If you have not installed it yet, get it from https://ollama.com - it is "
    "free, and it is what runs the AI on your own computer instead of someone "
    "else's."
)


class Ollama:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._session = None

    @property
    def session(self):
        if self._session is None:
            try:
                import requests
            except ImportError:
                raise StorykeeperError(
                    "The 'requests' package is not installed.",
                    "Run the setup script again:\n"
                    "    Windows:      setup.cmd\n"
                    "    Mac / Linux:  ./setup.sh",
                ) from None
            session = requests.Session()
            # See the module docstring: never let a proxy env var capture
            # traffic that is supposed to stay on this machine.
            session.trust_env = False
            self._session = session
        return self._session

    def _url(self, path: str) -> str:
        return self.cfg.host.rstrip("/") + path

    # -- status -------------------------------------------------------------

    def installed_models(self, timeout: float = 5.0) -> list[str] | None:
        """Model names Ollama has locally, or None if Ollama is not answering."""
        session = self.session  # raises if requests itself is missing
        try:
            response = session.get(
                self._url("/api/tags"), timeout=timeout, allow_redirects=False
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            return None
        return sorted(entry.get("name", "") for entry in data.get("models", []))

    def check_ready(self) -> None:
        """Raise a useful error unless Ollama is up with the configured model."""
        models = self.installed_models()
        if models is None:
            raise StorykeeperError(
                f"Ollama is not running, so there is nothing to write the answer.\n"
                f"(Storykeeper looked for it at {self.cfg.host}.)",
                _START_HINT,
            )
        if not self._model_present(models):
            listed = "\n".join(f"    {name}" for name in models) if models else "    (none yet)"
            raise StorykeeperError(
                f"The AI model '{self.cfg.model}' is not installed on this computer.",
                f"Install it once with this command - it is a large download, "
                f"a few gigabytes, and it only happens once:\n\n"
                f"    ollama pull {self.cfg.model}\n\n"
                f"Models you already have:\n{listed}\n\n"
                f"You can also point Storykeeper at one of those instead, by "
                f"editing the 'model' line under [llm] in storykeeper.toml.",
            )

    def _model_present(self, models: list[str]) -> bool:
        wanted = self.cfg.model
        for name in models:
            if name == wanted:
                return True
            # "llama3.1" in the config should accept "llama3.1:8b" on disk.
            if ":" not in wanted and name.split(":")[0] == wanted:
                return True
        return False

    # -- generation ---------------------------------------------------------

    def stream_chat(self, messages: list[dict]) -> Iterator[str]:
        """Yield the answer as it is written. Raises StorykeeperError on failure."""
        import requests

        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "stream": True,
            "keep_alive": self.cfg.keep_alive,
            "options": {
                # Ollama's own default context is small. Retrieved passages plus
                # a question routinely run past it, and when they do Ollama
                # silently drops the oldest text rather than complaining - so
                # the model answers from half the evidence and sounds just as
                # sure. Setting this explicitly is not optional.
                "num_ctx": self.cfg.num_ctx,
                "temperature": self.cfg.temperature,
                "top_p": self.cfg.top_p,
            },
        }

        try:
            response = self.session.post(
                self._url("/api/chat"),
                json=payload,
                stream=True,
                timeout=(10, self.cfg.timeout_seconds),
                allow_redirects=False,
            )
        except requests.exceptions.ConnectionError:
            raise StorykeeperError(
                f"Ollama stopped answering at {self.cfg.host}.", _START_HINT
            ) from None
        except requests.exceptions.Timeout:
            raise StorykeeperError(
                "Ollama took too long to start answering.",
                "The model may still be loading into memory. Wait a moment and "
                "ask again - the first question after starting Ollama is always "
                "the slowest.",
            ) from None

        if response.status_code == 404:
            raise StorykeeperError(
                f"Ollama does not have the model '{self.cfg.model}'.",
                f"Install it once:\n\n    ollama pull {self.cfg.model}",
            )
        if response.status_code >= 400:
            raise StorykeeperError(
                f"Ollama returned an error ({response.status_code}): "
                f"{_error_text(response)}",
                "If this keeps happening, restart Ollama and try again.",
            )

        try:
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    packet = json.loads(line)
                except ValueError:
                    continue
                if packet.get("error"):
                    raise StorykeeperError(f"Ollama reported: {packet['error']}")
                piece = packet.get("message", {}).get("content", "")
                if piece:
                    yield piece
                if packet.get("done"):
                    break
        except requests.exceptions.ChunkedEncodingError:
            raise StorykeeperError(
                "The connection to Ollama dropped part-way through the answer.",
                "This usually means Ollama ran out of memory. Try a smaller "
                "model, or lower num_ctx under [llm] in storykeeper.toml.",
            ) from None
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
            # requests reports a read timeout mid-stream as a ConnectionError.
            raise StorykeeperError(
                f"The answer stopped part-way through. Either Ollama stopped, or "
                f"the answer took longer than {self.cfg.timeout_seconds} seconds.",
                "If Ollama is still running, this computer may simply be too "
                "slow for the model. Either raise timeout_seconds under [llm] in "
                "storykeeper.toml, or switch to a smaller model.",
            ) from None
        finally:
            response.close()


def _error_text(response) -> str:
    try:
        return str(response.json().get("error", response.text))[:300]
    except ValueError:
        return response.text[:300]
