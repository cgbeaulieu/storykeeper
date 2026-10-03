"""The command line: index, ask, chat, find, status."""

from __future__ import annotations

import argparse
import json
import sys

from .config import DOC_TYPES, load_config
from .errors import StorykeeperError
from .render import fail, render_matches, render_sources, rule, say, setup_console, warn

PROGRAM = "storykeeper"

_EPILOG = """\
examples:
  storykeeper index                       read anything new or changed
  storykeeper ask "who is Kestrel?"       one question, one answer
  storykeeper ask -s "how does the guild choose a master?"
                                          ...and show the passages behind it
  storykeeper chat                        keep asking, with the thread kept
  storykeeper find "Ninefold Court"       every place you wrote those words
  storykeeper status                      what is indexed, and is it current

Your writing lives in the library folder and never leaves this computer.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Ask questions about your own book. Everything runs on this computer.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", metavar="FILE", help="use a different storykeeper.toml")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    subparsers = parser.add_subparsers(dest="command")

    index_parser = subparsers.add_parser(
        "index", help="read new and changed files into the search index"
    )
    index_parser.add_argument(
        "--rebuild", action="store_true",
        help="throw the index away and read everything again",
    )
    index_parser.add_argument(
        "--dry-run", action="store_true",
        help="say what would change, without changing it",
    )
    index_parser.set_defaults(handler=cmd_index)

    ask_parser = subparsers.add_parser("ask", help="ask one question")
    ask_parser.add_argument("question", nargs="+")
    _add_search_options(ask_parser)
    ask_parser.add_argument(
        "-s", "--show-sources", action="store_true",
        help="print the passages the answer was built from",
    )
    ask_parser.add_argument(
        "--no-llm", action="store_true",
        help="just show the passages - no AI, much faster",
    )
    ask_parser.add_argument("--json", action="store_true", help="machine-readable output")
    ask_parser.set_defaults(handler=cmd_ask)

    chat_parser = subparsers.add_parser("chat", help="ask several questions in a row")
    _add_search_options(chat_parser)
    chat_parser.add_argument(
        "-s", "--show-sources", action="store_true",
        help="show the passages behind every answer",
    )
    chat_parser.set_defaults(handler=cmd_chat)

    find_parser = subparsers.add_parser(
        "find", help="find text exactly as you wrote it - no AI involved"
    )
    find_parser.add_argument("text", nargs="+")
    find_parser.add_argument(
        "--type", dest="doc_types", action="append", choices=DOC_TYPES,
        help="only this kind of material (may be repeated)",
    )
    find_parser.add_argument(
        "-C", "--context", type=int, default=70, help="characters of context to show",
    )
    find_parser.add_argument("--limit", type=int, default=200, help="stop after this many")
    find_parser.add_argument("--files", action="store_true", help="list matching files only")
    find_parser.set_defaults(handler=cmd_find)

    status_parser = subparsers.add_parser("status", help="what is indexed, and is it up to date")
    status_parser.add_argument("--json", action="store_true", help="machine-readable output")
    status_parser.set_defaults(handler=cmd_status)

    return parser


def _add_search_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-k", type=int, default=None, help="how many passages to retrieve")
    parser.add_argument(
        "--type", dest="doc_types", action="append", choices=DOC_TYPES,
        help="only look at this kind of material (may be repeated)",
    )
    parser.add_argument("--model", help="use a different Ollama model just this once")


# ---------------------------------------------------------------------------
# index
# ---------------------------------------------------------------------------


def cmd_index(args, cfg) -> int:
    from .index import build

    report = build(cfg, rebuild=args.rebuild, dry_run=args.dry_run, say=say)

    if args.dry_run:
        say("")
        say("This is a dry run - nothing was changed.")
    say("")
    if report.added:
        say(f"  new files:      {len(report.added)}")
    if report.updated:
        say(f"  changed files:  {len(report.updated)}")
    for old, new in report.moved:
        say(f"  moved:          {old} -> {new}")
    for path in report.removed:
        say(f"  removed:        {path}")
    if report.unchanged:
        say(f"  untouched:      {report.unchanged}")

    if report.skipped:
        say("")
        say(f"{len(report.skipped)} file(s) were skipped:")
        for path, reason, hint in report.skipped:
            say(f"  {path}")
            say(f"      {reason}")
            if hint:
                for line in hint.split("\n"):
                    say(f"      {line}")

    if not args.dry_run:
        say("")
        if not report.changed and not report.skipped:
            say(f"Already up to date - {report.chunks:,} passages indexed.")
        else:
            say(f"Done. {report.chunks:,} passages indexed in {report.seconds:.1f} seconds.")
        say("")
        say('Now try:  storykeeper ask "what have I written about ..."')
    return 0


# ---------------------------------------------------------------------------
# ask
# ---------------------------------------------------------------------------


def cmd_ask(args, cfg) -> int:
    from .answer import answer_question, build_prompt
    from .search import Searcher

    question = " ".join(args.question).strip()
    if args.model:
        cfg.llm.model = args.model

    searcher = Searcher.open(cfg)
    hits = searcher.search(question, k=args.k, doc_types=args.doc_types)

    if args.json:
        prompt = build_prompt(cfg, question, hits)
        print(json.dumps(_ask_payload(question, hits, prompt), ensure_ascii=False, indent=2))
        return 0

    if not hits:
        say("Nothing in your library matched that.")
        say("")
        say("If you have written about it recently, run 'storykeeper index' first.")
        return 1

    if args.no_llm:
        say(render_sources(
            hits, chars=cfg.retrieval.snippet_chars, scores=True,
            heading="Passages that matched",
        ))
        return 0

    prompt, stream = answer_question(cfg, question, hits)
    if prompt.truncated:
        warn(
            f"{len(prompt.dropped)} of {len(hits)} passages did not fit and were "
            f"left out. Raise num_ctx under [llm] in storykeeper.toml to fit more."
        )
    say("")
    written = _stream_to_console(stream)
    say("")

    if args.show_sources:
        say("")
        say(rule())
        say(render_sources(prompt.used, chars=cfg.retrieval.snippet_chars, scores=True))
    elif written:
        say("")
        say(_short_source_list(prompt.used))
    return 0


def _stream_to_console(stream) -> bool:
    wrote = False
    for piece in stream:
        sys.stdout.write(piece)
        sys.stdout.flush()
        wrote = True
    return wrote


def _short_source_list(hits) -> str:
    lines = ["Sources:"]
    for number, hit in enumerate(hits, 1):
        where = hit.section or hit.title
        lines.append(f"  [{number}] {hit.path}" + (f"  >  {where}" if where else ""))
    lines.append("")
    lines.append("Add -s to see the passages themselves.")
    return "\n".join(lines)


def _ask_payload(question, hits, prompt) -> dict:
    return {
        "question": question,
        "passages": [
            {
                "n": number,
                "path": hit.path,
                "doc_type": hit.doc_type,
                "title": hit.title,
                "section": hit.section,
                "start": hit.row.get("start"),
                "end": hit.row.get("end"),
                "score": round(hit.score, 4),
                "semantic": round(hit.semantic, 4),
                "literal": round(hit.literal, 4),
                "names_matched": sorted(hit.names_matched),
                "text": hit.text,
                "used": hit in prompt.used,
            }
            for number, hit in enumerate(hits, 1)
        ],
    }


# ---------------------------------------------------------------------------
# chat / find / status
# ---------------------------------------------------------------------------


def cmd_chat(args, cfg) -> int:
    from .chat import run_chat

    if args.model:
        cfg.llm.model = args.model
    return run_chat(cfg, k=args.k, doc_types=args.doc_types, show_sources=args.show_sources)


def cmd_find(args, cfg) -> int:
    from .index import load_store, stale_summary
    from .search import find_literal

    needle = " ".join(args.text)
    store = load_store(cfg, require=True)
    assert store is not None

    # "Find every time I wrote X" is a question about completeness, so a stale
    # index is not a detail - it is the difference between a right answer and a
    # confidently wrong one.
    stale = stale_summary(cfg, store)
    if stale:
        warn(stale)

    matches = find_literal(store, needle, doc_types=args.doc_types, limit=args.limit)

    if not matches:
        say(f'"{needle}" does not appear anywhere in your indexed writing.')
        say("")
        say("If you wrote it since the last index, run 'storykeeper index' first.")
        return 1

    files = sorted({match.row["path"] for match in matches})
    if args.files:
        for path in files:
            say(path)
        return 0

    say(render_matches(matches, needle, args.context))
    say("")
    plural = "s" if len(matches) != 1 else ""
    say(f'{len(matches)} occurrence{plural} of "{needle}" '
        f"in {len(files)} file{'s' if len(files) != 1 else ''}.")
    if len(matches) >= args.limit:
        say(f"(Stopped at {args.limit}. Use --limit to see more.)")
    return 0


def cmd_status(args, cfg) -> int:
    from .embed import model_is_cached
    from .index import IndexReport, index_exists, load_store, scan_library
    from .llm import Ollama

    report = IndexReport()
    store = load_store(cfg, require=False)
    scanned = []
    scan_error = None
    try:
        scanned = scan_library(cfg, report)
    except StorykeeperError as exc:
        scan_error = exc.message

    known = {record.path: record.hash for record in (store.files if store else [])}
    live = {item.relative: item.hash for item in scanned}
    new = sorted(set(live) - set(known))
    changed = sorted(p for p in set(live) & set(known) if live[p] != known[p])
    gone = sorted(set(known) - set(live))

    ollama = Ollama(cfg.llm)
    installed = ollama.installed_models()
    model_ready = installed is not None and ollama._model_present(installed)

    by_type: dict[str, int] = {}
    for row in (store.rows if store else []):
        by_type[row["doc_type"]] = by_type.get(row["doc_type"], 0) + 1

    if args.json:
        print(json.dumps({
            "library": str(cfg.library_dir),
            "index": str(cfg.index_dir),
            "indexed": index_exists(cfg.index_dir),
            "built_at": store.built_at if store else None,
            "files": len(store.files) if store else 0,
            "passages": store.chunk_count if store else 0,
            "by_doc_type": by_type,
            "embedding_model": cfg.embedding.model,
            "embedding_model_downloaded": model_is_cached(
                cfg.model_cache_dir, cfg.embedding.model),
            "llm_model": cfg.llm.model,
            "llm_num_ctx": cfg.llm.num_ctx,
            "ollama_running": installed is not None,
            "ollama_models": installed or [],
            "llm_model_installed": model_ready,
            "new_files": new,
            "changed_files": changed,
            "missing_files": gone,
            "skipped": [{"path": p, "reason": r} for p, r, _ in report.skipped],
        }, ensure_ascii=False, indent=2))
        return 0

    say("Storykeeper")
    say(rule())
    say(f"  library folder    {cfg.library_dir}")
    say(f"  index folder      {cfg.index_dir}")
    if cfg.config_path:
        say(f"  settings          {cfg.config_path}")
    say("")

    if store is None:
        say("  Nothing has been indexed yet. Run:  storykeeper index")
    else:
        say(f"  indexed           {len(store.files)} file(s), "
            f"{store.chunk_count:,} passage(s)")
        say(f"  last updated      {store.built_at or 'unknown'}")
        if by_type:
            spread = ", ".join(f"{name} {count}" for name, count in sorted(by_type.items()))
            say(f"  by kind           {spread}")
    say("")

    if scan_error:
        say(f"  library           {scan_error}")
    elif new or changed or gone:
        say("  NOT UP TO DATE - run 'storykeeper index'")
        if new:
            say(f"      {len(new)} new file(s):     " + ", ".join(new[:4])
                + (" ..." if len(new) > 4 else ""))
        if changed:
            say(f"      {len(changed)} changed file(s): " + ", ".join(changed[:4])
                + (" ..." if len(changed) > 4 else ""))
        if gone:
            say(f"      {len(gone)} file(s) no longer there: " + ", ".join(gone[:4])
                + (" ..." if len(gone) > 4 else ""))
    elif store is not None:
        say("  up to date        yes")
    say("")

    downloaded = model_is_cached(cfg.model_cache_dir, cfg.embedding.model)
    say(f"  search model      {cfg.embedding.model}"
        f"{'' if downloaded else '   (not downloaded yet)'}")
    say(f"  writing model     {cfg.llm.model}   (context {cfg.llm.num_ctx:,})")
    if installed is None:
        say(f"  Ollama            not running at {cfg.llm.host}")
        say("                    Start the Ollama app, or run 'ollama serve'.")
    elif not model_ready:
        say(f"  Ollama            running, but '{cfg.llm.model}' is not installed")
        say(f"                    Install it with:  ollama pull {cfg.llm.model}")
    else:
        say("  Ollama            running, model ready")

    if report.skipped:
        say("")
        say(f"  {len(report.skipped)} file(s) cannot be read:")
        for path, reason, _ in report.skipped:
            say(f"      {path} - {reason}")
    say("")
    return 0


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    setup_console()
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "version", False):
        from . import __version__
        say(f"{PROGRAM} {__version__}")
        return 0

    if not getattr(args, "handler", None):
        parser.print_help()
        return 0

    try:
        cfg = load_config(args.config)
        for message in cfg.warnings:
            warn(message)
        return args.handler(args, cfg)
    except StorykeeperError as exc:
        fail(exc)
        return 1
    except KeyboardInterrupt:
        say("")
        say("Stopped.")
        return 130
    except BrokenPipeError:
        return 0


def entry_point() -> None:
    sys.exit(main())


if __name__ == "__main__":
    entry_point()
