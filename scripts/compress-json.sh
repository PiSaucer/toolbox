#!/bin/sh
# compress-json.sh
# Copyright (c) 2026 PiSaucer
# Licensed under the MIT License
# Version 1.3.0

# Compress JSON files
# Usage: ./compress-json.sh -f file|-i file [--input file] -o dir [--output dir]

# Color codes
NC='\033[0m' # No Color
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'

helpFunction() {
    printf "Compress JSON files\n\n"
    printf "Usage: ${YELLOW}$0 -f file|-i file [--input file] -o dir [--output dir] ${NC}\n"
    printf "\t-f, -i, --input   The Input JSON Filename or Directory\n"
    printf "\t-o, --output      The Output Directory (optional)\n"
    printf "\t--help            Show this help message\n"
    exit 1 # Exit script after printing help
}

# Parse long options
while [ $# -gt 0 ]; do
    case "$1" in
        --input)
            file="$2"
            shift 2
            ;;
        --input=*)
            file="${1#*=}"
            shift
            ;;
        --output)
            output="$2"
            shift 2
            ;;
        --output=*)
            output="${1#*=}"
            shift
            ;;
        --help)
            helpFunction
            ;;
        *)
            break
            ;;
    esac
done

# Parse short options
while getopts "f:o:i:" opt; do
   case "$opt" in
      f | i ) file="$OPTARG" ;;
      o ) output="$OPTARG" ;;
      ? ) helpFunction ;;
   esac
done

if [ -z "$file" ]; then
   printf "${RED}Missing Input JSON Filename or Directory${NC}\n"
   helpFunction
fi

if ! command -v jq >/dev/null 2>&1; then
    printf "${RED}Error: jq is not installed. Please install jq first.${NC}\n"
    exit 1
fi

output="${output:-./min}"
mkdir -p "$output"

compressed=0
failed=0

compress_file() {
    input_file="$1"
    output_file="$2"
    output_dir=$(dirname "$output_file")
    tmpfile="$output_file.tmp"

    mkdir -p "$output_dir"

    if jq -c . "$input_file" > "$tmpfile"; then
        mv "$tmpfile" "$output_file"
        printf "${GREEN}Compressed $input_file -> $output_file${NC}\n"
        compressed=$((compressed + 1))
    else
        printf "${RED}Failed: $input_file${NC}\n"
        rm -f "$tmpfile"
        failed=$((failed + 1))
    fi
}

if [ -d "$file" ]; then
    input_root="${file%/}"
    output_root="${output%/}"
    file_list=$(mktemp "${TMPDIR:-/tmp}/compress-json.XXXXXX") || {
        printf "${RED}Error: could not create a temporary file.${NC}\n"
        exit 1
    }
    trap 'rm -f "$file_list"' 0 1 2 15

    find "$input_root" -type f -name "*.json" > "$file_list"
    while IFS= read -r i; do
        case "$i" in
            "$output_root"/*)
                continue
                ;;
        esac

        rel="${i#"$input_root"/}"
        outfile="$output_root/$rel"

        compress_file "$i" "$outfile"
    done < "$file_list"

    rm -f "$file_list"
    trap - 0 1 2 15

elif [ -f "$file" ]; then
    base=$(basename "$file")
    outfile="${output%/}/$base"

    compress_file "$file" "$outfile"

else
    printf "${RED}Input does not exist: $file${NC}\n"
    helpFunction
fi

printf "\n${BLUE}Summary:${NC} ${GREEN}%s compressed${NC}, ${RED}%s failed${NC}\n" "$compressed" "$failed"

if [ "$failed" -gt 0 ]; then
    exit 1
fi
