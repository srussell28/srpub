#!/bin/bash
# Claude Code status line:
#   ~/path | repo:branch +N-M | model (effort) | ctx NN% | 5h NN% | sess +N-M
# The +N-M by the branch is the diff vs the trunk merge-base; "sess" is what
# this Claude session has written (cumulative, unaffected by commits).
input=$(cat)
model="?" effort="" dir="." ctx="" adds=0 dels=0 rl=0 transcript=""
eval "$(echo "$input" | jq -r '@sh "
  model=\(.model.display_name // "?")
  effort=\(.effort.level // "")
  dir=\(.workspace.current_dir // ".")
  ctx=\(.context_window.remaining_percentage // "")
  adds=\(.cost.total_lines_added // 0)
  dels=\(.cost.total_lines_removed // 0)
  rl=\(.rate_limits.five_hour.used_percentage // 0)
  transcript=\(.transcript_path // "")
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

# Branch diff vs the trunk merge-base (survives commits, unlike session lines)
if [ -n "$branch" ]; then
    for t in origin/main origin/master origin/develop; do
        base=$(git -C "$dir" merge-base HEAD "$t" 2>/dev/null) && break
    done
    if [ -n "$base" ]; then
        read -r bi bd < <(git -C "$dir" diff --numstat "$base" 2>/dev/null |
            awk '{a+=$1; d+=$2} END {print a+0, d+0}')
        if [ "${bi:-0}" -gt 0 ] || [ "${bd:-0}" -gt 0 ]; then
            printf ' \033[32m+%s\033[0m\033[31m-%s\033[0m' "$bi" "$bd"
        fi
    fi
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

# Lines this session has written (cumulative; unaffected by commits)
if [ "$adds" -gt 0 ] || [ "$dels" -gt 0 ]; then
    printf ' \033[90m|\033[0m \033[90msess\033[0m \033[32m+%s\033[0m\033[31m-%s\033[0m' \
        "$adds" "$dels"
fi

# What Claude is doing RIGHT NOW: the transcript is written incrementally, so
# a tool_use with no matching tool_result yet is the in-flight call. Beats the
# generic "Pondering..." spinner. Nothing renders when idle.
# Pair with "refreshInterval": 2 in settings.json so the timer ticks.
if [ -n "$transcript" ] && [ -f "$transcript" ]; then
    # An in-flight call is by definition the newest thing in the file, so a
    # tail keeps this O(1) as the transcript grows.
    # An unmatched tool_use is a running call. If there is none but the newest
    # record is a thinking block, Claude is reasoning - the CoT text itself is
    # never returned by the API (thinking.display defaults to "omitted", so the
    # blocks are empty), but the elapsed time still beats a bare spinner.
    busy=$(tail -400 "$transcript" 2>/dev/null | jq -rs '
        (map(select(.type=="user") | .message.content?
             | if type=="array" then .[] else empty end
             | select(type=="object" and .type=="tool_result") | .tool_use_id) | unique) as $done
        | (map(select(.type=="assistant")
              | .timestamp as $ts | .message.content?
              | if type=="array" then .[] else empty end
              | select(.type=="tool_use") | {id, name, ts:$ts, i:.input})
           | map(select(.id as $i | $done | index($i) | not)) | last) as $tool
        | (map(select(.type=="assistant" and (.message.content? // []
               | map(.type) | index("thinking")))) | last) as $think
        | (map(select(.type=="assistant" or .type=="user")) | last) as $newest
        | if $tool then
            [ $tool.ts,
              (if $tool.name=="Agent" then ($tool.i.subagent_type // "agent") else $tool.name end),
              (($tool.i.description // $tool.i.command // $tool.i.file_path
                // $tool.i.pattern // $tool.i.query // "")
               | tostring | gsub("\\s+"; " ") | .[0:70]) ]
          elif ($think and $newest and $think.timestamp == $newest.timestamp) then
            [ $think.timestamp, "thinking", "" ]
          else empty end
        | @tsv' 2>/dev/null)
    if [ -n "$busy" ]; then
        IFS=$'\t' read -r bts bname barg <<<"$busy"
        start=$(date -j -u -f "%Y-%m-%dT%H:%M:%S" "${bts%%.*}" +%s 2>/dev/null ||
            date -u -d "${bts%%.*}" +%s 2>/dev/null)
        el=""
        if [ -n "$start" ]; then
            s=$(($(date +%s) - start))
            [ "$s" -ge 0 ] && { [ "$s" -ge 60 ] && el=" $((s / 60))m$((s % 60))s" || el=" ${s}s"; }
        fi
        printf '\n\033[35m◐ %s\033[0m' "$bname"
        [ -n "$barg" ] && printf '\033[90m: %s\033[0m' "$barg"
        printf '\033[90m%s\033[0m' "$el"
    fi
fi

exit 0  # never fail: a nonzero exit makes Claude Code drop the status line
