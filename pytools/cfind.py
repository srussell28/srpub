#!/usr/bin/env python3
"""cfind TERM [TERM ...] — find a past claude session (all terms must match) and resume it."""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from colorstrings import blue_str, bold_str, grey_str, red_str, yellow_str

PROJECTS = Path.home() / ".claude" / "projects"
BRANCH_SESSIONS = Path.home() / ".claude" / "branch_sessions"


def files_matching(term):
    """Top-level session transcripts containing term (case-insensitive)."""
    if shutil.which("rg"):
        args = [
            "rg",
            "-l",
            "-i",
            "-F",
            "--max-depth",
            "2",
            "-g",
            "*.jsonl",
            term,
            str(PROJECTS),
        ]
    else:
        print(
            yellow_str(
                "rg not found, falling back to grep (slower; brew/apt install ripgrep)"
            ),
            file=sys.stderr,
        )
        args = ["grep", "-rliF", "--include=*.jsonl", term, str(PROJECTS)]
    out = subprocess.run(args, check=False, capture_output=True, text=True).stdout
    return {Path(p) for p in out.splitlines() if Path(p).parent.parent == PROJECTS}


def session_aliases():
    """sid -> ct keys (e.g. repo/branch, repo/~name) from branch_sessions."""
    aliases = {}
    if BRANCH_SESSIONS.exists():
        for line in BRANCH_SESSIONS.read_text().splitlines():
            key, _, sid = line.partition(" ")
            aliases.setdefault(sid.strip(), []).append(key)
    return aliases


def session_info(path):
    info = {
        "sid": path.stem,
        "title": "",
        "prompt": "",
        "cwd": "",
        "branch": "",
        "ts": "",
    }
    with open(path, errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = d.get("type")
            if t == "ai-title":
                info["title"] = d.get("aiTitle", "")
            elif t == "last-prompt":
                info["prompt"] = d.get("lastPrompt", "")
            elif (
                t == "user"
                and not info["prompt"]
                and isinstance(d.get("message", {}).get("content"), str)
            ):
                info["prompt"] = d["message"]["content"]
            if d.get("cwd"):
                info["cwd"], info["branch"] = d["cwd"], d.get("gitBranch", "")
            info["ts"] = d.get("timestamp") or info["ts"]
    return info


def main():
    terms = sys.argv[1:]
    if not terms or terms[0] in ("-h", "--help"):
        print(__doc__.strip())
        return
    aliases = session_aliases()
    paths = set.intersection(*(files_matching(t) for t in terms))
    # Also match sessions whose ct alias contains every term
    for sid, keys in aliases.items():
        if all(any(t.lower() in k.lower() for k in keys) for t in terms):
            paths |= set(PROJECTS.glob(f"*/{sid}.jsonl"))
    sessions = {}
    for p in paths:
        if (
            not p.parent.is_symlink()
        ):  # worktree-linked project dirs duplicate the real one
            info = session_info(p)
            sessions[info["sid"]] = info
    if not sessions:
        print(red_str(f"No claude sessions match: {' '.join(terms)}"))
        return
    found = sorted(sessions.values(), key=lambda s: s["ts"], reverse=True)

    for i, s in enumerate(found, 1):
        when = (
            datetime.fromisoformat(s["ts"]).astimezone().strftime("%Y-%m-%d %H:%M")
            if s["ts"]
            else "?"
        )
        names = ", ".join(aliases.get(s["sid"], []))
        print(
            f"{bold_str(f'{i:>2}.')} {grey_str(when)}  {bold_str(s['title'] or '(untitled)')}  {yellow_str(names)}"
        )
        print(
            f"     {blue_str(s['cwd'])} {grey_str(s['branch'])}  {grey_str(s['sid'])}"
        )
        print(f"     {' '.join(s['prompt'].split())[:100]}")

    try:
        choice = input(f"\nResume which? [1-{len(found)}, Enter to cancel]: ").strip()
    except (EOFError, KeyboardInterrupt):
        choice = ""
    if not choice.isdigit() or not 1 <= int(choice) <= len(found):
        print("Cancelled.")
        return
    s = found[int(choice) - 1]
    # --resume only finds sessions from the cwd they were started in
    if s["cwd"] and os.path.isdir(s["cwd"]):
        os.chdir(s["cwd"])
    else:
        print(
            yellow_str(
                f"Original dir {s['cwd'] or '?'} is gone; resume may fail from here."
            ),
            file=sys.stderr,
        )
    print(grey_str(f"cd {os.getcwd()} && claude --resume {s['sid']}"))
    os.execvp("claude", ["claude", "--resume", s["sid"]])


if __name__ == "__main__":
    main()
