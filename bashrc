
myhostname=`hostname -f`
datacenter=""
box_id_str="$myhostname"
cur_arch=$(arch)
processor=$(sysctl -a 2>/dev/null | grep brand)

# Dynamically find srpub directory
if [[ -n "$BASH_SOURCE" ]]; then
    SRPUB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
elif [[ -n "$0" && "$0" != "-bash" && "$0" != "bash" && "$0" != "-zsh" && "$0" != "zsh" ]]; then
    SRPUB_DIR="$(cd "$(dirname "$0")" && pwd)"
else
    # Fallback: try to find srpub in common locations
    if [[ -d "$HOME/srpub" ]]; then
        SRPUB_DIR="$HOME/srpub"
    elif [[ -d "$HOME/sam/srpub" ]]; then
        SRPUB_DIR="$HOME/sam/srpub"
    elif [[ -d "$(pwd)/srpub" ]]; then
        SRPUB_DIR="$(pwd)/srpub"
    else
        echo "Warning: Could not determine srpub directory location"
        SRPUB_DIR="$HOME/srpub"  # default fallback
    fi
fi

export PATH=${PATH}:$HOME/bin
export PATH=${PATH}:$HOME/scripts
export PATH=${PATH}:$HOME/customize
export PATH=${PATH}:$SRPUB_DIR
export PATH=${PATH}:$SRPUB_DIR/pytools
export PYTHONPATH=${PYTHONPATH}:$HOME/customize
export PYTHONPATH=${PYTHONPATH}:$SRPUB_DIR
export PYTHONPATH=${PYTHONPATH}:$SRPUB_DIR/pytools
export PYTHONUNBUFFERED="1"

# git initialization (only write if unset, so per-machine overrides stick)
# GIT_TERMINAL_PROMPT=0 prevents credential helpers from prompting during shell init
GIT_TERMINAL_PROMPT=0 git config --global --get core.editor >/dev/null 2>&1 || git config --global core.editor "vim"
GIT_TERMINAL_PROMPT=0 git config --global --get user.name >/dev/null 2>&1 || git config --global user.name "Samuel Russell"
#git config --global user.email "foobar@foobar.foo"

export KUBE_EDITOR='vim'

export SR_LOGS_VERBOSE=false
export SR_LOGS_PLAIN=true

############################################################
#     ZSH stuff
############################################################
shell=$SHELL
if [[ $shell == *zsh* ]]; then
    echo "Detected shell zsh"
    setopt NO_CASE_GLOB
    setopt AUTO_CD

    # history
    setopt EXTENDED_HISTORY
    export HISTFILE=${ZDOTDIR:-$HOME}/.zsh_history
    export SAVEHIST=5000
    # append to history
    setopt APPEND_HISTORY
    # Write history as typed not at exit
    setopt INC_APPEND_HISTORY
    # dont save space-prefixed commands into hist
    setopt HIST_IGNORE_SPACE

    export CLICOLOR=1

    # time: show only total elapsed time
    TIMEFMT='%*E'
fi

# bash: show only total elapsed time
TIMEFORMAT='%R'



############################################################
#     History
############################################################
# Generate unique 4-character session ID
if [[ -z "$SESSION_ID" ]]; then
  export SESSION_ID=$(LC_ALL=C tr -dc 'a-zA-Z0-9' < /dev/urandom | head -c 4)
fi

# Set terminal tab name to session ID
if [[ "$TERM_PROGRAM" == "Apple_Terminal" ]]; then
  printf "\e]1;%s\a" "[$SESSION_ID]"
elif [[ -n "$TMUX" ]]; then
  tmux rename-window "[$SESSION_ID]" 2>/dev/null
else
  printf "\e]0;%s\a" "[$SESSION_ID]"
fi

# Use prompt command to log all bash to files in .logs
BASH_LOGS_DIR="${BASH_LOGS_DIR:-$HOME/.logs}"
mkdir -p "$BASH_LOGS_DIR"
# These logs retain command lines indefinitely; keep them owner-only so a
# missed redaction (see below) isn't world-readable in backups/screen-shares.
chmod 700 "$BASH_LOGS_DIR" 2>/dev/null

# Redact potential secrets in commands - keeps first 4 chars of value, replaces rest with ***
# Best-effort only: novel secret shapes can still slip through, which is why the
# log files themselves are locked down to mode 600 above/below.
# Set SRPUB_NO_REDACT=1 to disable (e.g. if your sed doesn't support the 'i' flag)
redact_secrets() {
  local cmd="$1"
  if [ "${SRPUB_NO_REDACT:-0}" = "1" ]; then
    echo "$cmd"
    return
  fi
  echo "$cmd" | sed -E \
    -e 's/([A-Za-z_]*(_)?(PASSWORD|SECRET|TOKEN|API_KEY|APIKEY|OAUTH|AUTH_|CREDENTIAL|PRIVATE_KEY)[A-Za-z_]*=)([^[:space:]]{4})[^[:space:]]*/\1\4****REDACTED*****/gi' \
    -e 's/(AKIA[0-9A-Z]{4})[0-9A-Z]{12,}/\1****REDACTED*****/g' \
    -e 's/([Bb]earer )([A-Za-z0-9._-]{4})[A-Za-z0-9._-]{8,}/\1\2****REDACTED****/g' \
    -e 's/([Bb]asic )([A-Za-z0-9+/]{4})[A-Za-z0-9+/=]{8,}/\1\2****REDACTED****/g' \
    -e 's#([a-zA-Z][a-zA-Z0-9+.-]*://[^:/@[:space:]]+:)[^@[:space:]]+@#\1****REDACTED****@#g' \
    -e 's/(curl .*(-u|--user)[ =][^:[:space:]]+:)[^[:space:]]+/\1****REDACTED****/g' \
    -e 's/(mysql[a-z]* .*-p)[^[:space:]]+/\1****REDACTED****/g' \
    -e 's/([A-Za-z_]=[0-9a-fA-F]{4})[0-9a-fA-F]{28,}([[:space:]]|$)/\1****REDACTED*****\2/g'
}

prompt_command () {
  if [ "$(id -u)" -ne 0 ]; then
    if [[ "$shell" == *zsh* ]]; then
      NEWLINE=$(history -1)
    else
      NEWLINE=$(history 1)
    fi
    PCLOGNAME="$BASH_LOGS_DIR/bash-history-${myhostname}-$(date "+%Y-%m-%d").log"
    if [[ -e $PCLOGNAME ]]; then
      LASTLINE=$(tail -n 1 $PCLOGNAME)
    else
      LASTLINE=''
    fi
    # Skip space-prefixed commands (check if cmd starts with space after "123  " prefix)
    local cmd="${NEWLINE#*[0-9]  }"
    if [[ "$cmd" == " "* ]]; then
      return
    fi

    # Redact any secrets
    local safe_line=$(redact_secrets "$NEWLINE")
    local was_redacted=$([[ "$safe_line" != "$NEWLINE" ]] && echo 1 || echo 0)

    # Skip if already logged (compare redacted versions)
    if [[ "$LASTLINE" == *"$safe_line"* ]]; then
      return
    fi

    # Warn if we redacted something
    if [[ "$was_redacted" == "1" ]]; then
      printf '\033[93m[possible secret redacted from history log]\033[0m\n' >&2
    fi

    # Create new log files owner-only; harmless cheap chmod for existing ones.
    ( umask 077; echo "$(date "+%Y-%m-%d.%H:%M:%S") [${SESSION_ID}] $safe_line" >> "$PCLOGNAME" )
    chmod 600 "$PCLOGNAME" 2>/dev/null
  fi
}
if [[ "$shell" == *zsh* ]]; then
  # Remove any existing entries, then add once
  precmd_functions=("${(@)precmd_functions:#prompt_command}")
  precmd_functions+=(prompt_command)
