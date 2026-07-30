#!/usr/bin/env bash
# PostToolUse hook: clear the ⚙ working indicator from the terminal tab title.

_set_tab_title() {
    local title="$1"
    if [ -n "$TMUX" ]; then
        printf '\033Ptmux;\033\033]0;%s\007\033\\' "$title" >&2
    else
        printf '\033]0;%s\007' "$title" >&2
    fi
}

repo=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null)
branch=$(git branch --show-current 2>/dev/null)
[ -n "$repo" ] && _set_tab_title "${repo}/${branch}"
exit 0
