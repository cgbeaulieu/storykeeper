"""Turning retrieved passages into an answer, with citations.

Three things the prompt has to enforce, because a small local model will not do
any of them on its own:

1. **Answer only from the passages.** A 7B model asked about a fantasy novel it
   has never read will cheerfully invent a plausible one.
2. **Cite every claim.** The citation is what makes the answer checkable, and
   checkability is the only reason to trust a tool like this.
3. **Keep the manuscript separate from the notes.** "Ilvar dies in chapter
   twenty" is true of the outline and false of the book, because chapter twenty
   is not written. Blurring those two is the single most damaging mistake this
   tool could make for someone still deciding what happens, so passages are
   labelled and the model is told the difference in as many words.

Context budgeting matters as much as the wording. Passages are trimmed to fit
inside ``num_ctx`` *before* they are sent, because Ollama's own behaviour when
the prompt is too long is to quietly drop the front of it - which would remove
the instructions above and leave the model answering from whatever survived.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from .config import Config
from .llm import Ollama
from .search import Hit

#: Rough English average for this family of tokenizers. Used only to keep the
#: prompt inside num_ctx, so an approximation with headroom is the right tool.
CHARS_PER_TOKEN = 3.6
#: Tokens held back for the system prompt, the question and the answer itself.
RESERVED_TOKENS = 1100

_KIND_LABELS = {
    "manuscript": "MANUSCRIPT (prose that is written, on the page)",
    "character": "NOTES - character sheet",
    "history": "NOTES - history and timeline",
    "culture": "NOTES - culture and worldbuilding",
    "location": "NOTES - place",
    "plot": "NOTES - plot outline (plans, not written prose)",
    "other": "NOTES - other material",
}

SYSTEM_PROMPT = """\
You are Storykeeper. You help a novelist search their own manuscript and notes.
You are reading passages from their unpublished book. Everything you say must
come from those passages.

Follow these rules exactly:

1. Answer only from the numbered passages you are given. If they do not contain
   the answer, say so in one sentence - "The passages I found don't say" - and
   then, if it helps, say what they do cover. Never fill a gap with invention,
   and never use anything you might know about other books.

2. Cite a passage number in square brackets after every claim, like this: [2].
   If a claim rests on two passages, cite both: [2][5].

3. Keep written prose and planning notes apart. Each passage is labelled.
   MANUSCRIPT passages are what is actually on the page. NOTES passages are the
   writer's plans, sheets and reference material, and may describe things not
   yet written, or that have since changed. If they disagree, say so plainly
   rather than choosing one - a contradiction between the outline and the draft
   is exactly the kind of thing the writer wants to be told about.

4. Use the writer's own names and terms. Do not rename anything, do not tidy
   spellings, and do not smooth over an inconsistency you notice.

5. Be brief and concrete. Quote short phrases from the passages where the exact
   wording matters. No preamble, no summary of what you are about to do.
"""


@dataclass
class Prompt:
    messages: list[dict]
    used: list[Hit]
    dropped: list[Hit] = field(default_factory=list)
    context_chars: int = 0

    @property
    def truncated(self) -> bool:
        return bool(self.dropped)


def context_budget(cfg: Config) -> int:
    """How many characters of passages will actually fit."""
    room = int((cfg.llm.num_ctx - RESERVED_TOKENS) * CHARS_PER_TOKEN)
    return max(1000, min(cfg.llm.max_context_chars, room))


def format_passages(hits: Sequence[Hit]) -> str:
    blocks = []
    for number, hit in enumerate(hits, 1):
        label = _KIND_LABELS.get(hit.doc_type, hit.doc_type)
        where = hit.section or hit.title
        header = f"[{number}] {label}\n    file: {hit.path}"
        if where:
            header += f"\n    section: {where}"
        blocks.append(f"{header}\n\n{hit.text.strip()}")
    return "\n\n----\n\n".join(blocks)


def build_prompt(
    cfg: Config,
    question: str,
    hits: Sequence[Hit],
    history: Sequence[dict] | None = None,
) -> Prompt:
    """Assemble the messages for one question, trimming to fit the context."""
    budget = context_budget(cfg)
    used: list[Hit] = []
    dropped: list[Hit] = []
    total = 0

    # Hits arrive best-first, so anything dropped is the weakest evidence.
    for hit in hits:
        cost = len(hit.text) + 120  # header and separator
        if total + cost > budget and used:
            dropped.append(hit)
            continue
        used.append(hit)
        total += cost

    if used:
        body = (
            "Here are the passages from the writer's own files that best match "
            "the question.\n\n"
            f"{format_passages(used)}\n\n"
            "----\n\n"
            f"QUESTION: {question}\n\n"
            "Answer from the passages above, citing each claim by its number."
        )
    else:
        body = (
            f"No passages in the writer's library matched this question.\n\n"
            f"QUESTION: {question}\n\n"
            "Say that nothing in their files covers this, in one sentence. Do "
            "not answer from your own knowledge."
        )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": body})
    return Prompt(messages=messages, used=used, dropped=dropped, context_chars=total)


def stream_answer(cfg: Config, prompt: Prompt) -> Iterator[str]:
    """Stream the model's answer. Ollama readiness is checked first."""
    client = Ollama(cfg.llm)
    client.check_ready()
    yield from client.stream_chat(prompt.messages)


def answer_question(
    cfg: Config,
    question: str,
    hits: Sequence[Hit],
    history: Sequence[dict] | None = None,
) -> tuple[Prompt, Iterator[str]]:
    prompt = build_prompt(cfg, question, hits, history)
    return prompt, stream_answer(cfg, prompt)