else
  export PROMPT_COMMAND='prompt_command'
fi
alias fullhistory="cat \"\${BASH_LOGS_DIR:-\$HOME/.logs}\"/* | grep '^20' | sort"
hist() {
    fullhistory | grep_and $@ | tail -n 30
}
# Analytics dashboard over the ~/.logs history (top commands, by-hour, aliases)
alias logstats='$SRPUB_DIR/pytools/logstats.py'
alias logtail='$SRPUB_DIR/pytools/logtail.py'
alias keepawake='$SRPUB_DIR/pytools/keepawake.py'
alias peek='$SRPUB_DIR/pytools/peek.py'
alias k='$SRPUB_DIR/pytools/peek.py'

# Disk usage analysis + reclaimable-space report (read-only; --clean to free)
alias diskfree='$SRPUB_DIR/pytools/diskfree.py'

# big normal history
export HISTSIZE=9000
export HISTFILESIZE=$HISTSIZE
export HISTCONTROL=ignorespace:ignoredups

############################################################
#     Generic/Personal
############################################################
alias ..="cd .."
alias ...="cd ../.."
alias ....="cd ../../.."
alias .....="cd ../../../.."
alias ......="cd ../../../../.."
alias .......="cd ../../../../../.."
alias ........="cd ../../../../../../.."
alias .........="cd ../../../../../../../.."
alias ..........="cd ../../../../../../../../.."
alias ...........="cd ../../../../../../../../../.."
alias ............="cd ../../../../../../../../../../.."

alias less='less -R'
alias grep='grep --line-buffered --exclude=\*svn\* --color=auto'
alias igrep='grep -i --line-buffered --exclude=\*svn\* --color=auto'
#alias jq='jq --unbuffered'

rebash() {
  # Save the current environment information
  local current_conda_env=""
  local current_pyenv_env=""

  # Check for conda environment
  if [[ -n $CONDA_DEFAULT_ENV ]]; then
    current_conda_env="$CONDA_DEFAULT_ENV"
    echo "Currently in condaenv $current_conda_env"
  fi

  # Check for pyenv environment
  if [[ -n $VIRTUAL_ENV ]]; then
    current_pyenv_env="$VIRTUAL_ENV"
    echo "Currently in pyenv $current_pyenv_env"
  fi

  # Reload the appropriate shell configuration
  if [[ $SHELL == *zsh* ]]; then
    echo "Currently in zsh, reloading configuration..."
    source ~/.zshrc
  else
    echo "Currently in bash, reloading configuration..."
    source ~/.bashrc
  fi

  # Restore conda environment if it was active
  if [[ -n $current_conda_env && $current_conda_env != "base" ]]; then
    echo "Restoring conda environment: $current_conda_env"
    conda activate "$current_conda_env"
  fi

  # Restore pyenv environment if it was active
  if [[ -n $current_pyenv_env ]]; then
    echo "Restoring pyenv environment: $current_pyenv_env"
    source "${current_pyenv_env}/bin/activate"
  fi
}

alias addheretopath='export PATH=$PATH:`pwd`'
alias sparse="sed -n '0~10p'"
lsr() {
    ls -lth $@ | head -n 10
}
lsl() {
    ls -l $@
}

tmptmp() {
    rm -rf /tmp/tmp/
    mkdir -p /tmp/tmp/
    cd /tmp/tmp/
}

teelogs() {
    local logname="/tmp/$(date +%Y%m%d_%H%M%S).txt"
    echo "%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%"
    echo "Tee-ing to $logname" >&2
    echo "%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%"
    tee "${logname}"
}


color_code_files() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        GREP_COLOR=95 GREP_COLORS='mt=95' grep --color=always -E ".*(py|js|yaml|go|thrift|proto|cql|cc|cs|hh|hpp|vue|ts|tsx|ipynb|html|sh|tf|css|jsx):"
    else
        cat # pass-through for Linux
    fi
}

# =============================================================================
# Search (content search: grep / ripgrep)
# =============================================================================

CODE_EXTS="py,js,yaml,go,thrift,proto,cql,cc,cs,hh,hpp,vue,ts,tsx,ipynb,html,sh,tf,css,jsx,astro"
_grep_code_includes() { echo "$CODE_EXTS" | tr ',' '\n' | sed 's/^/--include=*./' | tr '\n' ' '; }
_rg_code_globs=()
if [ -n "$ZSH_VERSION" ]; then
    for _ext in ${(s:,:)CODE_EXTS}; do _rg_code_globs+=(-g "*.$_ext"); done
else
    IFS=',' read -r -a _arr <<< "$CODE_EXTS"
    for _ext in "${_arr[@]}"; do _rg_code_globs+=(-g "*.$_ext"); done
fi

# grep-based (o-prefix)
oshere() {
    grep --color=always -iI --exclude-dir={node_modules,build,.meteor,.mypy_cache,.env,bazel-venvs,.venv,.astro,frontend_dist} * 2>/dev/null -e "$1" ${@:2}
}
osearch() {
    grep --color=always -iIr --exclude-dir={node_modules,build,.meteor,.mypy_cache,.env,bazel-venvs,.venv,.astro,frontend_dist} . 2>/dev/null -e "$1" ${@:2}
}
osc() {
    osearch "$1" ${@:2} $(_grep_code_includes) | color_code_files
}
osch() {
    oshere "$1" ${@:2} $(_grep_code_includes) | color_code_files
}
oscw() {
    osc "\<$1\>" ${@:2}
}
oscnear() {
    osc $@ -A 2 -B 2
}
osearch_and() {
    grep -E -iIr * -e "$1.*$2|$2.*$1"
}
alias search_case='grep -Ir * -e'
osearch_struct () {
    osearch "} $1;"
    osearch "$1" | antigrep "//" | grep struct
}
osearch_func () {
    osearch $1 | antigrep "=" ";" "//" "if" "||" "@" "\.py" | grep -i $1
}

# ripgrep-based (rg-prefix)
rgsearch() {
    rg --color=always --no-heading -i "$1" "${@:2}" | sed 's|^|./|'
}
rghere() {
    rg --color=always --no-heading -i --max-depth 1 "$1" "${@:2}" | sed 's|^|./|'
}
rgsc() {
    rg --color=always --no-heading -i "${_rg_code_globs[@]}" "$1" "${@:2}" | sed 's|^|./|'
}
rgsch() {
    rg --color=always --no-heading -i --max-depth 1 "${_rg_code_globs[@]}" "$1" "${@:2}" | sed 's|^|./|'
}
rgscw() {
    rgsc -w "$1" "${@:2}"
}
rgscnear() {
    rgsc -C 2 "$@"
}
rgsearch_and() {
    rg --color=always --no-heading -i "$1.*$2|$2.*$1" "${@:3}" | sed 's|^|./|'
}

# auto-switch: use ripgrep if available, else grep
if command -v rg &>/dev/null; then
    alias search=rgsearch shere=rghere sc=rgsc sch=rgsch scw=rgscw scnear=rgscnear search_and=rgsearch_and
else
    echo "warning: ripgrep not installed, search/sc using grep (slower). Install: brew install ripgrep / apt install ripgrep" >&2
    alias search=osearch shere=oshere sc=osc sch=osch scw=oscw scnear=oscnear search_and=osearch_and
fi

# =============================================================================
# Grep helpers
# =============================================================================

