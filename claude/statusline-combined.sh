#!/bin/bash
# Our status line on top, claude-hud below. Both renderers get the same stdin
# JSON and emit independent lines - neither parses the other's output, so a
# change in either can't break the other. Falls back to ours alone if the
# plugin or node is missing. Configure claude-hud to hide what ours shows:
#   ~/.claude/plugins/claude-hud/config.json
input=$(cat)
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

echo "$input" | bash "$here/statusline.sh"

# claude-hud reads COLUMNS since Claude Code pipes stdout (no tty width).
# Minus 4 for Claude Code's input padding.
cols=${COLUMNS:-}
case "$cols" in "" | *[!0-9]*) cols=$(stty size 2>/dev/null </dev/tty | awk '{print $2}') ;; esac
case "$cols" in "" | *[!0-9]*) cols=120 ;; esac
export COLUMNS=$((cols > 4 ? cols - 4 : 1))

# Latest installed version, so plugin updates need no re-setup.
plugin_dir=$(ls -d "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/plugins/cache/*/claude-hud/*/ 2>/dev/null |
    awk -F/ '{ print $(NF-1) "\t" $(0) }' |
    grep -E '^[0-9]+\.[0-9]+\.[0-9]+[[:space:]]' |
    sort -t. -k1,1n -k2,2n -k3,3n -k4,4n | tail -1 | cut -f2-)

if [ -n "$plugin_dir" ] && command -v node >/dev/null 2>&1; then
    out=$(echo "$input" | node "${plugin_dir}dist/index.js" 2>/dev/null)
    [ -n "$out" ] && printf '\n%s' "$out"
fi

exit 0 # never fail: a nonzero exit makes Claude Code drop the status line
