---
name: keepawake
description: Keep the Mac awake (lid closed, display off) while doing a long task, then release when done. Uses caffeinate -si to block system and idle sleep.
---

# keepawake

Prevent the Mac from sleeping during a long-running task — including when the lid is closed. Uses `caffeinate -si` which blocks both system sleep (`-s`, requires AC power) and idle sleep (`-i`). The display is allowed to sleep; only the CPU/network stays up.

## PID file

`~/.claude/keepawake.pid` — stores the caffeinate PID so it can be stopped later. Always check this file before starting to avoid stacking multiple processes.

## Start

Run this at the beginning of any task that will take more than a few minutes or that involves background agents:

```bash
# Check if already running
if [ -f ~/.claude/keepawake.pid ] && kill -0 "$(cat ~/.claude/keepawake.pid)" 2>/dev/null; then
    echo "keepawake already active (PID $(cat ~/.claude/keepawake.pid))"
else
    caffeinate -si &
    echo $! > ~/.claude/keepawake.pid
    echo "keepawake started (PID $!)"
fi
```

Tell the user: "Keeping the Mac awake while I work — will release when done."

## Stop

Run this when the task is complete:

```bash
if [ -f ~/.claude/keepawake.pid ]; then
    pid=$(cat ~/.claude/keepawake.pid)
    if kill "$pid" 2>/dev/null; then
        echo "keepawake stopped (PID $pid)"
    else
        echo "keepawake PID $pid was already gone"
    fi
    rm -f ~/.claude/keepawake.pid
else
    echo "keepawake not running"
fi
```

Tell the user: "Released sleep prevention — Mac can sleep normally now."

## Status

```bash
if [ -f ~/.claude/keepawake.pid ] && kill -0 "$(cat ~/.claude/keepawake.pid)" 2>/dev/null; then
    echo "keepawake active (PID $(cat ~/.claude/keepawake.pid))"
    pmset -g assertions | grep -i "PreventSystemSleep\|PreventUserIdleSystemSleep" | head -5
else
    echo "keepawake not running"
    rm -f ~/.claude/keepawake.pid 2>/dev/null
fi
```

## When to use

- **Start automatically** when the user asks you to do something that will take a long time (e.g. a big refactor, running a build, a background agent sweep) and mentions closing the lid or stepping away.
- **Stop automatically** when the long task completes, before ending your response.
- **Don't start** for quick tasks — only when there's a real risk of the Mac sleeping mid-work.

## Important notes

- `-s` only works on AC power. If the Mac is on battery and the lid is closed, macOS may still sleep. Mention this if it seems relevant.
- If the Stop hook kills caffeinate, verify with `pmset -g assertions` that no PreventSystemSleep assertions remain. A runaway caffeinate will drain battery.
- If you crash mid-task and the pid file is stale, the next Start run will detect `kill -0` failure and overwrite it cleanly.