alias grep_ips="grep -o '[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}'"
antigrep() {
    local IFS="|"; grep -i -E -v -e "$*";
}
grep_or() {
    local IFS="|"; grep -i -E -e "$*";
}
grep_and() {
    if [ $# -eq 0 ]; then
        cat
        return
    fi
    local result
    result=$(grep -i -e "$1")
    shift
    while [ $# -gt 0 ]; do
        result=$(echo "$result" | grep -i -e "$1")
        shift
    done
    echo "$result"
}
search_or() {
    grep -E -iIr * -e "$1|$2"
}
alias notests='antigrep "/tests/" "/test/" "/script/" "build/lib.linux" "_test.go" "/mocks/" ".gen" "env_docs" "./go-build/" "/_build/" "/.tmp/" '
alias nobuildcache='antigrep "\.pyc" "\./vendor/"  "\./go-build/\.go/" "./node_modules/" '

# =============================================================================
# Locate (file search: find / fd)
# =============================================================================

# find-based (o-prefix)
oloc() {
    find . -iname "*$1*" 2>/dev/null | nobuildcache | highlight $1
}
oshallowloc() {
    find . -iname "*$1*" -maxdepth 3 2>/dev/null | nobuildcache | highlight $1
}
odeeploc() {
    find . -iname "*$1*" -maxdepth 6 2>/dev/null | nobuildcache | highlight $1
}

# fd-based
_fd_cmd=""
if command -v fd &>/dev/null; then _fd_cmd=fd
elif command -v fdfind &>/dev/null; then _fd_cmd=fdfind; fi

_fd_highlight() {
    # bold+underline the match without resetting surrounding colors
    sed -E "s/($1)/$(printf '\033[1;4m')\1$(printf '\033[22;24m')/gi"
}
fdloc() {
    $_fd_cmd --color=always -i --hidden --exclude .git "$1" "${@:2}" | _fd_highlight "$1"
}
fdshallowloc() {
    $_fd_cmd --color=always -i --hidden --exclude .git --max-depth 3 "$1" "${@:2}" | _fd_highlight "$1"
}
fddeeploc() {
    $_fd_cmd --color=always -i --hidden --exclude .git --max-depth 6 "$1" "${@:2}" | _fd_highlight "$1"
}
aloc() {
    $_fd_cmd --color=always -i --hidden --no-ignore --exclude .git "$1" "${@:2}" | _fd_highlight "$1"
}

# auto-switch: use fd if available, else find
if [ -n "$_fd_cmd" ]; then
    alias loc=fdloc shallowloc=fdshallowloc deeploc=fddeeploc
else
    echo "warning: fd not installed, loc/shallowloc/deeploc using find (slower). Install: brew install fd / apt install fd-find" >&2
    alias loc=oloc shallowloc=oshallowloc deeploc=odeeploc
fi

# =============================================================================
# Interactive pickers (fzf) - opt-in helper used by gco/gbd/cdd/goto.
# Preserves the existing "try to match, act, else fail" behavior: the only
# change is that an AMBIGUOUS substring (>1 match) opens an interactive fzf
# picker instead of silently grabbing the first one. Unique match acts
# immediately (no UI); no match returns nonzero so the caller falls through.
# =============================================================================
_have_fzf() { command -v fzf >/dev/null 2>&1; }

# Resolve one candidate from stdin that matches query $1 (substring, like the
# old grep). 0 matches -> return 1; exactly 1 -> echo it; >1 -> interactive fzf
# if installed, else the old first-match behavior.
_pick_match() {
    local query="$1"
    local matches
    matches=$(grep -i -- "$query" 2>/dev/null)
    [ -z "$matches" ] && return 1
    if [ "$(printf '%s\n' "$matches" | grep -c .)" -eq 1 ]; then
        printf '%s\n' "$matches"
    elif _have_fzf; then
        printf '%s\n' "$matches" | fzf --height=40% --reverse --query="$query"
    else
        printf '%s\n' "$matches" | head -n 1
    fi
}

# Fuzzy reverse-search over the ~/.logs command history. On zsh the chosen
# command is pushed onto the edit buffer (print -z) so you can tweak before
# running; elsewhere it's printed.
fh() {
    _have_fzf || { echo "fzf required for fh (brew install fzf)" >&2; return 1; }
    local sel
    sel=$(fullhistory \
        | sed -E 's/^[0-9.]+ \[[^]]*\] +[0-9]* +//' \
        | awk '!seen[$0]++' \
        | fzf --height=40% --reverse --tac --query="$*")
    [ -z "$sel" ] && return
    if [ -n "$ZSH_VERSION" ]; then
        print -z -- "$sel"
    else
        echo "$sel"
    fi
}

# =============================================================================

function duf {
    du -sk "$@" | sort -n | while read size fname; do for unit in k M G T P E Z Y; do if [ $size -lt 1024 ]; then echo -e "${size}${unit}\t${fname}"; break; fi; size=$((size/1024)); done; done
}
function dufa {
    # collect into array so names with spaces don't word-split
    local entries=()
    while IFS= read -r f; do entries+=("$f"); done < <(ls -A1)
    duf "${entries[@]}"
}

# Use brew/apt installed watch - its better
# watch () {
#   for i in `seq 99999`; do $1 $2 $3 $4 $5 $6 $7 $8 $9; sleep 0.5; done 
# }

# Base function - run command n times
nce() {
    local n=$1
    shift
    for ((i=1; i<=n; i++)); do
        "$@"
    done
}

# Run command twice (uses nce)
twice() {
    nce 2 "$@"
}

# Run command three times (uses nce)
thrice() {
    nce 3 "$@"
}


goto () {
    local choice
    choice=$(find . 2>/dev/null | _pick_match "$1")
    if [ -n "$choice" ]; then
        if [ -d "$choice" ]; then
            cd "$choice"
        else
            cd "$(dirname "$choice")"
        fi
    fi
}

locvim () {
    file=`find -name $1 | head -n 1`
    vim $file
}
alias lvim='locvim'
alias kvim='vim -S ~/.kernelvimrc'
highlight () {
    GREP_COLOR=34 GREP_COLORS='mt=34' grep -i --line-buffered --color=always -E "${1}|$"
}
highlightline () {
    GREP_COLOR=34 GREP_COLORS='mt=34' grep -i --line-buffered --color -E ".*${1}.*|$"
}
highlightred () {
    grep -i --line-buffered --color=always -E "${1}|$"
}
highlightlinered () {
    grep -i --line-buffered --color=always -E ".*${1}.*|$"
}
highlightyellow () {
    GREP_COLOR=93 GREP_COLORS='mt=93' grep -i --line-buffered --color=always -E "${1}|$"
}
highlightgreen () {
    GREP_COLOR='1;32' GREP_COLORS='mt=1;32' grep -i --line-buffered --color=always -E "${1}|$"
}
highlightgray () {
    GREP_COLOR=90 GREP_COLORS='mt=90' grep -i --line-buffered --color=always -E "${1}|$"
}
firstwordyellow() {
    GREP_COLORS='mt=93'  grep --color=always -E '.*:'
}
alias color='$SRPUB_DIR/pytools/colorstrings.py'
alias green='$SRPUB_DIR/pytools/colorstrings.py green'
alias blue='$SRPUB_DIR/pytools/colorstrings.py blue'
alias red='$SRPUB_DIR/pytools/colorstrings.py red'
alias yellow='$SRPUB_DIR/pytools/colorstrings.py yellow'
alias rainbow='$SRPUB_DIR/pytools/colorstrings.py rainbow'
alias blink='$SRPUB_DIR/pytools/colorstrings.py blink'

alias asdf='fortune'
alias frak='fortune'

extract () {
   if [ -f $1 ] ; then
       case $1 in
           *.tar.bz2)   tar xvjf $1    ;;
           *.tar.gz)    tar xvzf $1    ;;
           *.bz2)       bunzip2 $1     ;;
           *.rar)       unrar x $1       ;;
           *.gz)        gunzip $1      ;;
           *.tar)       tar xvf $1     ;;
           *.tbz2)      tar xvjf $1    ;;
           *.tgz)       tar xvzf $1    ;;
           *.zip)       unzip $1       ;;
           *.Z)         uncompress $1  ;;
           *.7z)        7z x $1        ;;
           *)           echo "don't know how to extract '$1'..." ;;
       esac
   else
       echo "'$1' is not a valid file!"
   fi
}
alias make_tar='tar -cvzf'

