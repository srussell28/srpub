#!/bin/bash
set -e

AUTO_YES=false
for arg in "$@"; do
    case "$arg" in
        --yes|-y) AUTO_YES=true ;;
        --help|-h)
            echo "Usage: quicksetup.sh [OPTIONS]"
            echo ""
            echo "Sets up a new machine with standard packages, tools, and configs."
            echo ""
            echo "Options:"
            echo "  -y, --yes    Skip confirmation prompts and install everything"
            echo "  -h, --help   Show this help message"
            exit 0
            ;;
    esac
done

confirm() {
    if [ "$AUTO_YES" = true ]; then
        return 0
    fi
    read -r -p "$1 [y/N] " response
    case "$response" in
        [yY][eE][sS]|[yY]) return 0 ;;
        *) return 1 ;;
    esac
}

# Remember when slow "update/upgrade" ops were last run, so we can show e.g.
# "(last done 2 months ago)" and let you skip churn you don't need.
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/quicksetup"
mkdir -p "$STATE_DIR"

_ago() {  # $1=quantity $2=unit(singular) -> "1 week ago" / "2 weeks ago"
    if [ "$1" -eq 1 ]; then echo "$1 $2 ago"; else echo "$1 ${2}s ago"; fi
}
last_done() {
    local f="$STATE_DIR/$1.last" then now diff
    [ -f "$f" ] || { echo "never"; return; }
    then=$(cat "$f" 2>/dev/null)
    [ -z "$then" ] && { echo "never"; return; }
    now=$(date +%s)
    diff=$(( now - then ))
    if   [ "$diff" -lt 3600 ];    then _ago "$(( diff / 60 ))" min
    elif [ "$diff" -lt 86400 ];   then _ago "$(( diff / 3600 ))" hour
    elif [ "$diff" -lt 604800 ];  then _ago "$(( diff / 86400 ))" day
    elif [ "$diff" -lt 2592000 ]; then _ago "$(( diff / 604800 ))" week
    else _ago "$(( diff / 2592000 ))" month; fi
}

mark_done() { date +%s > "$STATE_DIR/$1.last"; }

# confirm, annotated with when this op last ran. $1=op-key, $2=prompt
confirm_op() { confirm "$2 (last done $(last_done "$1"))"; }

OS="$(uname)"
if [ "$OS" != "Darwin" ] && [ "$OS" != "Linux" ]; then
    echo "Error: This script supports macOS and Linux only."
    exit 1
fi

SRPUB_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Quick Setup (srpub: $SRPUB_DIR) ==="

# 1. Install packages
echo ""
echo "--- Packages ---"
PACKAGES=(tmux wget jq htop tree ripgrep fzf)
if [ "$OS" = "Darwin" ]; then
    PACKAGES+=(fd)
else
    PACKAGES+=(fd-find)
fi
if [ "$OS" = "Darwin" ]; then
    if command -v brew &>/dev/null; then
        echo "Homebrew already installed."
    else
        if confirm "Install Homebrew?"; then
            echo "Installing Homebrew..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        fi
    fi
    if command -v brew &>/dev/null; then
        # Refresh the formula index (needed so installs resolve correctly);
        # this doesn't change anything already installed.
        brew update
        # Upgrading installed packages is the churn-y part -> make it opt-in.
        if confirm_op brew-upgrade "Upgrade installed brew packages?"; then
            brew upgrade
            brew autoremove
            brew cleanup
            mark_done brew-upgrade
        fi
        for pkg in "${PACKAGES[@]}"; do
            if brew list "$pkg" &>/dev/null; then
                echo "$pkg already installed, skipping."
            else
                if confirm "Install $pkg?"; then
                    echo "Installing $pkg..."
                    brew install "$pkg"
                fi
            fi
        done
    fi
else
    # Refresh the package index (needed for installs; doesn't upgrade
    # anything). The actual upgrade of installed packages is opt-in.
    sudo apt-get update -qq
    if confirm_op apt-upgrade "Upgrade installed apt packages?"; then
        sudo apt-get upgrade -y -qq
        mark_done apt-upgrade
    fi
    for pkg in "${PACKAGES[@]}"; do
        if dpkg -s "$pkg" &>/dev/null; then
            echo "$pkg already installed, skipping."
        else
            if confirm "Install $pkg?"; then
                echo "Installing $pkg..."
                sudo apt-get install -y -qq "$pkg"
            fi
        fi
    done
