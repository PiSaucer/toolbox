#!/bin/sh
# uninstall.sh
# Copyright (c) 2026 PiSaucer
# Licensed under the MIT License
# Version 1.0.0

# Uninstall the toolbox launcher installed by install.sh
# Usage: ./uninstall.sh [--prefix PATH] [--keep-shell-config]

prefix="${HOME}/.local"
clean_shell_config=1

# Color codes
# https://stackoverflow.com/questions/5947742/how-to-change-the-output-color-of-echo-in-linux
NC='\033[0m' # No Color
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'

helpFunction() {
    printf "Toolbox Uninstaller\n\n"
    printf "Usage: ${YELLOW}./uninstall.sh [OPTIONS]${NC}\n\n"
    printf "\t--prefix PATH          Remove toolbox from PATH (default: ~/.local)\n"
    printf "\t--keep-shell-config    Keep PATH and completion lines in shell profiles\n"
    printf "\t-h, --help             Show this help message\n\n"
    printf "This removes installations created by install.sh. For pip, pipx, uv, or\n"
    printf "Homebrew installations, use that package manager's uninstall command.\n"
    exit 1 # Exit script after printing help
}

# Print a consistent option error
option_error() {
    printf "${RED}Error: %s${NC}\n\n" "$1" >&2
    helpFunction >&2
    exit 2
}

# Parse uninstaller options
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix)
            if [ "$#" -lt 2 ]; then
                option_error "--prefix requires a path."
            fi
            prefix=$2
            shift 2
            ;;
        --prefix=*)
            prefix=${1#*=}
            [ -n "$prefix" ] || option_error "--prefix requires a path."
            shift
            ;;
        --keep-shell-config)
            clean_shell_config=0
            shift
            ;;
        -h|--help)
            helpFunction
            exit 0
            ;;
        *)
            option_error "unknown option: $1"
            ;;
    esac
done

# Remove an installed file when it exists
remove_file() {
    if [ -f "$1" ] || [ -L "$1" ]; then
        if ! rm -f -- "$1"; then
            printf "${RED}Error: Could not remove %s.${NC}\n" "$1" >&2
            exit 1
        fi
        printf 'Removed %s\n' "$1"
    fi
}

# Remove installer-managed lines from a shell startup file
clean_profile() {
    profile=$1
    [ -f "$profile" ] || return 0
    temporary=$(mktemp "${profile}.toolbox-uninstall.XXXXXX") || return 1
    awk '
        $0 == "# Added by the toolbox installer" { next }
        $0 == "export PATH=\"$HOME/.local/bin:$PATH\"" { next }
        $0 == "fpath=(\"$HOME/.local/share/zsh/site-functions\" $fpath)" { next }
        $0 == "autoload -Uz compinit && compinit" { next }
        $0 == "[ -r \"$HOME/.local/share/bash-completion/completions/toolbox\" ] && . \"$HOME/.local/share/bash-completion/completions/toolbox\"" { next }
        { print }
    ' "$profile" > "$temporary"
    if cmp -s "$profile" "$temporary"; then
        rm -f -- "$temporary"
    else
        mv -- "$temporary" "$profile"
        printf 'Removed toolbox settings from %s\n' "$profile"
    fi
}

remove_file "${prefix}/bin/toolbox"
remove_file "${prefix}/share/zsh/site-functions/_toolbox"
remove_file "${prefix}/share/bash-completion/completions/toolbox"

# Remove now-empty directories without disturbing anything owned by other tools.
rmdir "${prefix}/share/zsh/site-functions" 2>/dev/null || true
rmdir "${prefix}/share/zsh" 2>/dev/null || true
rmdir "${prefix}/share/bash-completion/completions" 2>/dev/null || true
rmdir "${prefix}/share/bash-completion" 2>/dev/null || true
rmdir "${prefix}/share" 2>/dev/null || true
rmdir "${prefix}/bin" 2>/dev/null || true

if [ "$clean_shell_config" -eq 1 ] && [ "$prefix" = "${HOME}/.local" ]; then
    clean_profile "${ZDOTDIR:-$HOME}/.zprofile"
    clean_profile "${ZDOTDIR:-$HOME}/.zshrc"
    clean_profile "$HOME/.bash_profile"
    clean_profile "$HOME/.bashrc"
    clean_profile "$HOME/.profile"
fi

printf "${GREEN}Toolbox uninstall complete.${NC}\n"
shell_name=$(basename "${SHELL:-}")
case "$shell_name" in
    zsh)
        printf 'Reload this console with:\n  exec zsh -l\n'
        ;;
    bash)
        printf 'Reload this console with:\n  exec bash -l\n'
        ;;
    *)
        if [ -n "${SHELL:-}" ]; then
            printf 'Reload this console with:\n  exec %s -l\n' "$SHELL"
        else
            printf 'Open a new terminal to refresh PATH and completion.\n'
        fi
        ;;
esac
