#!/bin/bash
# Toggle copy-mode on the most recently used client, for a single BTT gesture:
# one gesture scrolls back, the same gesture returns to the prompt.
tty=$(tmux list-clients -F '#{client_activity} #{client_tty}' | sort -rn | head -1 | awk '{print $2}')
[ -n "$tty" ] || exit 0
pane=$(tmux display-message -p -c "$tty" '#{pane_id}')
if [ "$(tmux display-message -p -t "$pane" '#{pane_in_mode}')" = 1 ]; then
    tmux send-keys -t "$pane" -X cancel
else
    tmux copy-mode -e -t "$pane"
fi