fi

# 2. Install Docker
echo ""
echo "--- Docker ---"
if command -v docker &>/dev/null; then
    echo "Docker already installed."
    if docker info &>/dev/null; then
        echo "Pruning dangling images and stopped containers..."
        docker system prune -f
    else
        echo "Docker daemon not running, skipping prune."
    fi
else
    if confirm "Install Docker?"; then
        echo "Installing Docker..."
        if [ "$OS" = "Darwin" ]; then
            brew install --cask docker
            echo "Docker Desktop installed. You may need to open it manually to finish setup."
        else
            curl -fsSL https://get.docker.com | sh
            sudo usermod -aG docker "$USER"
            echo "Docker installed. You may need to log out and back in for group changes."
        fi
    fi
fi

# 3. Install Miniconda
echo ""
echo "--- Miniconda ---"
if command -v conda &>/dev/null; then
    echo "Conda already installed."
    if confirm_op conda-base "Update conda base?"; then
        conda update -n base -c defaults conda -y
        mark_done conda-base
    fi
else
    if confirm "Install Miniconda?"; then
        echo "Installing Miniconda..."
        ARCH=$(uname -m)
        if [ "$OS" = "Darwin" ]; then
            if [ "$ARCH" = "arm64" ]; then
                CONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh"
            else
                CONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.sh"
            fi
        else
            if [ "$ARCH" = "aarch64" ]; then
                CONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh"
            else
                CONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
            fi
        fi
        curl -fsSL "$CONDA_URL" -o /tmp/miniconda.sh
        bash /tmp/miniconda.sh -b -p "$HOME/miniconda3"
        rm /tmp/miniconda.sh
        eval "$("$HOME/miniconda3/bin/conda" shell.bash hook)"
    fi
fi

# 4. Create samdev conda env
echo ""
echo "--- Conda env: samdev ---"
if command -v conda &>/dev/null; then
    if conda env list | grep -q "^samdev "; then
        if confirm_op conda-env "Update samdev conda env?"; then
            echo "Updating samdev env from environment.yml..."
            conda env update -f "$SRPUB_DIR/environment.yml" --prune --solver libmamba
            mark_done conda-env
        fi
    else
        if confirm "Create samdev conda env?"; then
            echo "Creating samdev env from environment.yml..."
            conda env create -f "$SRPUB_DIR/environment.yml" --solver libmamba
        fi
    fi
    echo "Cleaning conda cache..."
    conda clean --all -y
else
    echo "Conda not installed, skipping samdev env."
fi

# 5. Set up shell rc file
if [ "$OS" = "Darwin" ]; then
    SHELL_RC="$HOME/.zshrc"
else
    SHELL_RC="$HOME/.bashrc"
fi

echo ""
echo "--- $SHELL_RC ---"
SRPUB_SOURCE="source $SRPUB_DIR/bashrc"
SECRETS_SOURCE="source ~/.secretsrc"

if [ ! -f "$SHELL_RC" ]; then
    touch "$SHELL_RC"
fi

if grep -qF "$SRPUB_SOURCE" "$SHELL_RC"; then
    echo "srpub bashrc source line already present, skipping."
else
    echo "Adding srpub bashrc source line to $SHELL_RC..."
    echo "$SRPUB_SOURCE" >> "$SHELL_RC"
fi

if grep -qF "$SECRETS_SOURCE" "$SHELL_RC"; then
    echo "secretsrc source line already present, skipping."
else
    echo "Adding secretsrc source line to $SHELL_RC..."
    echo "$SECRETS_SOURCE" >> "$SHELL_RC"
fi

# 6. Copy configs
echo ""
echo "--- Config files ---"
for pair in vimrc:.vimrc condarc:.condarc psqlrc:.psqlrc tmux.conf:.tmux.conf; do
    src="${pair%%:*}"
    dest="$HOME/${pair#*:}"
    if [ -f "$dest" ]; then
        echo "$dest already exists, skipping."
    else
        echo "Copying $src -> $dest"
        cp "$SRPUB_DIR/other_config/$src" "$dest"
    fi