dofrom() {
    orig=`pwd`
    cd $1
    ${@:2}
    code=$?
    cd $orig
    return $code
}

# parsing helper
last_word() {
    awk 'NF>1{print $NF}'
}
first_word() {
    cut -d' ' -f1
}
nthword() {
    if [ $1 -lt "0" ]; then
        index="$(expr `wc -w` + $1)"
        echo $index
    else
        index=$1
    fi
    fcut="-f$index"
    echo $fcut
    cut -d" " $fcut
}
allbutfirstword() {
    cut -d" " -f1 --complement
}
allbutlastword() {
    sed 's/[^ ]*$//'
}

cdd() {
    cd $1
    if [ $? -eq 1 ]; then
        substr=$(ls -d */ 2>/dev/null | _pick_match "$1")
        if [ -n "$substr" ]; then
            echo "auto-matching directory $substr" | yellow
            cd $substr
        fi
    fi
}
vim() {
    # Enable bash-style 0-indexed arrays in zsh if needed
    [[ -n "${ZSH_VERSION:-}" ]] && setopt local_options KSH_ARRAYS

    local target="$1"

    # If file exists as-is, just open it
    if [ -e "$target" ]; then
        command vim "$@"
        return
    fi

    # Get current directory as an absolute path
    local current_dir=$(pwd)

    # Split paths into arrays (now works for both bash and zsh with KSH_ARRAYS)
    if [[ -n "$BASH_VERSION" ]]; then
        IFS='/' read -ra current_parts <<< "$current_dir"
        IFS='/' read -ra target_parts <<< "$target"
    else
        # zsh with KSH_ARRAYS: split and filter out empty strings
        local temp_current=("${(@s:/:)current_dir}")
        local temp_target=("${(@s:/:)target}")
        local current_parts=()
        local target_parts=()
        for part in "${temp_current[@]}"; do
            [[ -n "$part" ]] && current_parts+=("$part")
        done
        for part in "${temp_target[@]}"; do
            [[ -n "$part" ]] && target_parts+=("$part")
        done
    fi

    # Try matching suffixes of current path with prefixes of target path
    local best_match_len=0
    local current_len=${#current_parts[@]}
    local target_len=${#target_parts[@]}

    # Check each possible suffix of current path
    for ((i=1; i<=$current_len; i++)); do
        local match_len=0
        # Check if this suffix matches the prefix of target
        for ((j=0; j<i && j<target_len; j++)); do
            local curr_idx=$((current_len - i + j))
            if [[ "${current_parts[$curr_idx]}" == "${target_parts[$j]}" ]]; then
                ((match_len++))
            else
                break
            fi
        done

        # If we matched all positions we checked, this is a valid overlap
        if [[ $match_len -gt 0 && $match_len -eq $((j)) ]]; then
            if [[ $match_len -gt $best_match_len ]]; then
                best_match_len=$match_len
            fi
        fi
    done

    # If we found an overlap, strip it from the target path
    if [[ $best_match_len -gt 0 ]]; then
        local new_target=""
        for ((i=$best_match_len; i<target_len; i++)); do
            if [[ -n "$new_target" ]]; then
                new_target="$new_target/${target_parts[$i]}"
            else
                new_target="${target_parts[$i]}"
            fi
        done

        if [[ -n "$new_target" && -e "$new_target" ]]; then
            echo "Stripping redundant path prefix, opening: $new_target" | yellow
            command vim "$new_target" "${@:2}"
            return
        fi
    fi

    # If nothing worked, just pass through to vim (might create new file or error)
    command vim "$@"
}


# Colorized cat
ccat() {
    if command -v pygmentize >/dev/null 2>&1; then
        pygmentize -O style=vim -l python "$1"
    else
        cat "$1"
    fi
}


alias difftotest='arc diff -m "just to test" --plan-changes'
alias diffrebase='arc diff -m "rebase"'
alias difftests='arc diff -m "fix tests"'
alias diffcomments='arc diff -m "update comments"'
diffit() {
    arc diff -m "$1 $2 $3 $4 $5"
}


alias kbn='killbyname.py'
alias stripcolors='sed -r "s/\x1B\[([0-9]{1,2}(;[0-9]{1,2})?)?[mGK]//g"'
alias utcnow='date -u'
alias epochnow='python -c "import time; print(int(time.time()))"'
alias epochnowmillis='python -c "import time; print(1000 * int(time.time()))"'
alias epoch="epoch.py"
alias tmx='tmux attach || tmux new'

who_is_on_port() {
    echo "if this is a mac"
    lsof -n -i4TCP:$1

    echo "netstat -tulpn"
    netstat -tulpn | grep $1

    echo "fuser $1/tcp"
    fuser $1/tcp
}

percent_free_swap() {
    free | grep 'Swap' | awk '{t = $2; f = $4; print (f/t)}'
}

alias author_of_past_500='git log HEAD~500...HEAD | grep Author | hist_common.py'
alias author_of_all_time='git log | grep Author | hist_common.py'

nolonglines() {
    awk 'length($0)<5000 {print $0}'
}
alias uuid='python3 -c "import uuid; print(uuid.uuid4())"'
uuids() {
    for i in `seq 20`; do uuid; done
}


jqm() {
    raw=`cat`
    echo $raw | jq -S -e $1 || printf "~~invalid json~~\n\n$raw\n"
}

jq_some() {
    while read line; do
        if [[ -n "$line" ]]; then
            (echo $line | jq . 2>/dev/null||echo $line)
        else
            echo $line
        fi
    done
}

gtv() {
    go test -v 2>&1 | highlightlinered "\<FAIL\>" | highlightlinered "panic" | highlightgreen "\<PASS\>" | highlightline "Unexpected Call" | highlightline "missing call"
}

docker_lightprune() {
    docker rmi $(docker images -f "dangling=true" -q)
    docker system prune
}

docker_fullprune() {
    docker system prune -a --volumes
}

list_all_services() {
    systemctl list-units --type=service --no-pager
}



#######################################################
# Git stuff
#######################################################

alias gb='git branch'
alias ggd='git diff'
alias grh='git reset --hard'
alias gcp='git cherry-pick'
alias gc='git commit'
alias gitlastdiff='git diff HEAD^ HEAD'

git_main_branch() {
   if git rev-parse refs/remotes/origin/HEAD &>/dev/null; then
       git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@'
   else
       echo "main"  # Default to main if no remote HEAD found
   fi
}
git_main_origin() {
    echo "origin/$(git_main_branch)"
}
githeaddiff() {
    git diff $(git_main_origin)...HEAD $@
}
alias gitbranchdiff='git diff $(git_main_origin) HEAD'

squashhead() {
    merge=`git merge-base HEAD $(git_main_origin)`
    git reset --soft ${merge}
    git commit -a -n
}
squashn() {
    if [ $# -eq 0 ]
    then
        echo "No arguments supplied: N is requred"
        return
    fi
    git reset --soft HEAD~${1}
    git commit -a -n
}

_worktree_path_for_branch() {
    # Print the worktree path for the given branch, or nothing if not in a worktree.
    local branch="$1"
    git worktree list --porcelain 2>/dev/null | awk -v b="refs/heads/$branch" '
        /^worktree / { path=$2 }
        $0 == "branch " b { print path; exit }
    '
}

primary() {
    # cd to the primary checkout. With no args, check out the current branch there.
    # With a branch arg, check out that branch on the primary checkout.
    local branch="${1:-$(git branch --show-current)}"
    local primary_path
    primary_path=$(git worktree list --porcelain 2>/dev/null | awk '/^worktree / {print $2; exit}')
    if [ -z "$primary_path" ]; then
        echo "Not in a git repo" | red; return 1
    fi
    if [ -z "$branch" ]; then
        cd "$primary_path"
    else
        cd "$primary_path" && git checkout "$branch"
    fi
}

gco() {
    local branch="$1"
    # If branch is checked out in a worktree, cd there instead of checking out.
    if [ -n "$branch" ] && [[ "$branch" != -* ]]; then
        local wt_path
        wt_path=$(_worktree_path_for_branch "$branch")
        if [ -n "$wt_path" ]; then
            echo "branch '$branch' is in worktree, cd-ing to $wt_path" | yellow
            cd "$wt_path"
            return
        fi
    fi
    git checkout $@
    if [ $? -eq 1 ]; then
        local substr
        substr=$(git branch | sed 's/^[+* ]*//' | _pick_match "$1")
        if [ -n "$substr" ]; then
            echo "auto-matching branch $substr" | yellow
            # Check worktree for the matched branch too
            local wt_path
            wt_path=$(_worktree_path_for_branch "$substr")
            if [ -n "$wt_path" ]; then
                echo "branch '$substr' is in worktree, cd-ing to $wt_path" | yellow
                cd "$wt_path"
            else
                git checkout $substr
            fi
        fi
    fi
}
gitcleanmain() {
    # Force reset main back to origin main
    git branch -f main origin/main
}

git_push_as_me() {
    git push https://srussell28@github.com/srussell28/srpub main:main
}

git_pre_push() {
    echo "override me pre-push"
}

with_ssh_remote() {
    local old ssh rc
    old=$(git remote get-url origin) || return 1
    # rewrite https://github.com/OWNER/REPO(.git) -> git@github.com:OWNER/REPO.git
    # Two-step: strip trailing .git first, then rewrite scheme — avoids non-greedy
    # quantifiers (+?) which BSD sed (macOS) rejects in ERE mode.
    ssh=$(sed -E 's#[.]git$##' <<<"$old" | sed -E 's#^https://github[.]com/([^/]+)/([^/]+)$#git@github.com:\1/\2.git#')
    echo "with_ssh_remote: origin $old -> $ssh" >&2
    git remote set-url origin "$ssh" || return 1
    "$@"
    rc=$?
    echo "with_ssh_remote: restoring origin -> $old" >&2
    git remote set-url origin "$old"
    return $rc
}

gitpush() {
    b=$(git branch --show-current)
    if [[ "$b" == "master" || "$b" == "main" ]];
    then
        echo "cannot push master/main";
        return 1;
    fi

    git_pre_push || return 1
    echo "pushing... $b"
    git push origin $b:$b 2>/dev/null || git push --force-with-lease origin $b:$b
}
gitqpush() {
    b=$(git branch --show-current)
    if [[ "$b" == "master" || "$b" == "main" ]];
    then
        echo "cannot push master/main";
        return 1;
    fi

    echo "quick-pushing... $b"
    git push origin $b:$b 2>/dev/null || git push --force-with-lease origin $b:$b
}

#rebase_master_push() {
#    fixgitbranch && git fetch && git rebase && qpush
#}

gnb() {
    if [ -z "$2" ]
    then
        gco -b $1 $(git_main_origin)
    else
        gco -b $1 $2
    fi
}
gbd() {
    local branch="$1"
    # Resolve branch name (with fuzzy match if needed) before doing anything.
    if ! git show-ref --verify --quiet "refs/heads/$branch" 2>/dev/null; then
        local matched
        matched=$(git branch | grep -v "^\*" | sed 's/^[+ ]*//' | _pick_match "$branch")
        if [ -n "$matched" ]; then
            echo "auto-matching branch $matched" | yellow
            branch="$matched"
        fi
    fi

    # If branch has a worktree, remove it first.
    if [ -n "$branch" ]; then
        local wt_path
        wt_path=$(_worktree_path_for_branch "$branch")
        if [ -n "$wt_path" ]; then
            echo "removing worktree at $wt_path for branch '$branch'" | yellow
            if ! git worktree remove --force "$wt_path" 2>/dev/null; then
                # Worktree dir is gone/corrupt (e.g. a stale Claude scratchpad).
                # Prune the dead ref so git lets us delete the branch.
                echo "worktree remove failed, pruning stale ref" | yellow
                git worktree prune
            fi
        fi
    fi

    git branch -D "$branch"
    if [ $? -eq 1 ]; then
        echo "failed to delete branch $branch" | red
        return 1
    fi

    # Kill any tmux claude session for this branch
    if [ -n "$branch" ]; then
        local repo=$(basename "$(git rev-parse --show-toplevel)" 2>/dev/null)
        local session_name="${repo}/${branch}"
        if tmux has-session -t "=$session_name" 2>/dev/null; then
            echo "Killing tmux claude session $session_name" | yellow
            tmux kill-session -t "=$session_name"
        fi
        # Clean up branch_sessions and branch_parents maps
        local key="${repo}/${branch}"
        local map_file="$HOME/.claude/branch_sessions"
        [ -f "$map_file" ] && sed -i.bak "\|^${key} |d" "$map_file"
        local parents_file="$HOME/.claude/branch_parents"
        [ -f "$parents_file" ] && sed -i.bak "\|^${key} |d" "$parents_file"
    fi
}

gl() {
    git log $@
    if [ $? -ne 0 ] && [ -n "$1" ]; then
        substr=`git branch | grep -v "^\*" | sed 's/^[+ ]*//' | grep $1 | xargs`
        if [ -n "$substr" ]; then
            echo "auto-matching branch $substr" | yellow
            git log $substr ${@:2}
        fi
    fi
}

function gits() {
    $SRPUB_DIR/pytools/git_awesome_status.py $@
}
alias gitmine="git log --format=short --author='Russell'"

gittrack() {
    if [ -z "$1" ]; then
        echo "tracking origin is required"
        return 1;
    fi
    git branch --set-upstream-to $1
}
gittrackmain() {
    gittrack $(git_main_origin)
}
alias gtm="gittrackmain"
gittrackself() {
    b=$(git branch --show-current)
    gittrack origin/$b
}

git_cleanup() {
  # https://gitbetter.substack.com/p/how-to-clean-up-the-git-repo-and
  git remote prune origin && git repack && git prune-packed && git reflog expire --expire=1.month.ago && git gc --aggressive
}

# Render a size in KiB as a human-readable string (matches duf's unit loop).
_human_kib() {
    local size=$1 unit
    for unit in K M G T P E Z Y; do
        if [ "$size" -lt 1024 ]; then echo "${size}${unit}"; return; fi
        size=$((size / 1024))
    done
}

# Reclaim disk space in a git repo (and its LFS cache), reporting how much
# the .git dir shrank. Pass --aggressive/-a to expire ALL reflog entries now
# (frees more, but throws away your undo/recovery history) and run an
# aggressive gc; otherwise reflog entries older than 2 weeks are expired.
gitgc() {
    if [[ $(is_git) != "$GIT_ENUM" ]]; then
        echo "gitgc: not inside a git work tree" >&2
        return 1
    fi

    local aggressive=0
    case "$1" in
        -a|--aggressive) aggressive=1 ;;
        "") ;;
        *) echo "gitgc: unknown option '$1' (use -a/--aggressive)" >&2; return 1 ;;
    esac

    local gitdir
    gitdir=$(git rev-parse --git-dir) || return 1
    local before
    before=$(du -sk "$gitdir" 2>/dev/null | cut -f1)

    # Drop stale remote-tracking refs, then let unreachable objects expire.
    git remote prune origin
    if [[ $aggressive -eq 1 ]]; then
        git reflog expire --expire=now --all
        git gc --prune=now --aggressive
    else
        git reflog expire --expire=2.weeks.ago --all
        git gc --prune=now
    fi

    # Trim the local LFS cache of files no longer referenced by recent commits.
    if command -v git-lfs >/dev/null 2>&1 && [ -d "$gitdir/lfs" ]; then
        git lfs prune
    fi

    local after saved
    after=$(du -sk "$gitdir" 2>/dev/null | cut -f1)
    saved=$((before - after))
    echo "gitgc: ${gitdir} $(_human_kib "$before") -> $(_human_kib "$after") (saved $(_human_kib "$saved"))"
}

