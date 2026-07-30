#!/usr/bin/env bash
# Stop hook: release the repo lock and clear the tab title working indicator.

input=$(cat)
session_id=$(echo "$input" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id','unknown'))" 2>/dev/null)
[ -z "$session_id" ] && session_id="unknown"

SRPUB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bash "$SRPUB_DIR/claude/repo-lock.sh" release "$session_id"

# Clear ⚙ working indicator from terminal tab title
repo=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null)
branch=$(git branch --show-current 2>/dev/null)
if [ -n "$repo" ]; then
    if [ -n "$TMUX" ]; then
        printf '\033Ptmux;\033\033]0;%s\007\033\\' "${repo}/${branch}" >&2
    else
        printf '\033]0;%s\007' "${repo}/${branch}" >&2
    fi
fi
exit 0
