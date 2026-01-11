from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from wmt.config import AppConfig, load_config
from wmt.logging_setup import setup_logging
from wmt.pipeline import process_one_from_inbox, process_url
from wmt.state import open_state_store
from wmt.watcher import Watcher

log = logging.getLogger(__name__)

_GLOBAL_FLAGS = {"-v", "--verbose"}


def _normalize_argv(argv: list[str]) -> list[str]:
    """
    Allow global flags (like --config / -v) to appear *after* the subcommand.
    """
    global_parts: list[str] = []
    rest: list[str] = []

    i = 0
    while i < len(argv):
        arg = argv[i]

        if arg in _GLOBAL_FLAGS:
            global_parts.append(arg)
            i += 1
            continue

        if arg == "--config":
            global_parts.append(arg)
            if i + 1 < len(argv):
                global_parts.append(argv[i + 1])
                i += 2
            else:
                i += 1
            continue

        if arg.startswith("--config="):
            global_parts.append(arg)
            i += 1
            continue

        rest.append(arg)
        i += 1

    return global_parts + rest


def _load(cfg_path: str | None, *, verbose: bool) -> AppConfig:
    cfg = load_config(Path(cfg_path).expanduser() if cfg_path else None)
    setup_logging(cfg.paths.log_file, verbose=verbose)
    return cfg


def cmd_watch(args: argparse.Namespace) -> int:
    cfg = _load(args.config, verbose=args.verbose)
    watcher = Watcher(cfg)
    try:
        if args.once:
            watcher.run_once(log_when_idle=True, wait_for_stable=True)
            return 0
        watcher.run_forever()
        return 0
    finally:
        watcher.close()


def cmd_process_one(args: argparse.Namespace) -> int:
    cfg = _load(args.config, verbose=args.verbose)
    state = open_state_store(path=cfg.state.path, backend=cfg.state.backend)
    try:
        outcome = process_one_from_inbox(cfg, state=state, force=args.force)
        if outcome:
            print(outcome.output_file)
        return 0
    finally:
        state.close()


def cmd_process_url(args: argparse.Namespace) -> int:
    cfg = _load(args.config, verbose=args.verbose)
    transcript: str | None = None
    if args.transcript_stdin:
        transcript = sys.stdin.read()
    state = open_state_store(path=cfg.state.path, backend=cfg.state.backend)
    try:
        outcome = process_url(
            cfg,
            url=args.url,
            transcript=transcript,
            title=args.title,
            force=args.force,
            state=state,
        )
        if outcome:
            print(outcome.output_file)
        return 0
    finally:
        state.close()


def cmd_status(args: argparse.Namespace) -> int:
    cfg = _load(args.config, verbose=args.verbose)
    state = open_state_store(path=cfg.state.path, backend=cfg.state.backend)
    try:
        stats = state.stats()
        print(f"processed={stats['processed']} failed={stats['failed']} in_progress={stats['in_progress']}")
        return 0
    finally:
        state.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wmt")
    p.add_argument("--config", help="Path to config.yaml (default: auto)")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("watch", help="Watch Brave Inbox bookmarks and process new items")
    w.add_argument("--once", action="store_true", help="Process one stable update and exit")
    w.set_defaults(func=cmd_watch)

    po = sub.add_parser("process-one", help="Process one unprocessed Inbox bookmark")
    po.add_argument("--force", action="store_true", help="Reprocess even if already processed/failed")
    po.set_defaults(func=cmd_process_one)

    pu = sub.add_parser(
        "process-url",
        help="Process a URL (auto-fetches content; use --transcript-stdin to supply your own transcript)",
    )
    pu.add_argument("url", help="URL to analyse")
    pu.add_argument("--title", help="Optional title hint (used for filename)")
    pu.add_argument(
        "--transcript-stdin",
        action="store_true",
        help="Read transcript from stdin and use it as the primary source (skips auto transcript retrieval)",
    )
    pu.add_argument("--force", action="store_true", help="Reprocess even if already processed/failed")
    pu.set_defaults(func=cmd_process_url)

    st = sub.add_parser("status", help="Show ledger counts")
    st.set_defaults(func=cmd_status)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(_normalize_argv(raw))
    return int(args.func(args))
