#!/bin/bash
# Claude Code status line: model (effort) | dir | git branch
input=$(cat)
eval "$(echo "$input" | jq -r '@sh "model=\(.model.display_name // "?") effort=\(.effort.level // "") dir=\(.workspace.current_dir // ".")"')"
branch=$(git -C "$dir" branch --show-current 2>/dev/null)

printf '\033[36m%s\033[0m' "$model"
[ -n "$effort" ] && printf ' \033[35m(%s)\033[0m' "$effort"
printf ' \033[90m|\033[0m %s' "$(basename "$dir")"
[ -n "$branch" ] && printf ' \033[90m|\033[0m \033[32m%s\033[0m' "$branch"
