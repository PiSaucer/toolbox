#!/bin/sh
# pptx-to-pdf.sh
# Copyright (c) 2026 PiSaucer
# Licensed under the MIT License
# Version 1.0.0
# PowerPoint to PDF

# Color codes
# https://stackoverflow.com/questions/5947742/how-to-change-the-output-color-of-echo-in-linux
NC='\033[0m' # No Color
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'

helpFunction() {
   echo "PowerPoint to PDF\n"
   echo "Usage: ${YELLOW}$0 -i file -o output${NC}"
   echo "\t-i, -f, --input The Input PowerPoint Filename"
   echo "\t-o, --output The Ouput PDF Filename"
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
   echo "${RED}Missing Input PowerPoint Filename${NC}\n";
   helpFunction
fi

# Check if soffice is installed
if ! command -v soffice >/dev/null 2>&1; then
    printf "${RED}Error: soffice is not installed. Please install LibreOffice first.${NC}\n"
    exit 1
fi

# Determine if input is a file or directory
if [ -d "$file" ]
then
    find "$file" -name "*.pptx" | while read i; do soffice --headless --convert-to pdf "$i"; done
elif [ -f "$file" ]
then
    soffice --headless --convert-to pdf "$file"
    echo "${GREEN}Convert $file to ${output:-$file".pdf"}${NC}"
else
    echo "${RED}Missing Input PowerPoint Filename${NC}";
    helpFunction
fi
