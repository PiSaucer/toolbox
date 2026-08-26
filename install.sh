#!/bin/sh
# install.sh
# Copyright (c) 2026 PiSaucer
# Licensed under the MIT License
# Version 1.0.0

# Install the toolbox launcher and native zsh or bash command completion
# Usage: ./install.sh [--prefix PATH] [--url URL] [--no-path-update]

TOOLBOX_URL="${TOOLBOX_URL:-https://pisaucer.github.io/toolbox/toolbox.py}"
prefix="${HOME}/.local"
update_path=1
url_selected=0

# Color codes
# https://stackoverflow.com/questions/5947742/how-to-change-the-output-color-of-echo-in-linux
NC='\033[0m' # No Color
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'

helpFunction() {
    printf "Toolbox Installer\n\n"
    printf "Usage: ${YELLOW}./install.sh [OPTIONS]${NC}\n\n"
    printf "\t--prefix PATH       Install under PATH/bin (default: ~/.local)\n"
    printf "\t--url URL           Download toolbox.py from URL\n"
    printf "\t--no-path-update    Do not update your shell PATH\n"
    printf "\t-h, --help          Show this help message\n\n"
    printf "Environment:\n"
    printf "\tTOOLBOX_URL         Download toolbox.py from a different URL\n"
    exit 0 # Exit script after printing help
}

# Print a consistent option error
option_error() {
    printf "${RED}Error: %s${NC}\n\n" "$1" >&2
    helpFunction >&2
    exit 2
}

# Parse installer options
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
        --url)
            if [ "$#" -lt 2 ]; then
                option_error "--url requires a URL."
            fi
            TOOLBOX_URL=$2
            url_selected=1
            shift 2
            ;;
        --url=*)
            TOOLBOX_URL=${1#*=}
            [ -n "$TOOLBOX_URL" ] || option_error "--url requires a URL."
            url_selected=1
            shift
            ;;
        --no-path-update)
            update_path=0
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

# toolbox.py requires Python 3.9+ and installs its console dependency below.
if ! command -v python3 >/dev/null 2>&1; then
    printf "${RED}Error: Python 3.9 or newer is required.${NC}\n" >&2
    exit 1
fi
if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 9))'; then
    printf "${RED}Error: Python 3.9 or newer is required (found %s).${NC}\n" \
        "$(python3 -c 'import platform; print(platform.python_version())')" >&2
    exit 1
fi

# Check to see if pip is installed for Python 3. If not, print an error message and exit.
if ! python3 -m pip --version >/dev/null 2>&1; then
    printf "${RED}Error: pip is not installed for python3.${NC}\n" >&2
    printf "Install pip for Python 3 and try again.\n" >&2
    exit 1
fi

# Install Rich if it is not already available.
if python3 -c 'import rich' >/dev/null 2>&1; then
    printf "${GREEN}Rich is already installed.${NC}\n"
else
    rich_installed=0

    # Prefer pip when Python allows normal user package installation.
    if python3 -m pip --version >/dev/null 2>&1; then
        externally_managed=$(
            python3 -c '
import pathlib
import sysconfig

stdlib = pathlib.Path(sysconfig.get_path("stdlib"))
print("1" if (stdlib / "EXTERNALLY-MANAGED").exists() else "0")
'
        )

        if [ "$externally_managed" = "0" ]; then
            printf "Installing Rich using pip...\n"

            if python3 -m pip install --user "rich>=13.9,<15"; then
                rich_installed=1
                printf "${GREEN}Installed Rich using pip.${NC}\n"
            fi
        else
            printf "Python is externally managed; skipping pip.\n"
        fi
    else
        printf "pip is not available; trying the system package manager.\n"
    fi

    # Debian/Ubuntu and similar distributions use apt.
    if [ "$rich_installed" -eq 0 ] && command -v apt >/dev/null 2>&1; then
        printf "Installing Rich using apt (python3-rich)...\n"

        if [ "$(id -u)" -eq 0 ]; then
            if apt install -y python3-rich; then
                rich_installed=1
                printf "${GREEN}Installed Rich using apt.${NC}\n"
            fi
        elif command -v sudo >/dev/null 2>&1; then
            if sudo apt install -y python3-rich; then
                rich_installed=1
                printf "${GREEN}Installed Rich using apt.${NC}\n"
            fi
        else
            printf "${RED}Error: sudo is required to install python3-rich.${NC}\n" >&2
            exit 1
        fi
    fi

    if [ "$rich_installed" -eq 0 ]; then
        printf "${RED}Error: Could not install the Rich console dependency.${NC}\n" >&2
        exit 1
    fi

    # Verify that Rich is importable by the Python used by Toolbox.
    if ! python3 -c 'import rich' >/dev/null 2>&1; then
        printf "${RED}Error: Rich was installed, but python3 cannot import it.${NC}\n" >&2
        exit 1
    fi
fi

install_dir="${prefix}/bin"
destination="${install_dir}/toolbox"
# Prefer a checked-out toolbox.py; piped installers download the published copy
local_source=""
if [ "$url_selected" -eq 0 ] && [ -f "$0" ]; then
    script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
    if [ -f "${script_dir}/toolbox.py" ]; then
        local_source="${script_dir}/toolbox.py"
    fi
fi

# Write to a temporary destination so a failed update preserves the old command
mkdir -p "$install_dir"
temporary=$(mktemp "${install_dir}/.toolbox.XXXXXX")

if [ -n "$local_source" ]; then
    printf "Installing toolbox from %s\n" "$local_source"
    if ! cp "$local_source" "$temporary"; then
        rm -f "$temporary"
        printf "${RED}Error: Could not copy toolbox.py.${NC}\n" >&2
        exit 1
    fi
