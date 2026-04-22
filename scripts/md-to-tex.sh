#!/bin/sh
# md-to-tex.sh
# Copyright (c) 2026 PiSaucer
# Licensed under the MIT License
# Version 1.0.0

# Markdown to LaTeX

# Color codes
# https://stackoverflow.com/questions/5947742/how-to-change-the-output-color-of-echo-in-linux
NC='\033[0m' # No Color
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'

helpFunction() {
    printf "Markdown to LaTeX\n\n"
    printf "Usage: ${YELLOW}$0 -f file|-i file [--input file] -o output [--output output] ${NC}\n"
    printf "\t-f, -i, --input   The Input Markdown Filename\n"
    printf "\t-o, --output      The Output LaTeX Filename (optional)\n"
    exit 1 # Exit script after printing help
}

# Parse long options
shift $((OPTIND -1))
while [ $# -gt 0 ]; do
    case "$1" in
        --input)
            file="$2"
            shift 2
            ;;
        --output)
            output="$2"
            shift 2
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

# Print helpFunction in case parameters are empty
if [ -z "$file" ]; then
   printf "${RED}Missing Input Markdown Filename${NC}\n"
   helpFunction
fi

# Check if pandoc is installed
if ! command -v pandoc >/dev/null 2>&1; then
    printf "${RED}Error: pandoc is not installed. Please install pandoc first.${NC}\n"
    exit 1
fi

# Check if the input file or directory exists
if [ -d "$file" ]; then
    find "$file" -name "*.md" | while read -r i; do
        pandoc -s -f markdown -t latex "$i" -o "${i%.*}.tex"
    done
elif [ -f "$file" ]; then
    output="${output:-${file%.*}_converted.tex}"
    pandoc -s -f markdown -t latex "$file" -o "$output"
    printf "${GREEN}Converted $file to $output${NC}\n"
else
    printf "${RED}Input file does not exist: $file${NC}\n"
    helpFunction
fi
