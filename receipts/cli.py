"""receipts CLI: verify an agent's claims against the evidence."""

import argparse
import os
import sys

from . import __version__
from .claims import extract_claims
from .evidence import discover_session, gather
from .reporters import render_json, render_terminal
from .verifiers import verify


def _read_summary(args) -> str:
    if args.summary:
        return args.summary
    if args.summary_file:
        with open(args.summary_file, "r", encoding="utf-8") as fh:
            return fh.read()
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def _resolve_session(args) -> "str | None":
    if args.session is None:
        return None
    if args.session == "":
        # --session with no value: auto-discover.
        found = discover_session()
        if found is None:
            print("receipts: no session files found under "
                  "~/.claude/projects or ~/.codex/sessions", file=sys.stderr)
        return found
    return args.session


def cmd_verify(args) -> int:
    summary = _read_summary(args)
    if not summary.strip():
        print("receipts: no summary provided (arg, --summary-file, or stdin)",
              file=sys.stderr)
        return 2
    session = _resolve_session(args)
    if args.session is not None and session is None:
        return 2

    claims = extract_claims(summary)
    evidence = gather(args.repo or os.getcwd(), session=session,
                      diff_base=args.diff)
    report = verify(claims, evidence)

    if args.json:
        print(render_json(report))
    else:
        print(render_terminal(report))

    if args.fail_under is not None:
        pct = report.pass_rate * 100
        if pct < args.fail_under:
            print("receipts: pass rate %.1f%% is under --fail-under %s"
                  % (pct, args.fail_under), file=sys.stderr)
            return 1
    if report.verdict == "FAILED":
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="receipts",
        description='Verify your agent\'s claims against the evidence. '
                    "Receipts or it didn't happen.",
    )
    p.add_argument("--version", action="version", version="receipts " + __version__)
    sub = p.add_subparsers(dest="command")

    v = sub.add_parser("verify", help="verify an agent's summary")
    v.add_argument("summary", nargs="?",
                   help="the agent's summary text (or omit to read stdin)")
    v.add_argument("--summary-file",
                   help="read the agent's summary from a file")
    v.add_argument("--session", nargs="?", const="",
                   help="session transcript (.jsonl); omit the value to "
                        "auto-discover from ~/.claude/projects or "
                        "~/.codex/sessions")
    v.add_argument("--repo", default=None,
                   help="repo to check against (default: current directory)")
    v.add_argument("--diff", default="HEAD",
                   help="git base for the diff (default: HEAD)")
    v.add_argument("--json", action="store_true",
                   help="machine-readable JSON output")
    v.add_argument("--fail-under", type=float, default=None, metavar="PCT",
                   help="exit 1 unless pass rate >= PCT (CI gate)")
    v.set_defaults(func=cmd_verify)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
