#!/bin/bash
# Claude Code status line:
#   ~/path | repo:branch +adds-dels | model (effort) | ctx NN% | 5h NN%
input=$(cat)
model="?" effort="" dir="." ctx="" adds=0 dels=0 rl=0
eval "$(echo "$input" | jq -r '@sh "
  model=\(.model.display_name // "?")
  effort=\(.effort.level // "")
  dir=\(.workspace.current_dir // ".")
  ctx=\(.context_window.remaining_percentage // "")
  adds=\(.cost.total_lines_added // 0)
  dels=\(.cost.total_lines_removed // 0)
  rl=\(.rate_limits.five_hour.used_percentage // 0)
"' 2>/dev/null)"
# Guard against non-numeric values reaching the arithmetic tests below
[[ $adds =~ ^[0-9]+$ ]] || adds=0
[[ $dels =~ ^[0-9]+$ ]] || dels=0
[[ $rl =~ ^[0-9.]+$ ]] || rl=0

# Path relative to home, and repo:branch from the git root
path=${dir/#$HOME/\~}
branch=$(git -C "$dir" branch --show-current 2>/dev/null)
repo=$(basename "$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null)

printf '%s' "$path"
[ -n "$branch" ] && printf ' \033[90m|\033[0m \033[32m%s%s\033[0m' \
    "${repo:+$repo:}" "$branch"

# Lines changed this session, next to the branch they were made on
if [ "$adds" -gt 0 ] || [ "$dels" -gt 0 ]; then
    printf ' \033[32m+%s\033[0m\033[31m-%s\033[0m' "$adds" "$dels"
fi

printf ' \033[90m|\033[0m \033[36m%s\033[0m' "$model"
[ -n "$effort" ] && printf ' \033[35m(%s)\033[0m' "$effort"

# Context remaining: green >50%, yellow >20%, else red
if [[ $ctx =~ ^[0-9.]+$ ]]; then
    pct=${ctx%.*}
    if [ "$pct" -gt 50 ]; then c=32; elif [ "$pct" -gt 20 ]; then c=33; else c=31; fi
    printf ' \033[90m|\033[0m \033[%sm%s%% ctx\033[0m' "$c" "$pct"
fi

# Rate limit is the real constraint on a plan (cost is hypothetical there).
# Green <50%, yellow <80%, else red.
pct=${rl%.*}
if [ "$pct" -lt 50 ]; then c=32; elif [ "$pct" -lt 80 ]; then c=33; else c=31; fi
printf ' \033[90m|\033[0m \033[%sm5h %s%%\033[0m' "$c" "$pct"

exit 0  # never fail: a nonzero exit makes Claude Code drop the status line