done

# 7. Claude config: symlink global CLAUDE.md and skills from the repo.
# Symlinks (vs copies) mean a `git pull` updates every machine; per-skill
# links let machine-local skills coexist in ~/.claude/skills.
echo ""
echo "--- Claude config ---"

# install_link <src> <dest>: create/refresh symlink, never clobber real files
install_link() {
    local src="$1" dest="$2"
    if [ -L "$dest" ]; then
        if [ "$(readlink "$dest")" = "$src" ]; then
            echo "$dest already linked."
        else
            rm "$dest" && ln -s "$src" "$dest"
            echo "Re-linked $dest -> $src"
        fi
    elif [ -e "$dest" ]; then
        echo "WARNING: $dest exists and is not a symlink; leaving it alone." >&2
    else
        ln -s "$src" "$dest"
        echo "Linked $dest -> $src"
    fi
}

mkdir -p "$HOME/.claude/skills"
if [ -f "$SRPUB_DIR/claude/CLAUDE.md" ]; then
    install_link "$SRPUB_DIR/claude/CLAUDE.md" "$HOME/.claude/CLAUDE.md"
fi
found_skill=false
for skill_dir in "$SRPUB_DIR"/claude/skills/*/; do
    [ -d "$skill_dir" ] || continue
    [ -f "$skill_dir/SKILL.md" ] || continue  # skills need a SKILL.md
    found_skill=true
    install_link "${skill_dir%/}" "$HOME/.claude/skills/$(basename "$skill_dir")"
done
if [ "$found_skill" = false ]; then
    echo "No skills in repo yet (add claude/skills/<name>/SKILL.md)."
fi

# Install Claude Code hooks and status line into ~/.claude/settings.json
settings="$HOME/.claude/settings.json"
hook_pre="bash $SRPUB_DIR/claude/hooks/pre-tool-lock.sh"
hook_stop="bash $SRPUB_DIR/claude/hooks/stop-release-lock.sh"
hook_post="bash $SRPUB_DIR/claude/hooks/post-tool-tab-title.sh"
statusline="bash $SRPUB_DIR/claude/statusline.sh"
python3 - "$settings" "$hook_pre" "$hook_stop" "$hook_post" "$statusline" <<'PYEOF'
import sys, json, os

settings_path, hook_pre, hook_stop, hook_post, statusline = sys.argv[1:6]
data = {}
if os.path.exists(settings_path):
    with open(settings_path) as f:
        data = json.load(f)

hooks = data.setdefault("hooks", {})

def ensure_hook(event, command, matcher=None):
    entries = hooks.setdefault(event, [])
    for e in entries:
        for h in e.get("hooks", []):
            if h.get("command") == command:
                return  # already installed
    entry = {"hooks": [{"type": "command", "command": command}]}
    if matcher is not None:
        entry["matcher"] = matcher
    entries.append(entry)

ensure_hook("PreToolUse", hook_pre, matcher="")
ensure_hook("Stop", hook_stop)
ensure_hook("PostToolUse", hook_post, matcher="")

data["statusLine"] = {"type": "command", "command": statusline, "padding": 0}

with open(settings_path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print(f"Claude hooks + status line installed in {settings_path}")
PYEOF

# 8. Configure git hooks
echo ""
echo "--- Git hooks ---"
git -C "$SRPUB_DIR" config core.hooksPath "$SRPUB_DIR/hooks"
echo "Set core.hooksPath to $SRPUB_DIR/hooks"

# 9. Install Claude Code (macOS only)
if [ "$OS" = "Darwin" ]; then
    echo ""
    echo "--- Claude Code ---"
    if command -v claude &>/dev/null; then
        if confirm_op claude-update "Update Claude Code?"; then
            echo "Updating Claude Code..."
            claude update
            mark_done claude-update
        fi
    else
        if confirm "Install Claude Code?"; then
            echo "Installing Claude Code..."
            curl -fsSL https://claude.ai/install.sh | bash
        fi
    fi
fi

echo ""
echo "=== Setup complete ==="