else
    printf "Downloading toolbox from %s\n" "$TOOLBOX_URL"
    if ! python3 -c \
        'import pathlib, sys, urllib.request; pathlib.Path(sys.argv[2]).write_bytes(urllib.request.urlopen(sys.argv[1]).read())' \
        "$TOOLBOX_URL" "$temporary"; then
        rm -f "$temporary"
        printf "${RED}Error: Could not download toolbox.py.${NC}\n" >&2
        exit 1
    fi
fi

# Validate the Python source before atomically replacing the launcher
if ! python3 -c \
    'import pathlib, sys; source = pathlib.Path(sys.argv[1]).read_bytes(); compile(source, sys.argv[1], "exec")' \
    "$temporary"; then
    rm -f "$temporary"
    printf "${RED}Error: toolbox.py failed validation.${NC}\n" >&2
    exit 1
fi
if ! chmod 755 "$temporary"; then
    rm -f "$temporary"
    printf "${RED}Error: Could not make toolbox executable.${NC}\n" >&2
    exit 1
fi
if ! mv "$temporary" "$destination"; then
    rm -f "$temporary"
    printf "${RED}Error: Could not install toolbox to %s.${NC}\n" "$destination" >&2
    exit 1
fi

# Add the default user-local bin directory to the active shell's startup file
path_updated=0
completion_installed=0
case ":${PATH}:" in
    *":${install_dir}:"*) ;;
    *)
        if [ "$update_path" -eq 1 ] && [ "$prefix" = "${HOME}/.local" ]; then
            shell_name=$(basename "${SHELL:-}")
            os_name=$(uname -s 2>/dev/null || printf unknown)
            case "$shell_name" in
                zsh) profile="${ZDOTDIR:-$HOME}/.zprofile" ;;
                bash)
                    if [ "$os_name" = "Darwin" ]; then
                        profile="$HOME/.bash_profile"
                    else
                        profile="$HOME/.bashrc"
                    fi
                    ;;
                *) profile="$HOME/.profile" ;;
            esac
            path_line='export PATH="$HOME/.local/bin:$PATH"'
            if [ ! -f "$profile" ] || ! grep -Fqx "$path_line" "$profile"; then
                {
                    printf '\n# Added by the toolbox installer\n'
                    printf '%s\n' "$path_line"
                } >> "$profile"
            fi
            path_updated=1
        fi
        ;;
esac

# Install tracked shell-native completion for launcher options and script IDs
shell_name=$(basename "${SHELL:-}")
case "$shell_name" in
    zsh)
        completion_dir="${prefix}/share/zsh/site-functions"
        completion_file="${completion_dir}/_toolbox"
        mkdir -p "$completion_dir"
        if [ -n "$local_source" ] && [ -f "${script_dir}/completions/_toolbox" ]; then
            cp "${script_dir}/completions/_toolbox" "$completion_file"
        fi
        zshrc="${ZDOTDIR:-$HOME}/.zshrc"
        if [ -f "$completion_file" ] && [ "$prefix" = "${HOME}/.local" ]; then
            fpath_line='fpath=("$HOME/.local/share/zsh/site-functions" $fpath)'
            if [ ! -f "$zshrc" ] || ! grep -Fqx "$fpath_line" "$zshrc"; then
                {
                    printf '\n# Added by the toolbox installer\n'
                    printf '%s\n' "$fpath_line"
                    printf '%s\n' 'autoload -Uz compinit && compinit'
                } >> "$zshrc"
            fi
            completion_installed=1
        fi
        ;;
    bash)
        completion_dir="${prefix}/share/bash-completion/completions"
        completion_file="${completion_dir}/toolbox"
        mkdir -p "$completion_dir"
        if [ -n "$local_source" ] && [ -f "${script_dir}/completions/toolbox.bash" ]; then
            cp "${script_dir}/completions/toolbox.bash" "$completion_file"
        fi
        if [ -f "$completion_file" ] && [ "$prefix" = "${HOME}/.local" ]; then
            os_name=$(uname -s 2>/dev/null || printf unknown)
            if [ "$os_name" = "Darwin" ]; then
                bash_profile="$HOME/.bash_profile"
            else
                bash_profile="$HOME/.bashrc"
            fi
            completion_line='[ -r "$HOME/.local/share/bash-completion/completions/toolbox" ] && . "$HOME/.local/share/bash-completion/completions/toolbox"'
            if [ ! -f "$bash_profile" ] || ! grep -Fqx "$completion_line" "$bash_profile"; then
                {
                    printf '\n# Added by the toolbox installer\n'
                    printf '%s\n' "$completion_line"
                } >> "$bash_profile"
            fi
            completion_installed=1
        fi
        ;;
esac

printf "${GREEN}Installed toolbox to %s${NC}\n" "$destination"
if [ "$path_updated" -eq 1 ]; then
    echo "Added ~/.local/bin to PATH."
elif ! command -v toolbox >/dev/null 2>&1; then
    echo "Add $install_dir to PATH to run toolbox from anywhere."
fi
if [ "$completion_installed" -eq 1 ]; then
    printf "${GREEN}Installed %s completion.${NC}\n" "$shell_name"
fi
if [ "$path_updated" -eq 1 ] || [ "$completion_installed" -eq 1 ]; then
    echo "Restart your shell to activate it, or run:"
    if [ "$shell_name" = "zsh" ]; then
        echo '  source ~/.zprofile; source ~/.zshrc; rehash'
    elif [ "$shell_name" = "bash" ]; then
        echo "  source $bash_profile"
    else
        echo "  source $profile"
    fi
fi