#!/bin/bash
# Runs our status line, then claude-hud's below it. Two independent renderers
# sharing the same stdin JSON - no parsing of each other's output, so a change
# in either can't break the other. Degrades to ours alone if the plugin is
# absent. Configure claude-hud to hide segments ours already shows.
input=$(cat)
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

echo "$input" | bash "$here/statusline.sh"

hud=$(ls -d "$HOME"/.claude/plugins/marketplaces/*/claude-hud/dist/index.js \
             "$HOME"/.claude/plugins/repos/*/claude-hud/dist/index.js \
             "$HOME"/.claude/plugins/cache/*/claude-hud/dist/index.js \
             2>/dev/null | head -1)
if [ -n "$hud" ] && command -v node >/dev/null 2>&1; then
    out=$(echo "$input" | node "$hud" 2>/dev/null)
    [ -n "$out" ] && printf '\n%s' "$out"
fi

exit 0  # never fail: a nonzero exit makes Claude Code drop the status line
