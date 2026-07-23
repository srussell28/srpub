#!/usr/bin/env bash
# PreToolUse hook: repo lock with branch tracking and wait/block logic.
#
# Exit 0  → allow tool call (we hold the lock)
# Exit 1  → BLOCK tool call (couldn't get lock, branch changed, or dirty checkout)
#
# Lock file format: session_id timestamp_epoch branch
#
# Behavior when another session holds the lock:
#   1. Print prominent warning + worktree suggestion
#   2. Poll up to 60s for the lock to clear
#   3. If lock clears and checkout is clean → acquire and proceed
#   4. If lock clears but checkout is dirty, or 60s timeout → block + ask user
#
# Behavior when we already hold the lock:
#   - Check current branch matches the branch we locked on
#   - If branch changed: block and warn (branch switch requires confirmation)

STALE_SECS=300
WAIT_SECS=60
POLL_INTERVAL=5

input=$(cat)
session_id=$(echo "$input" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('session_id','unknown'))" 2>/dev/null)
[ -z "$session_id" ] && session_id="unknown"

# Record branch parentage when Claude creates a new branch, so ct can auto-inherit context.
_record_branch_parent() {
    local tool_name cmd new_branch repo parents_file
    tool_name=$(echo "$input" | python3 -c \
        "import sys,json; d=json.load(sys.stdin); print(d.get('tool_name',''))" 2>/dev/null)
    [[ "$tool_name" != "Bash" ]] && return
    cmd=$(echo "$input" | python3 -c \
        "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)
    if [[ "$cmd" =~ git[[:space:]]+checkout[[:space:]]+-b[[:space:]]+([^[:space:]]+) ]]; then
        new_branch="${BASH_REMATCH[1]}"
    elif [[ "$cmd" =~ git[[:space:]]+switch[[:space:]]+-c[[:space:]]+([^[:space:]]+) ]]; then
        new_branch="${BASH_REMATCH[1]}"
    else
        return
    fi
    repo=$(_repo_name) || return
    parents_file="$HOME/.claude/branch_parents"
    mkdir -p "$HOME/.claude"
    sed -i.bak "\|^${repo}/${new_branch} |d" "$parents_file" 2>/dev/null
    echo "${repo}/${new_branch} ${session_id}" >> "$parents_file"
}
_record_branch_parent

_git_root() { git rev-parse --show-toplevel 2>/dev/null; }
_lock_file() { local r; r=$(_git_root) && echo "${r}/.git/.claude-lock"; }
_now() { date +%s; }
_branch() { git branch --show-current 2>/dev/null; }

_read_lock() {
    local lf="$1"
    [ -f "$lf" ] || return 1
    read -r _lock_sid _lock_ts _lock_branch < "$lf"
}

_is_stale() { [ $(( $(_now) - $1 )) -gt $STALE_SECS ]; }

_acquire() {
    local branch; branch=$(_branch)
    echo "$session_id $(_now) $branch" > "$lf"
}

_has_uncommitted() {
    local root; root=$(_git_root) || return 0
    ! git -C "$root" diff --quiet 2>/dev/null || ! git -C "$root" diff --cached --quiet 2>/dev/null
}

_repo_name() { basename "$(_git_root)" 2>/dev/null; }

lf=$(_lock_file) || exit 0   # not a git repo → skip

if _read_lock "$lf"; then
    if [ "$_lock_sid" = "$session_id" ]; then
        # We hold the lock — check the branch hasn't changed
        cur_branch=$(_branch)
        if [ -n "$cur_branch" ] && [ -n "$_lock_branch" ] && [ "$cur_branch" != "$_lock_branch" ]; then
            echo "" >&2
            echo "🛑 BRANCH CHANGED: this session was locked to '${_lock_branch}' but now on '${cur_branch}'." >&2
            echo "   The branch changed without confirmation. Please verify this is intentional." >&2
            echo "   To proceed: run 'git checkout ${cur_branch}' to confirm, then retry your task." >&2
            exit 1
        fi
        _acquire; exit 0
    fi

    if _is_stale "$_lock_ts"; then
        _acquire; exit 0
    fi

    # ── Another active session holds the lock ──────────────────────────────
    age=$(( $(_now) - _lock_ts ))
    short_sid="${_lock_sid:0:8}"
    cur_branch=$(_branch)
    repo=$(_repo_name)

    echo "" >&2
    echo "┌────────────────────────────────────────────────────────────────┐" >&2
    echo "│  ⚠️  REPO LOCK — another Claude session is actively editing     │" >&2
    printf "│  Session %-8s… on branch %-20s %3ds ago  │\n" \
        "$short_sid" "'${_lock_branch}'" "$age" >&2
    echo "└────────────────────────────────────────────────────────────────┘" >&2
    echo "" >&2

    if [ -n "$cur_branch" ]; then
        wt_parent=$(dirname "$(_git_root)")
        echo "  💡 If this task doesn't need builds/tests, use a worktree:" >&2
        echo "     git worktree add ${wt_parent}/${repo}-wt ${cur_branch}" >&2
    fi
    echo "" >&2
    echo "  ⏳ Waiting up to ${WAIT_SECS}s for the other session to finish..." >&2

    deadline=$(( $(_now) + WAIT_SECS ))
    while [ $(_now) -lt $deadline ]; do
        sleep $POLL_INTERVAL
        _read_lock "$lf"
        lock_gone=$?
        if [ "$lock_gone" -ne 0 ] || _is_stale "$_lock_ts"; then
            echo "" >&2
            if _has_uncommitted; then
                echo "🛑 Lock is free but the checkout has uncommitted changes." >&2
                echo "   Run 'git status' to review before continuing." >&2
                exit 1
            fi
            echo "✅ Lock acquired — proceeding." >&2
            _acquire; exit 0
        fi
        remaining=$(( deadline - $(_now) ))
        age=$(( $(_now) - _lock_ts ))
        echo "  ...still waiting (${remaining}s left, other session active ${age}s ago)" >&2
    done

    echo "" >&2
    echo "🛑 Could not acquire the repo lock after ${WAIT_SECS}s." >&2
    echo "   Session ${short_sid}… is still active." >&2
    echo "   Options:" >&2
    echo "     • Wait for the other session to finish, then retry" >&2
    echo "     • Use a worktree (see suggestion above)" >&2
    echo "     • Force-clear: rm \$(git rev-parse --git-dir)/.claude-lock" >&2
    exit 1
else
    _acquire; exit 0
fi