git-halfway() {
    local sha1=$1
    local sha2=$2
    
    # Determine which SHA is earlier in history
    if git merge-base --is-ancestor $sha1 $sha2 2>/dev/null; then
        local start=$sha1
        local end=$sha2
    elif git merge-base --is-ancestor $sha2 $sha1 2>/dev/null; then
        local start=$sha2
        local end=$sha1
    else
        echo "Error: SHAs are not on the same branch/lineage"
        return 1
    fi
    
    local total=$(git rev-list --count ${start}..${end})
    local halfway=$((total / 2))
    
    echo "Commits between $start and $end: $total"
    echo "Halfway point: commit #$halfway"
    echo ""

    local halfway_sha=$(git rev-list ${start}..${end} | sed -n "${halfway}p")
    echo "$halfway_sha"
    
    # Show the commit info
    git log --oneline -1 $halfway_sha
} 

gfix() {
    vim $@;
    git add $@
}


#######################################################
# HG stuff
#######################################################

function hgs() {
    echo "****************************************************"
    hg bookmarks
    echo "****************************************************"
    hg status
    echo "****************************************************"
    hg sl
}

function hg_new_bookmark() {
    hg bookmark -r master $1
    hg update $1
}

hgco() {
    hg checkout $@
    if [ $? -ne 0 ]; then
        substr=`hg bookmarks | grep $1 | awk '{print $1}'`
        if [ -n "$substr" ]; then
            echo "auto-matching branch $substr" | yellow
            hg checkout $substr
            return
        fi
    fi
}

