#!/bin/sh
# tex-to-md.sh
# Copyright (c) 2026 PiSaucer
# Licensed under the MIT License
# Version 1.0.0

# LaTex to Markdown

# Color codes
# https://stackoverflow.com/questions/5947742/how-to-change-the-output-color-of-echo-in-linux
NC='\033[0m' # No Color
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'

helpFunction() {
   printf "LaTeX to Markdown\n\n"
   printf "Usage: ${YELLOW}$0 -f file|-i file [--input file] -o output [--output output] ${NC}\n"
   printf "\t-f, -i, --input The Input LaTeX Filename\n"
   printf "\t-o, --output The Ouput Markdown Filename\n"
   exit 1 # Exit script after printing help
}

# Parse long options
for arg in "$@"; do
  case $arg in
    --input=*)
      file="${arg#*=}"
      shift
      ;;
    --output=*)
      output="${arg#*=}"
      shift
      ;;
  esac
done

# Parse short options
while getopts "i:f:o:" opt
do
   case "$opt" in
      i ) file="$OPTARG" ;;
      f ) file="$OPTARG" ;; # legacy support
      o ) output="$OPTARG" ;;
      ? ) helpFunction ;; # Print helpFunction in case parameter is non-existent
   esac
done

# Print helpFunction in case parameters are empty
if [ -z "$file" ]
then
   echo "${RED}Missing Input LaTex Filename${NC}\n";
   helpFunction
fi

# Check if pandoc is installed
if ! command -v pandoc >/dev/null 2>&1; then
    printf "${RED}Error: pandoc is not installed. Please install pandoc first.${NC}\n"
    exit 1
fi

# Check if the input file or directory exists
if [ -d "$file" ]
then
    find "$file" -name "*.tex" | while read i; do pandoc -s "$i" -o "${i%.*}.md"; done
elif [ -f "$file" ]
then
    $file | pandoc -s "$file" -o "${output:-$file"_converted"}.md"
    echo "${GREEN}Convert $file to ${output:-$file"_converted"}.md${NC}"
else
    echo "${RED}Missing Input LaTex Filename${NC}";
    helpFunction
fi
