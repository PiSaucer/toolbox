#!/bin/sh
# dcurl.sh
# Copyright (c) 2026 PiSaucer
# Licensed under the MIT License
# Version 1.0.0

# Directory CURL
# Usage: ./dcurl.sh URL [-o DIRECTORY]

# Color codes
# https://stackoverflow.com/questions/5947742/how-to-change-the-output-color-of-echo-in-linux
NC='\033[0m' # No Color
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'

url=""
output=""

helpFunction() {
    printf "Directory Copy URL\n\n"
    printf "Usage: ${YELLOW}%s URL [-o DIRECTORY]${NC}\n" "$0"
    printf "       ${YELLOW}%s --url URL [--output DIRECTORY]${NC}\n\n" "$0"
    printf "\t-u, --url       HTTP or HTTPS directory URL to download\n"
    printf "\t-o, --output    Local download directory (optional)\n"
    printf "\t-h, --help      Show this help message\n"
    exit 1 # Exit script after printing help
}

# Print an error message
option_error() {
    printf "${RED}Error: %s${NC}\n\n" "$1" >&2
    helpFunction 1
}

# Read the value following an option and reject missing values
require_option_value() {
    option_name="$1"
    option_value="${2-}"

    if [ -z "$option_value" ]; then
        option_error "$option_name requires a value."
    fi
}

# Parse flags and options
while [ $# -gt 0 ]; do
    case "$1" in
        -u | --url)
            require_option_value "$1" "${2-}"
            url="$2"
            shift 2
            ;;
        --url=*)
            url="${1#*=}"
            [ -n "$url" ] || option_error "--url requires a value."
            shift
            ;;
        -o | --output)
            require_option_value "$1" "${2-}"
            output="$2"
            shift 2
            ;;
        --output=*)
            output="${1#*=}"
            [ -n "$output" ] || option_error "--output requires a value."
            shift
            ;;
        -h | --help)
            helpFunction 0
            ;;
        --)
            shift
            break
            ;;
        -*)
            option_error "unknown option: $1"
            ;;
        *)
            if [ -n "$url" ]; then
                option_error "unexpected argument: $1"
            fi
            url="$1"
            shift
            ;;
    esac
done

# Accept one positional URL after flagss
if [ $# -gt 0 ]; then
    if [ -n "$url" ] || [ $# -gt 1 ]; then
        option_error "unexpected argument: $1"
    fi
    url="$1"
fi

if [ -z "$url" ]; then
    option_error "missing URL."
fi

# Restrict input to remote web URLs
case "$url" in
    http://* | https://*)
        ;;
    *)
        option_error "URL must begin with http:// or https://."
        ;;
esac

# Check the dependency after parsing so --help works without wget installed
if ! command -v wget >/dev/null 2>&1; then
    printf "${RED}Error: wget is not installed.${NC}\n" >&2
    exit 1
fi

# Preserve wget's default host/path layout and optionally choose its local root
if [ -n "$output" ]; then
    if ! mkdir -p "$output"; then
        printf "${RED}Error: could not create output directory: %s${NC}\n" "$output" >&2
        exit 1
    fi
    wget --no-parent --recursive --directory-prefix="$output" -- "$url"
else
    wget --no-parent --recursive -- "$url"
fi

download_status=$?
if [ "$download_status" -ne 0 ]; then
    printf "${RED}Error: wget failed for %s (exit %s).${NC}\n" \
        "$url" "$download_status" >&2
    exit "$download_status"
fi

if [ -n "$output" ]; then
    printf "${GREEN}Downloaded %s into %s${NC}\n" "$url" "$output"
else
    printf "${GREEN}Downloaded %s${NC}\n" "$url"
fi