alias hglastdiff='hg show `hg id -i | cut -d"+" -f1`'
alias hgamend='hg amend'
alias hgctrllog='hg log arvr/projects/ctrl-r -l 100'
alias hgrebasemaster='hg pull --rebase -d master'
alias hgrebasewarm='hg pull --rebase -d fbcode/warm'
alias hgmine="hg log --user=samrussell@meta.com --limit 10"

# This is wrong
alias hgheaddiff='hglastdiff'

hgbd() {
    hg bookmark -d $@
    if [ $? -ne 0 ]; then
        substr=`hg bookmarks | grep $1 | awk '{print $1}'`
        if [ -n "$substr" ]; then
            echo "auto-matching branch $substr" | yellow
            hg bookmark -d $substr
            return
        fi
    fi
}

#######################################################
# Conda stuff
#######################################################

export DEFAULTENV=base
act() {
  # Check if conda is installed
  if command -v conda &> /dev/null; then
    conda deactivate 2>/dev/null
    conda deactivate 2>/dev/null

    # If no argument provided, check for environment.yml
    if [ -z "$1" ] && [ -f "environment.yml" ]; then
        local env=$(grep "^name:" environment.yml | cut -d: -f2 | tr -d '[:space:]')
        if [ -n "$env" ]; then
            echo "Found environment.yml, activating: $env"
            conda activate "$env"
            return
        fi
    fi
  fi

  if [ -z "$1" ]; then
    # Start from current directory and move up through parents
    local dir=$(pwd)
    while [ "$dir" != "/" ]; do
        # echo "act checking $dir"
        for venv_dir in .env .venv venv env; do
            if [ -f "$dir/$venv_dir/bin/activate" ]; then
                echo "Found venv in $dir/$venv_dir"
                source "$dir/$venv_dir/bin/activate"
                local project_name=$(basename "$dir")
                export VIRTUAL_ENV_PROMPT="($project_name) "
                PS1="($project_name) ${PS1#\(\(*\) \) }"
                return 0
            fi
        done

        if [ -d "$dir/bazel-venvs" ]; then
            echo "Found bazel-venvs in $dir/bazel-venvs"
            local venv=$(ls -1 "$dir/bazel-venvs" | head -1)
            if [ -n "$venv" ] && [ -f "$dir/bazel-venvs/$venv/bin/activate" ]; then
                echo "Activating venv: $venv"
                source "$dir/bazel-venvs/$venv/bin/activate"
                return
            fi
            return 0
        fi

        if [ -f "$dir/environment.yml" ]; then
            local env=$(grep "^name:" "$dir/environment.yml" | cut -d: -f2 | tr -d '[:space:]')
            if [ -n "$env" ]; then
                echo "Found $dir/environment.yml, activating: $env"
                conda activate "$env"
                return
            fi
        fi

        # Move up to parent directory
        dir=$(dirname "$dir")
    done
  fi

  local env="${1:-$DEFAULTENV}"
  if [ -z "$env" ]; then
      echo "No environment specified and DEFAULTENV not set"
      return 1
  fi

  echo "Activating environment: $env"
  conda activate "$env"
}
deact() {
  if command -v conda &> /dev/null; then
    conda deactivate 2>/dev/null
  elif [ -n "$VIRTUAL_ENV" ]; then
    deactivate
  else
    echo "No active environment to deactivate"
  fi
}

_resolve_host() {
    # Resolve a single hostname->IP or IP->hostname
    local query="$1"
    if echo "$query" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
        # IP -> hostname
        if command -v avahi-resolve &>/dev/null; then
            avahi-resolve -a "$query" 2>/dev/null | awk '{print $2}' && return
        fi
        if command -v dig &>/dev/null; then
            local name
            name=$(dig +short +time=2 +tries=1 -x "$query" 2>/dev/null | sed 's/\.$//')
            [ -n "$name" ] && echo "$name" && return
        fi
        echo "<unknown>"
    else
        # hostname -> IP (append .local if needed for mDNS)
        local host="$query"
        [[ "$host" != *.* ]] && host="${host}.local"
        if command -v avahi-resolve &>/dev/null; then
            avahi-resolve -n "$host" 2>/dev/null | awk '{print $2}' && return
        fi
        if command -v dns-sd &>/dev/null; then
            local result
            result=$(dns-sd -G v4 "$host" 2>/dev/null & local pid=$!; sleep 2; kill $pid 2>/dev/null; wait $pid 2>/dev/null)
            local ip
            ip=$(echo "$result" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | grep -v '^0\.' | tail -1)
            [ -n "$ip" ] && echo "$ip" && return
        fi
        # fallback: ping
        ping -c1 -W2 "$host" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1
    fi
}

scan_local_network() {
    # With an arg: resolve a single host
    if [ -n "$1" ]; then
        _resolve_host "$1"
        return
    fi

    # No args: scan the full network
    if command -v arp-scan &>/dev/null; then
        local iface=""
        [[ "$OSTYPE" == "darwin"* ]] && iface="--interface=en0"
        local scan
        scan=$(sudo arp-scan $iface --localnet 2>/dev/null | grep -E '^[0-9]+\.')
        [ -z "$scan" ] && echo "No hosts found" >&2 && return 1

        if command -v avahi-resolve &>/dev/null; then
            echo "$scan" | while read -r ip mac vendor; do
                local name
                name=$(avahi-resolve -a "$ip" 2>/dev/null | awk '{print $2}')
                printf "%-18s %-24s %s  %s\n" "$ip" "${name:--}" "$mac" "$vendor"
            done
        else
            echo "$scan"
        fi
    else
        echo "arp-scan not found. Install: brew install arp-scan / apt install arp-scan" >&2
        echo "Showing cached ARP entries:" >&2
        arp -a 2>/dev/null | grep -v incomplete
    fi
}

