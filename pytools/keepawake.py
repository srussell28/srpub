#!/usr/bin/env python3
"""
keepawake - prevent macOS from sleeping.

Usage:
  keepawake [DURATION]          # start hard mode (default)
  keepawake [DURATION] --soft   # soft mode (caffeinate only, AC-power)
  keepawake --stop              # stop and restore
  keepawake --status            # show current state

DURATION: 30s, 15m, 2h, or raw seconds. Omit for indefinite.

Hard mode (default): caffeinate -si + sudo pmset -b sleep 0.
  Works on battery with lid closed. Requires passwordless sudo pmset.
  Setup: echo 'USER ALL=(ALL) NOPASSWD: /usr/bin/pmset' | sudo tee /etc/sudoers.d/pmset

Soft mode: caffeinate -si only.
  Works reliably on AC; macOS may override on battery with lid closed.
"""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

STATE_FILE = Path.home() / ".claude" / "keepawake.json"
FALLBACK_SLEEP_MINS = 10


def parse_duration(s: str) -> int:
    s = s.strip().lower()
    if s.endswith("h"):
        return int(float(s[:-1]) * 3600)
    if s.endswith("m"):
        return int(float(s[:-1]) * 60)
    if s.endswith("s"):
        return int(s[:-1])
    return int(s)


def fmt_duration(secs: int) -> str:
    if secs >= 3600 and secs % 3600 == 0:
        return f"{secs // 3600}h"
    if secs >= 60 and secs % 60 == 0:
        return f"{secs // 60}m"
    if secs >= 60:
        return f"{secs // 60}m{secs % 60}s"
    return f"{secs}s"


def can_sudo_pmset() -> bool:
    return subprocess.run(["sudo", "-n", "pmset", "-g"], capture_output=True).returncode == 0


def get_battery_sleep() -> int:
    out = subprocess.run(["pmset", "-g"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("sleep "):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                pass
    return FALLBACK_SLEEP_MINS


def is_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    except Exception:
        return {}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def do_start(soft: bool, duration_secs: int | None):
    state = load_state()
    if state and is_alive(state.get("caffeinate_pid", 0)):
        print(f"keepawake already active ({state['mode']} mode, PID {state['caffeinate_pid']})")
        return

    hard = not soft
    if hard and not can_sudo_pmset():
        print("Warning: hard mode needs passwordless sudo pmset — falling back to soft mode.")
        print("  Fix: echo 'sam ALL=(ALL) NOPASSWD: /usr/bin/pmset' | sudo tee /etc/sudoers.d/pmset")
        hard = False

    original_sleep = None
    if hard:
        original_sleep = get_battery_sleep()
        subprocess.run(["sudo", "pmset", "-b", "sleep", "0"], check=True)

    caff_cmd = ["caffeinate", "-si"] + (["-t", str(duration_secs)] if duration_secs else [])
    caff = subprocess.Popen(caff_cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    restore_pid = None
    if hard and duration_secs:
        restore_proc = subprocess.Popen(
            ["bash", "-c", f"sleep {duration_secs} && sudo pmset -b sleep {original_sleep}"],
            start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        restore_pid = restore_proc.pid

    save_state({
        "mode": "hard" if hard else "soft",
        "started_at": int(time.time()),
        "duration_secs": duration_secs,
        "original_sleep": original_sleep,
        "caffeinate_pid": caff.pid,
        "restore_pid": restore_pid,
    })

    dur_str = f" for {fmt_duration(duration_secs)}" if duration_secs else " indefinitely"
    print(f"keepawake started ({'hard' if hard else 'soft'} mode{dur_str}, PID {caff.pid})")
    if hard:
        print(f"  battery sleep disabled (was {original_sleep}min — restores on stop)")
    if not hard:
        print("  Note: soft mode only holds reliably on AC power")


def do_stop():
    state = load_state()
    if not state:
        print("keepawake not running")
        return

    caff_pid = state.get("caffeinate_pid")
    if is_alive(caff_pid):
        os.kill(caff_pid, 15)
        print(f"caffeinate stopped (PID {caff_pid})")
    else:
        print("caffeinate was already gone")

    restore_pid = state.get("restore_pid")
    if is_alive(restore_pid):
        os.kill(restore_pid, 15)

    original = state.get("original_sleep")
    if original is not None:
        if can_sudo_pmset():
            subprocess.run(["sudo", "pmset", "-b", "sleep", str(original)])
            print(f"battery sleep restored to {original}min")
        else:
            print(f"WARNING: run manually: sudo pmset -b sleep {original}")

    STATE_FILE.unlink(missing_ok=True)
    print("keepawake released — Mac can sleep normally")


def do_status():
    state = load_state()
    if not state or not is_alive(state.get("caffeinate_pid", 0)):
        print("keepawake not running")
        if state:
            STATE_FILE.unlink(missing_ok=True)
        return

    elapsed = int(time.time()) - state["started_at"]
    dur = state.get("duration_secs")
    mode = state["mode"]
    pid = state["caffeinate_pid"]

    dur_part = f", {fmt_duration(max(0, dur - elapsed))} remaining of {fmt_duration(dur)}" if dur else ", no timeout"
    print(f"keepawake active — {mode} mode (PID {pid})")
    print(f"  running: {fmt_duration(elapsed)}{dur_part}")
    if mode == "hard":
        current = get_battery_sleep()
        print(f"  battery sleep: {current}min (original: {state.get('original_sleep', '?')}min)")


def main():
    parser = argparse.ArgumentParser(
        description="Keep macOS awake, with optional duration.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  keepawake 2h         # hard mode for 2 hours\n  keepawake --soft 30m # soft mode for 30 min\n  keepawake --stop     # stop now",
    )
    parser.add_argument("duration", nargs="?", help="Duration: 30s, 15m, 2h (omit for indefinite)")
    parser.add_argument("--soft", action="store_true", help="Soft mode: caffeinate only (no pmset)")
    parser.add_argument("--stop", action="store_true", help="Stop keepawake and restore settings")
    parser.add_argument("--status", action="store_true", help="Show current keepawake state")
    args = parser.parse_args()

    if args.stop:
        do_stop()
    elif args.status:
        do_status()
    else:
        duration_secs = parse_duration(args.duration) if args.duration else None
        do_start(soft=args.soft, duration_secs=duration_secs)


if __name__ == "__main__":
    main()
