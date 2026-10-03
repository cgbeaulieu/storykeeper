"""The interactive session.

Two things here that `ask` does not need.

**Follow-ups.** "What colour are her eyes?" retrieves nothing useful on its own -
"her" is not in the index. So when a question is short and leans on a pronoun,
the previous question is folded into the *search* text only. The model still
sees the question as it was typed, and the conversation still reads normally.

**A conversation the model can see.** Earlier turns are kept as messages so the
model can follow a thread, but they are capped and the passages from earlier
turns are not re-sent. On a local model, context is the scarcest thing there is,
and this turn's evidence matters more than last turn's.
"""

from __future__ import annotations

from collections.abc import Sequence

from .answer import answer_question
from .config import DOC_TYPES, Config
from .errors import StorykeeperError
from .llm import Ollama
from .render import fail, render_sources, rule, say
from .search import Searcher
from .textutil import COMMON_WORDS, query_terms

MAX_HISTORY_TURNS = 4
MAX_REMEMBERED_ANSWER = 700

_PRONOUNS = {
    "he", "him", "his", "she", "her", "hers", "they", "them", "their", "it",
    "its", "that", "this", "those", "these", "there",
}

_BANNER = """\
Storykeeper - ask about your own book. Everything stays on this computer.

  Type a question and press Enter.
  /sources   show or hide the passages behind each answer
  /k 12      change how many passages are retrieved
  /type      limit to one kind of material (e.g. /type character, /type all)
  /new       forget the conversation so far
  /help      this list
  /quit      leave (typing just  exit  works too)
"""


# Typed on their own, these leave the chat rather than being asked as a
# question - it is what people reach for first.
_BARE_QUIT_WORDS = {"exit", "quit", "bye", "q"}


class Session:
    def __init__(self, cfg: Config, searcher: Searcher, k: int | None,
                 doc_types: list[str] | None, show_sources: bool):
        self.cfg = cfg
        self.searcher = searcher
        self.k = k or cfg.retrieval.k
        self.doc_types = doc_types
        self.show_sources = show_sources
        self.history: list[dict] = []
        self.last_question = ""

    # -- retrieval -----------------------------------------------------------

    def search_text(self, question: str) -> str:
        """The text used for *searching*, which may borrow from the last turn."""
        if not self.last_question:
            return question
        tokens = [token for token, _ in query_terms(question)]
        if not tokens:
            return question
        leans_on_context = any(token in _PRONOUNS for token in tokens)
        has_own_subject = any(
            token not in COMMON_WORDS and token not in _PRONOUNS for token in tokens
        )
        if leans_on_context and (len(tokens) <= 8 or not has_own_subject):
            return f"{self.last_question} {question}"
        return question

    def remember(self, question: str, answer: str) -> None:
        self.last_question = question
        trimmed = answer.strip()
        if len(trimmed) > MAX_REMEMBERED_ANSWER:
            trimmed = trimmed[:MAX_REMEMBERED_ANSWER].rstrip() + " ..."
        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": trimmed})
        del self.history[: max(0, len(self.history) - MAX_HISTORY_TURNS * 2)]

    # -- one turn ------------------------------------------------------------

    def ask(self, question: str) -> None:
        hits = self.searcher.search(
            self.search_text(question), k=self.k, doc_types=self.doc_types
        )
        if not hits:
            say("Nothing in your library matched that.")
            return

        prompt, stream = answer_question(self.cfg, question, hits, self.history)
        say("")
        pieces: list[str] = []
        for piece in stream:
            print(piece, end="", flush=True)
            pieces.append(piece)
        say("")
        answer = "".join(pieces)
        self.remember(question, answer)

        if self.show_sources:
            say("")
            say(rule())
            say(render_sources(prompt.used, chars=self.cfg.retrieval.snippet_chars, scores=True))
        else:
            say("")
            for number, hit in enumerate(prompt.used, 1):
                where = hit.section or hit.title
                say(f"  [{number}] {hit.path}" + (f"  >  {where}" if where else ""))

    # -- commands ------------------------------------------------------------

    def command(self, line: str) -> bool:
        """Handle a /command. Returns False to end the session."""
        parts = line[1:].split()
        name = parts[0].lower() if parts else ""
        argument = " ".join(parts[1:]).strip()

        if name in ("quit", "exit", "q", "bye"):
            return False
        if name in ("help", "?"):
            say(_BANNER)
        elif name == "sources":
            self.show_sources = not self.show_sources
            say(f"Passages will {'now' if self.show_sources else 'no longer'} be shown.")
        elif name == "k":
            if argument.isdigit() and int(argument) > 0:
                self.k = int(argument)
                say(f"Retrieving {self.k} passages per question.")
            else:
                say(f"Currently retrieving {self.k}. Use, for example: /k 12")
        elif name == "type":
            self._set_type(argument)
        elif name in ("new", "reset", "clear"):
            self.history.clear()
            self.last_question = ""
            say("Starting fresh.")
        else:
            say(f"'/{name}' isn't a command. Type /help to see the list.")
        return True

    def _set_type(self, argument: str) -> None:
        if not argument:
            current = ", ".join(self.doc_types) if self.doc_types else "everything"
            say(f"Currently looking at: {current}")
            say(f"Choose from: {', '.join(DOC_TYPES)}, or 'all'.")
            return
        wanted = [word.strip().lower() for word in argument.replace(",", " ").split()]
        if "all" in wanted or "everything" in wanted:
            self.doc_types = None
            say("Looking at everything again.")
            return
        unknown = [word for word in wanted if word not in DOC_TYPES]
        if unknown:
            say(f"Don't know the kind '{unknown[0]}'. Choose from: {', '.join(DOC_TYPES)}.")
            return
        self.doc_types = wanted
        say(f"Now looking only at: {', '.join(wanted)}")


def run_chat(
    cfg: Config,
    *,
    k: int | None = None,
    doc_types: Sequence[str] | None = None,
    show_sources: bool = False,
) -> int:
    searcher = Searcher.open(cfg)
    Ollama(cfg.llm).check_ready()

    session = Session(cfg, searcher, k, list(doc_types) if doc_types else None, show_sources)

    say(_BANNER)
    say(f"{searcher.store.chunk_count:,} passages from {len(searcher.store.files)} "
        f"file(s), answered by {cfg.llm.model}.")
    if session.doc_types:
        say(f"Limited to: {', '.join(session.doc_types)}")
    say(rule())

    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            say("")
            break
        if not line:
            continue
        if line.lower() in _BARE_QUIT_WORDS:
            break
        if line.startswith("/"):
            if not session.command(line):
                break
            continue
        try:
            session.ask(line)
        except StorykeeperError as exc:
            fail(exc)
        except KeyboardInterrupt:
            say("")
            say("(stopped that answer)")

    say("Goodbye.")
    return 0