#######################################################
# Source control ambiguation
#######################################################
has_hg=false

GIT_ENUM=10
HG_ENUM=11
UNRECOGNIZED_ENUM=-1

function is_git() {
    git rev-parse --is-inside-work-tree 1>/dev/null 2>/dev/null
    if [[ $? -eq 0 ]]; then
        #echo "is git"
        echo $GIT_ENUM
    else
        hg root 1>/dev/null 2>/dev/null
        if [[ $? -eq 0 ]]; then
            #echo "is hg"
            echo $HG_ENUM
        else
            echo $UNRECOGNIZED_ENUM
        fi
    fi
}

function test_is_git() {
    typ=$(is_git)
    if [[ $typ = $GIT_ENUM ]]; then
        echo "git command"
    elif [[ $typ = $HG_ENUM ]]; then
        echo "hg command"
    else
        echo "no source control"
    fi
}

# Helper function to run python commands avoiding conflicts with local python files
python_avoidbadlocals() {
    local python_cmd="$1"
    shift
    local conflict_files=("types.py")
    
    local has_conflict=false
    for file in "${conflict_files[@]}"; do
        if [[ -f "$file" ]]; then
            has_conflict=true
            break
        fi
    done
    
    if [[ "$has_conflict" == true ]]; then
        local orig_dir=$(pwd)
        cd ..
        $python_cmd "$@"
        cd "$orig_dir"
    else
        $python_cmd "$@"
    fi
}

function gs() {
    typ=$(is_git)
    if [[ $typ = $GIT_ENUM ]]; then
        python_avoidbadlocals "$SRPUB_DIR/pytools/git_awesome_status.py" $@
    elif [[ $typ = $HG_ENUM ]]; then
        hgs $@
    else
        echo "no source control"
    fi
}

amend() {
    typ=$(is_git)
    if [[ $typ = $GIT_ENUM ]]; then
        git commit --amend -a --no-edit
    elif [[ $typ = $HG_ENUM ]]; then
        hg amend
    else
        echo "no source control"
    fi
}
qamend() {
    typ=$(is_git)
    if [[ $typ = $GIT_ENUM ]]; then
        git commit --amend -a --no-edit --no-verify
    elif [[ $typ = $HG_ENUM ]]; then
        hg amend
    else
        echo "no source control"
    fi
}
push() {
    typ=$(is_git)
    if [[ $typ = $GIT_ENUM ]]; then
        gitpush $@
    elif [[ $typ = $HG_ENUM ]]; then
        arc lint && jf submit
    else
        echo "no source control"
    fi
}
qpush() {
    typ=$(is_git)
    if [[ $typ = $GIT_ENUM ]]; then
        gitqpush $@
    elif [[ $typ = $HG_ENUM ]]; then
        jf submit
    else
        echo "no source control"
    fi
}

gd() {
    typ=$(is_git)
    if [[ $typ = $GIT_ENUM ]]; then
        git diff $@
    elif [[ $typ = $HG_ENUM ]]; then
        hg diff
    else
        echo "no source control"
    fi
}

lastdiff() {
    typ=$(is_git)
    if [[ $typ = $GIT_ENUM ]]; then
        gitlastdiff $@
    elif [[ $typ = $HG_ENUM ]]; then
        hglastdiff
    else
        echo "no source control"
    fi

}

headdiff() {
    typ=$(is_git)
    if [[ $typ = $GIT_ENUM ]]; then
        githeaddiff $@
    elif [[ $typ = $HG_ENUM ]]; then
        hgheaddiff
    else
        echo "no source control"
    fi
}

mine() {
    typ=$(is_git)
    if [[ $typ = $GIT_ENUM ]]; then
        gitmine
    elif [[ $typ = $HG_ENUM ]]; then
        hgmine
    else
        echo "no source control"
    fi

}

grm() {
    typ=$(is_git)
    if [[ $typ = $GIT_ENUM ]]; then
        local origin_main=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/||')
        if [[ -z "$origin_main" ]]; then
            echo "origin/HEAD not set. Run: git remote set-head origin --auto"
            return 1
        fi
        echo "Rebasing against $origin_main..."
        git fetch && git rebase "$origin_main"
    elif [[ $typ = $HG_ENUM ]]; then
        hgrebasewarm
    else
        echo "no source control"
    fi
}

gfrm() {
    git fetch && grm
}

#######################################################
# AWS Stuff
#######################################################


myec2() {
    echo "Checking instance $MY_EC2_INSTANCE_ID status..."

    # Get current instance state
    STATE=$(aws ec2 describe-instances \
        --instance-ids $MY_EC2_INSTANCE_ID \
        --query 'Reservations[0].Instances[0].State.Name' \
        --output text)

    echo "Current state: $STATE"


    if [[ "$STATE" != "running" ]]; then
        echo "Starting instance..."
        aws ec2 start-instances --instance-ids $MY_EC2_INSTANCE_ID
        
        # Wait for instance to be running
        echo "Waiting for instance to boot..."
        aws ec2 wait instance-running --instance-ids $MY_EC2_INSTANCE_ID
        
        # Extra wait for SSH to be ready
        echo "Waiting for SSH to be ready..."
        sleep 20
    fi

    # Get public DNS name
    PUBLIC_DNS=$(aws ec2 describe-instances \
        --instance-ids $MY_EC2_INSTANCE_ID \
        --query 'Reservations[0].Instances[0].PublicDnsName' \
        --output text)
    echo "public DNS: $PUBLIC_DNS"

    if [[ -z "$PUBLIC_DNS" ]] || [[ "$PUBLIC_DNS" == "None" ]]; then
        echo "Error: No public DNS found. Instance may not have a public IP."
        return 1
    fi

    echo "Connecting to: $MY_EC2_USERNAME@$PUBLIC_DNS"

    # SSH into the instance
    ssh -i $MY_EC2_PEM_FILE $MY_EC2_USERNAME@$PUBLIC_DNS
}

#######################################################
# MacOS Stuff
#######################################################

alias unfuck_touchbar="sudo pkill TouchBarServer"

rosetta() {
	env /usr/bin/arch -x86_64 /bin/bash --login
}
x86() {
	env /usr/bin/arch -x86_64 /bin/bash --login
}

unrosetta() {
	env /usr/bin/arch -arm64 /bin/bash --login
}
arm() {
	env /usr/bin/arch -arm64 /bin/bash --login
}

function mac_unquarantine() {
    xattr -d com.apple.metadata:kMDItemWhereFroms $1
    xattr -d com.apple.quarantine $1
}


############################################################
#     AI / LLM stuff
############################################################
opus() {
    claude --model opus $@
}
sonet() {
    claude --model sonnet $@
}

