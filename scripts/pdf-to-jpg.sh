#!/bin/sh
# pdf-to-jpg.sh
# Copyright (c) 2026 PiSaucer
# Licensed under the MIT License
# Version 1.0.0

# Render PDF pages as high-quality JPG images
# Usage: ./pdf-to-jpg.sh -i file.pdf|dir [-o outdir] [--dpi 300] [-q 92]

# Color codes
# https://stackoverflow.com/questions/5947742/how-to-change-the-output-color-of-echo-in-linux
NC='\033[0m' # No Color
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'

# Default rendering settings
DPI=300
QUALITY=92
file=""
output=""

helpFunction() {
    printf "PDF to JPG\n\n"
    printf "Usage: ${YELLOW}%s -i file.pdf|dir [-o outdir] [--dpi 300] [-q 92]${NC}\n" "$0"
    printf "\t-f, -i, --input   Input PDF file or directory containing PDF files\n"
    printf "\t-o, --output      Output directory (optional; default: alongside input)\n"
    printf "\t--dpi             Render DPI (default: 300)\n"
    printf "\t-q, --quality     JPG quality from 1 to 100 (default: 92)\n"
    printf "\t-h, --help        Show this help message\n"
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

# Ensure a numeric setting is an integer within the supported range
validate_integer() {
    setting_name="$1"
    setting_value="$2"
    minimum="$3"
    maximum="$4"

    case "$setting_value" in
        "" | *[!0-9]*)
            option_error "$setting_name must be an integer from $minimum to $maximum."
            ;;
    esac

    if [ "$setting_value" -lt "$minimum" ] || [ "$setting_value" -gt "$maximum" ]; then
        option_error "$setting_name must be an integer from $minimum to $maximum."
    fi
}

# Prefer ImageMagick 7's magick command, with ImageMagick 6 as a fallback
find_imagemagick() {
    if command -v magick >/dev/null 2>&1; then
        printf "magick"
    elif command -v convert >/dev/null 2>&1; then
        printf "convert"
    fi
}

# Render every page and use a zero-padded page number in each output filename
pdf_to_jpg() {
    pdf_file="$1"
    output_base="$2"

    "$IMAGEMAGICK" \
        -density "$DPI" \
        -units PixelsPerInch \
        "$pdf_file" \
        -background white \
        -alpha remove \
        -alpha off \
        -strip \
        -quality "$QUALITY" \
        "${output_base}-%03d.jpg"
}

# Determine the destination for one PDF and render it
process_pdf() {
    pdf_file="$1"

    if [ -n "$output" ]; then
        if [ -n "$input_root" ]; then
            # Preserve subdirectories during batch conversion to avoid name collisions
            relative_path="${pdf_file#"$input_root"/}"
            output_base="${output%/}/${relative_path%.*}"
        else
            output_base="${output%/}/$(basename "${pdf_file%.*}")"
        fi
    else
        output_base="${pdf_file%.*}"
    fi

    output_directory=$(dirname "$output_base")
    if ! mkdir -p "$output_directory"; then
        printf "${RED}Error: could not create output directory: %s${NC}\n" "$output_directory" >&2
        return 1
    fi

    if pdf_to_jpg "$pdf_file" "$output_base"; then
        printf "${GREEN}Rendered %s -> %s-###.jpg (%s DPI, q=%s)${NC}\n" \
            "$pdf_file" "$output_base" "$DPI" "$QUALITY"
    else
        printf "${RED}Error: failed to render %s${NC}\n" "$pdf_file" >&2
        return 1
    fi
}

# Parse short and long options, including --option=value forms
while [ $# -gt 0 ]; do
    case "$1" in
        -f | -i | --input)
            require_option_value "$1" "${2-}"
            file="$2"
            shift 2
            ;;
        --input=*)
            file="${1#*=}"
            [ -n "$file" ] || option_error "--input requires a value."
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
        --dpi)
            require_option_value "$1" "${2-}"
            DPI="$2"
            shift 2
            ;;
        --dpi=*)
            DPI="${1#*=}"
            [ -n "$DPI" ] || option_error "--dpi requires a value."
            shift
            ;;
        -q | --quality)
            require_option_value "$1" "${2-}"
            QUALITY="$2"
            shift 2
            ;;
        --quality=*)
            QUALITY="${1#*=}"
            [ -n "$QUALITY" ] || option_error "--quality requires a value."
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
            option_error "unexpected argument: $1"
            ;;
    esac
done

# Reject positional arguments after the explicit end-of-options marker
if [ $# -gt 0 ]; then
    option_error "unexpected argument: $1"
fi

if [ -z "$file" ]; then
    option_error "missing input PDF file or directory."
fi

validate_integer "DPI" "$DPI" 1 2400
validate_integer "quality" "$QUALITY" 1 100

# Check for ImageMagick after parsing so --help works without dependencies
IMAGEMAGICK=$(find_imagemagick)
if [ -z "$IMAGEMAGICK" ]; then
    printf "${RED}Error: ImageMagick is not installed (expected magick or convert).${NC}\n" >&2
    exit 1
fi

# Convert one PDF or all PDFs below an input directory
if [ -d "$file" ]; then
    input_root="${file%/}"
    found_pdf=0
    failed=0

    # A temporary list avoids a pipeline subshell, so summary state remains available
    pdf_list=$(mktemp "${TMPDIR:-/tmp}/pdf-to-jpg.XXXXXX") || exit 1
    trap 'rm -f "$pdf_list"' 0
    trap 'exit 130' HUP INT TERM
    find "$input_root" -type f \( -name "*.pdf" -o -name "*.PDF" \) -print > "$pdf_list"

    while IFS= read -r pdf_file; do
        found_pdf=1
        process_pdf "$pdf_file" || failed=$((failed + 1))
    done < "$pdf_list"

    if [ "$found_pdf" -eq 0 ]; then
        printf "${YELLOW}No PDF files found in: %s${NC}\n" "$file"
        exit 0
    fi

    if [ "$failed" -gt 0 ]; then
        printf "${RED}%s PDF file(s) failed to render.${NC}\n" "$failed" >&2
        exit 1
    fi
elif [ -f "$file" ]; then
    case "$file" in
        *.[pP][dD][fF])
            process_pdf "$file" || exit 1
            ;;
        *)
            option_error "input file must have a .pdf extension: $file"
            ;;
    esac
else
    printf "${RED}Error: input does not exist: %s${NC}\n" "$file" >&2
    exit 1
fi
