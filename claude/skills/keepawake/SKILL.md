---
name: keepawake
description: Keep the Mac awake (lid closed, display off) while doing a long task, then release when done. Soft mode uses caffeinate -si (AC only); hard mode also disables battery sleep via sudo pmset.
---

# keepawake

Prevent the Mac from sleeping during a long-running task — including when the lid is closed.

Two modes:
- **Soft** (default): `caffeinate -si` — prevents idle and system sleep. Works reliably on AC power; on battery with lid closed macOS may still override it.
- **Hard**: `caffeinate -si` + `sudo pmset -b sleep 0` — disables battery sleep at the OS level. Works on battery too. Requires passwordless sudo for `/usr/bin/pmset` (see setup below).

The display is allowed to sleep in both modes; only the CPU/network stays up.

## PID/state files

- `~/.claude/keepawake.pid` — caffeinate PID
- `~/.claude/keepawake.sleep` — original battery sleep value (hard mode only, for restore)

## Check if hard mode is available

Before offering hard mode, check if passwordless sudo pmset works:

```bash
if sudo -n pmset -g 2>/dev/null | grep -q sleep; then
    echo "hard mode available"
else
    echo "hard mode unavailable (no passwordless sudo pmset)"
fi
```

If unavailable, fall back to soft mode and note that `-s` only holds on AC power. To enable hard mode, the user can run:
```bash
echo 'sam ALL=(ALL) NOPASSWD: /usr/bin/pmset' | sudo tee /etc/sudoers.d/pmset && sudo chmod 440 /etc/sudoers.d/pmset
```

## Start

Check if already running first. If the user is on battery with the lid closed, offer hard mode if available:

```bash
# Already running?
if [ -f ~/.claude/keepawake.pid ] && kill -0 "$(cat ~/.claude/keepawake.pid)" 2>/dev/null; then
    echo "keepawake already active (PID $(cat ~/.claude/keepawake.pid))"
    exit 0
fi

HARD=${1:-false}  # pass "hard" as argument for hard mode

caffeinate -si &
echo $! > ~/.claude/keepawake.pid
echo "caffeinate started (PID $!)"

if [ "$HARD" = "hard" ]; then
    if sudo -n pmset -g &>/dev/null; then
        original=$(pmset -g | awk '/^[ \t]+sleep / {print $2; exit}')
        echo "$original" > ~/.claude/keepawake.sleep
        sudo pmset -b sleep 0
        echo "hard mode: battery sleep disabled (was ${original}min)"
    else
        echo "hard mode requested but sudo pmset not available — soft mode only"
    fi
fi
```

Tell the user which mode is active and note AC-only limitation if soft mode on battery.

## Stop

```bash
# Kill caffeinate
if [ -f ~/.claude/keepawake.pid ]; then
    pid=$(cat ~/.claude/keepawake.pid)
    kill "$pid" 2>/dev/null && echo "caffeinate stopped (PID $pid)" || echo "caffeinate was already gone"
    rm -f ~/.claude/keepawake.pid
else
    echo "caffeinate not running"
fi

# Restore pmset if hard mode was active
if [ -f ~/.claude/keepawake.sleep ]; then
    original=$(cat ~/.claude/keepawake.sleep)
    if sudo -n pmset -g &>/dev/null; then
        sudo pmset -b sleep "$original"
        echo "battery sleep restored to ${original}min"
    else
        echo "WARNING: could not restore battery sleep setting — run: sudo pmset -b sleep $original"
    fi
    rm -f ~/.claude/keepawake.sleep
fi
```

Tell the user: "Released sleep prevention — Mac can sleep normally now."

## Status

```bash
if [ -f ~/.claude/keepawake.pid ] && kill -0 "$(cat ~/.claude/keepawake.pid)" 2>/dev/null; then
    mode=$([ -f ~/.claude/keepawake.sleep ] && echo "hard" || echo "soft")
    echo "keepawake active — $mode mode (PID $(cat ~/.claude/keepawake.pid))"
    pmset -g | awk '/^[ \t]+sleep / {print "battery sleep timeout: "$2"min"}'
    pmset -g assertions | grep -i "PreventSystemSleep\|PreventUserIdleSystemSleep" | head -3
else
    echo "keepawake not running"
    rm -f ~/.claude/keepawake.pid ~/.claude/keepawake.sleep 2>/dev/null
fi
```

## When to use

- **Soft mode**: user is on AC power or doesn't mention battery/lid concerns. Default.
- **Hard mode**: user says they'll close the lid on battery, or soft mode has failed before. Check availability first.
- **Stop automatically** when the long task completes, before ending your response.
- **Don't start** for quick tasks — only when there's a real risk of the Mac sleeping mid-work.

## Important notes

- Always restore pmset on stop — a forgotten `sleep 0` setting drains battery.
- If the session crashes with hard mode active, the `.sleep` file persists and the next stop will restore correctly. If the file is lost, remind the user to run `sudo pmset -b sleep 10` (or their preferred timeout) manually.
- Stale PID file: `kill -0` failure means caffeinate is gone; overwrite cleanly on next start.
