#!/usr/bin/env python3
# srt-to-txt.py
# Copyright (c) 2026 PiSaucer
# Licensed under the MIT License
# Version 1.0.0

# Convert an SRT subtitle file to plain UTF-8 text.
# Usage: python3 srt-to-txt.py INPUT.srt [OUTPUT.txt]

import argparse
import re
import sys
from pathlib import Path

# Match an SRT time range, including optional positioning information.
TIMECODE_RE = re.compile(
    r"^\s*\d{1,3}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*"
    r"\d{1,3}:\d{2}:\d{2}[,.]\d{3}(?:\s+.*)?$"
)

def extract_subtitle_text(content: str) -> list[str]:
    """Extract visible text lines from SubRip content.

    Args:
        content: Complete SRT document text, optionally including a byte-order
            mark and mixed newline styles.

    Returns:
        Subtitle lines with cue numbers, timecodes, and blank lines removed.
    """
    # utf-8-sig normally removes the BOM, but lstrip also supports direct calls.
    normalized = content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    subtitles = []

    # SRT cues are separated by one or more blank lines.
    for block in re.split(r"\n[ \t]*\n+", normalized):
        lines = [line.strip() for line in block.splitlines()]

        # A well-formed cue begins with an optional sequence number and time range.
        if lines and lines[0].isdigit():
            lines.pop(0)
        if lines and TIMECODE_RE.match(lines[0]):
            lines.pop(0)

        # Retain markup such as speaker or emphasis tags; this converter removes
        # SRT structure, not formatting embedded in the subtitle text itself.
        subtitles.extend(line for line in lines if line)

    return subtitles

def convert_srt_to_txt(srt_file: Path, txt_file: Path) -> int:
    """Convert one SRT subtitle file to a UTF-8 plaintext file.

    Args:
        srt_file: Input subtitle path.
        txt_file: Output plaintext path.

    Returns:
        Number of subtitle text lines written.

    Raises:
        FileNotFoundError: If ``srt_file`` is not a file.
        ValueError: If the input is not an SRT file or the input and output
            resolve to the same path.
        OSError: If the input cannot be read or the output cannot be written.
        UnicodeError: If the input cannot be decoded as UTF-8.
    """
    if not srt_file.is_file():
        raise FileNotFoundError(f"input file not found: {srt_file}")
    if srt_file.suffix.lower() != ".srt":
        raise ValueError(f"input file must have a .srt extension: {srt_file}")
    if srt_file.resolve() == txt_file.resolve():
        raise ValueError("input and output paths must be different")

    # utf-8-sig accepts regular UTF-8 and removes a leading byte-order mark.
    content = srt_file.read_text(encoding="utf-8-sig")
    subtitles = extract_subtitle_text(content)

    # Create an explicitly requested output directory when it does not exist.
    txt_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Emit one subtitle line per output line and include a conventional final LF.
    output = "\n".join(subtitles)
    if output:
        output += "\n"
    txt_file.write_text(output, encoding="utf-8")

    return len(subtitles)

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed input SRT path and optional output text path.

    Raises:
        SystemExit: If arguments are invalid or argparse handles an immediate
            action such as ``--help``.
    """
    parser = argparse.ArgumentParser(
        description="Convert an SRT subtitle file to plain UTF-8 text."
    )
    parser.add_argument("srt_file", type=Path, help="Input .srt subtitle file")
    parser.add_argument(
        "output_file",
        type=Path,
        nargs="?",
        help="Output .txt file (default: input filename with a .txt extension)",
    )
    return parser.parse_args()

def main() -> int:
    """Run the command-line subtitle converter.

    Returns:
        Zero on success or one when validation, decoding, or file I/O fails.
    """
    args = parse_args()
    srt_file = args.srt_file.expanduser()
    txt_file = (
        args.output_file.expanduser()
        if args.output_file
        else srt_file.with_suffix(".txt")
    )

    try:
        line_count = convert_srt_to_txt(srt_file, txt_file)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Converted: {srt_file} -> {txt_file} ({line_count} text lines)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
