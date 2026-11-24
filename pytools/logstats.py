#!/usr/bin/env python3
"""Analytics over the ~/.logs bash-history logs written by bashrc's prompt_command.

Each logged line looks like:

    2026-06-10.09:42:35 [Mh10]  5061  gs

i.e. "<date>.<time> [<session>]  <histnum>  <command>". This surfaces what that
pile of data actually contains: most-used commands and long commands you run
often enough to be worth aliasing.
"""

import argparse
import glob
import os
import re
from collections import Counter
from datetime import datetime, timedelta

from colorstrings import blue_str, bold_str, green_str, grey_str

LOGDIR = os.environ.get("BASH_LOGS_DIR", os.path.expanduser("~/.logs"))

# <date>.<time> [<session>] <optional hist number> <command>
LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})\.(\d{2}:\d{2}:\d{2}) \[([^\]]*)\]\s+(?:\d+\s+)?(.*)$"
)

# Commands that are already short/cheap, never worth flagging as alias candidates.
_TRIVIAL = {"ls", "cd", "gs", "gd", "vim", "cat", "git", "ll", "la"}


class Entry:
    __slots__ = ("cmd", "dt", "prog", "session")

    def __init__(self, dt, session, cmd):
        self.dt = dt
        self.session = session
        self.cmd = cmd
        self.prog = cmd.split()[0] if cmd.split() else cmd


def load_entries(since=None, grep=None):
    """Parse all log files, optionally filtered by date and a substring."""
    entries = []
    for path in glob.glob(os.path.join(LOGDIR, "bash-history-*.log")):
        try:
            with open(path, errors="replace") as f:
                for line in f:
                    m = LINE_RE.match(line.rstrip("\n"))
                    if not m:
                        continue
                    date_s, time_s, session, cmd = m.groups()
                    cmd = cmd.strip()
                    if not cmd:
                        continue
                    if grep and grep.lower() not in cmd.lower():
                        continue
                    try:
                        dt = datetime.strptime(
                            f"{date_s}.{time_s}", "%Y-%m-%d.%H:%M:%S"
                        )
                    except ValueError:
                        continue
                    if since and dt < since:
                        continue
                    entries.append(Entry(dt, session, cmd))
        except OSError:
            continue
    entries.sort(key=lambda e: e.dt)
    return entries


def _bar(n, maxn, width=30):
    filled = int(width * n / maxn) if maxn else 0
    return "|" * filled + " " * (width - filled)


def print_header(entries):
    if not entries:
        print(grey_str("No log entries found in " + LOGDIR))
        return
    span_days = max(1, (entries[-1].dt - entries[0].dt).days + 1)
    sessions = len({e.session for e in entries})
    print(bold_str(f"\n{len(entries):,} commands") + grey_str(f"  in {LOGDIR}"))
    print(
        grey_str(
            f"{entries[0].dt:%Y-%m-%d} -> {entries[-1].dt:%Y-%m-%d}  "
            f"({span_days} days, {sessions} sessions, "
            f"{len(entries) / span_days:.0f}/day)"
        )
    )


def print_top(entries, limit, full=False):
    label = "full command lines" if full else "commands"
    counts = Counter(e.cmd if full else e.prog for e in entries)
    total = sum(counts.values())
    maxn = counts.most_common(1)[0][1] if counts else 0
    print(bold_str(f"\nTop {label}"))
    print(grey_str("  cnt     %   " + "-" * 30))
    for name, n in counts.most_common(limit):
        perc = 100.0 * n / total if total else 0
        disp = name if len(name) <= 48 else name[:47] + "…"
        print(
            f"{n:5} {grey_str('%5.1f' % perc)} {green_str(_bar(n, maxn))} {blue_str(disp)}"
        )


def print_alias_candidates(entries, limit):
    """Long-ish full command lines run often enough to be worth an alias."""
    counts = Counter(e.cmd for e in entries)
    scored = []
    for cmd, n in counts.items():
        prog = cmd.split()[0] if cmd.split() else cmd
        if n < 5 or len(cmd) < 12 or prog in _TRIVIAL:
            continue
        # rough "typing saved": times run * length, minus an aliased keystroke
        scored.append((n * (len(cmd) - 3), n, cmd))
    scored.sort(reverse=True)
    if not scored:
        return
    print(bold_str("\nAlias candidates") + grey_str("  (run often, long to type)"))
    print(grey_str("  cnt  len   " + "-" * 30))
    for _score, n, cmd in scored[:limit]:
        disp = cmd if len(cmd) <= 56 else cmd[:55] + "…"
        print(f"  {n:4} {len(cmd):4}  {blue_str(disp)}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("grep", nargs="?", help="only count commands containing this text")
    p.add_argument("--last", type=int, metavar="N", help="only the last N days")
    p.add_argument("--since", type=str, help="only since this date (YYYY-MM-DD)")
    p.add_argument("--limit", type=int, default=15, help="rows per section")
    p.add_argument("--full", action="store_true", help="rank full lines, not programs")
    p.add_argument("--aliases", action="store_true", help="only alias candidates")
    p.add_argument(
        "--commands", action="store_true", help="only the top-commands table"
    )
    args = p.parse_args()

    since = None
    if args.last:
        since = datetime.now() - timedelta(days=args.last)
    elif args.since:
        since = datetime.strptime(args.since, "%Y-%m-%d")

    entries = load_entries(since=since, grep=args.grep)
    if not entries:
        print_header(entries)
        return

    # Focused modes
    if args.aliases:
        print_alias_candidates(entries, args.limit)
        return
    if args.commands:
        print_top(entries, args.limit, full=args.full)
        return

    # Default: a small dashboard
    print_header(entries)
    print_top(entries, args.limit, full=args.full)
    print_alias_candidates(entries, args.limit)
    print()


if __name__ == "__main__":
    main()