# Start claude, resuming session if it exists, otherwise start new.
# Stores the session mapping in ~/.claude/branch_sessions.
# Usage: claude_resume_or_new <key>
claude_resume_or_new() {
    local key="$1"
    local map_file="$HOME/.claude/branch_sessions"
    mkdir -p "$HOME/.claude"

    local claude_sid=""
    if [ -f "$map_file" ]; then
        claude_sid=$(grep "^${key} " "$map_file" | head -n 1 | cut -d' ' -f2)
    fi

    if [ -n "$claude_sid" ]; then
        echo "Resuming claude session $claude_sid for $key" | yellow
        claude --resume "$claude_sid"
        if [ $? -ne 0 ]; then
            echo "Stale session, starting fresh..." | red
            sed -i.bak "\|^${key} |d" "$map_file"
            claude_sid=""
        fi
    fi

    if [ -z "$claude_sid" ]; then
        claude_sid=$(uuidgen | tr '[:upper:]' '[:lower:]')
        echo "Starting new claude session $claude_sid for $key" | yellow
        echo "${key} ${claude_sid}" >> "$map_file"
        claude --session-id "$claude_sid"
    fi
}

ct() {
    local force_new=false
    local branch_arg=""
    local from_branch=""
    local resume_sid=""

    # Parse args; use positional-param slice so --from/--resume can consume the next token.
    # ${@:i:1} is 1-based and works in both bash and zsh (unlike C-style array indexing).
    local i=1
    while [[ $i -le $# ]]; do
        local arg="${@:$i:1}"
        case "$arg" in
            --new) force_new=true ;;
            --from)
                (( i++ ))
                from_branch="${@:$i:1}" ;;
            --resume)
                (( i++ ))
                resume_sid="${@:$i:1}" ;;
            --help|-h)
                echo "Usage: ct [branch] [--new] [--from <branch>] [--resume <session-id>]"
                echo ""
                echo "  Opens (or attaches to) a tmux+claude session for a git branch."
                echo "  Defaults to the current branch if none specified."
                echo ""
                echo "Options:"
                echo "  --new                  Kill any existing session and start fresh"
                echo "  --from <branch>        Inherit claude context from <branch> (use after merging)"
                echo "  --resume <session-id>  Resume a specific claude session by ID"
                echo ""
                echo "Examples:"
                echo "  ct                                  # attach/open session for current branch"
                echo "  ct sam/my-feature                   # switch to branch and open its session"
                echo "  ct --new                            # start fresh, discarding existing session"
                echo "  ct sam/new --from sam/old           # new branch, carry over old branch's context"
                echo "  ct --resume abc-123-def             # wire a specific session ID to current branch"
                return 0 ;;
            *) branch_arg="$arg" ;;
        esac
        (( i++ ))
    done

    local branch="${branch_arg:-$(git branch --show-current)}"
    if [ -z "$branch" ]; then
        echo "Cannot start ct from a detached HEAD. Specify a branch or checkout one first." | red
        return 1
    fi
    local repo
    repo="$(basename "$(git rev-parse --show-toplevel)")"
    local session_name="${repo}/${branch}"

    # Switch branch if specified and different from current
    if [ -n "$branch_arg" ]; then
        if ! git checkout "$branch" 2>/dev/null; then
            local match=$(git branch | sed 's/^[+* ]*//' | grep "$branch_arg" | head -n 1 | xargs)
            if [ -n "$match" ]; then
                echo "auto-matching branch $match" | yellow
                branch="$match"
                session_name="${repo}/${branch}"
                git checkout "$match" || return 1
            else
                echo "No branch matching '$branch_arg'" >&2
                return 1
            fi
        fi
    fi

    # Kill existing tmux session if --new
    if [ "$force_new" = true ] && tmux has-session -t "=$session_name" 2>/dev/null; then
        echo "Killing existing tmux session $session_name" | yellow
        tmux kill-session -t "=$session_name"
    fi

    # Attach to existing tmux session if one exists
    if tmux has-session -t "=$session_name" 2>/dev/null; then
        echo "Attaching to existing tmux session $session_name" | yellow
        sleep 0.5
        tmux attach -t "=$session_name"
        return
    fi

    local key="${repo}/${branch}"
    local map_file="$HOME/.claude/branch_sessions"

    # Clear old session mapping if --new
    if [ "$force_new" = true ] && [ -f "$map_file" ]; then
        sed -i.bak "\|^${key} |d" "$map_file"
    fi

    # --resume: wire a specific claude session ID to this branch
    if [ -n "$resume_sid" ]; then
        echo "Wiring claude session $resume_sid to ${key}" | yellow
        sed -i.bak "\|^${key} |d" "$map_file"
        echo "${key} ${resume_sid}" >> "$map_file"
    fi

    # --from: inherit session ID from another branch (e.g. after merging it)
    if [ -n "$from_branch" ]; then
        local from_key="${repo}/${from_branch}"
        local from_sid=""
        [ -f "$map_file" ] && from_sid=$(grep "^${from_key} " "$map_file" | head -n 1 | cut -d' ' -f2)
        if [ -n "$from_sid" ]; then
            echo "Inheriting claude session $from_sid from ${from_branch}" | yellow
            # Remove any existing mapping for the new branch, then add inherited one
            sed -i.bak "\|^${key} |d" "$map_file"
            echo "${key} ${from_sid}" >> "$map_file"
        else
            echo "No session found for ${from_branch}, starting fresh" | yellow
        fi
    fi

    # Auto-inherit parent session if this branch was spawned by another Claude session
    local parents_file="$HOME/.claude/branch_parents"
    if [ -z "$from_branch" ] && [ "$force_new" != "true" ] && [ -f "$parents_file" ]; then
        local parent_sid existing_sid
        parent_sid=$(grep "^${key} " "$parents_file" | head -n 1 | cut -d' ' -f2)
        existing_sid=""
        [ -f "$map_file" ] && existing_sid=$(grep "^${key} " "$map_file" | head -n 1 | cut -d' ' -f2)
        if [ -n "$parent_sid" ] && [ -z "$existing_sid" ]; then
            echo "Branch was spawned by another Claude session — inheriting context (use --new for blank)" | yellow
            echo "${key} ${parent_sid}" >> "$map_file"
        fi
    fi

    sleep 0.5
    tmux new -s "$session_name" "source '${SRPUB_DIR}/bashrc' && claude_resume_or_new '${key}'"
}

############################################################
#     setup terminal coloring
############################################################

show_arch=''
if [[ $processor == *Apple* ]]; then
    echo "Apple processor detected: $processor"
    show_arch="($cur_arch) "
fi

set_ps1() {
    if [[ $shell == *zsh* ]]; then
        autoload -U colors && colors
        setopt PROMPT_SUBST
        if [[ -n "$SSH_CLIENT" ]]; then
            PROMPT='%{$fg[green]%}%m%{$reset_color%} %2~ %# '
        else
            PROMPT='%{$fg[yellow]%}%2~ %#%{$reset_color%} '
        fi
        return
    fi

    if [[ $box_id_str == *prod* ]]; then
        # production is red (and named)
        PS1="\w \[\033[1;91m\]\h $\[\033[0m\] "
        alias ls="ls -G --color=auto --hide='*.pyc'"
    elif [[ $box_id_str == *dev* || $box_id_str == *ec2* ]]; then
        # Dev boxes are blue
        PS1="\w \[\033[1;34m\]$\[\033[0m\] "
        alias ls="ls -G --color=auto --hide='*.pyc'"
    else
        # Check if this is a Mac or Linux
        if [[ "$(uname -s)" == "Darwin" ]]; then
            # Macbooks are yellow, show hostname if SSHed in
            if [[ -n "$SSH_CLIENT" ]]; then
                PS1="\[\033[1;32m\]\h\[\033[0m\] \w $show_arch$ "
            else
                PS1="\[\033[1;93m\]\w $show_arch$\[\033[0m\] "
            fi
            alias ls="ls -G"
        else
            # Linux machines are green and named
            PS1="\[\033[1;32m\]\h\[\033[0m\] \w $ "
            alias ls="ls -G --color=auto --hide='*.pyc'"
        fi
    fi
}

set_ps1
