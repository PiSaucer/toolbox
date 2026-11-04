#!/usr/bin/env python3
# pdf_merge.py
# Copyright (c) 2026 PiSaucer
# Licensed under the MIT License
# Version 1.0.0

# Merge PDFs in the order provided on the command line or standard input.
# Usage: python3 pdf_merge.py -o OUTPUT.pdf INPUT.pdf INPUT.pdf [...]

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VERSION = "1.0.0"

def parse_args() -> argparse.Namespace:
    """Parse the output path and optional input PDF paths.

    Returns:
        An argparse namespace containing the output path and input filenames.

    Raises:
        SystemExit: If arguments are invalid or argparse handles an immediate
            action such as ``--help`` or ``--version``.
    """
    parser = argparse.ArgumentParser(description="Merge PDF files in order.")
    parser.add_argument("pdfs", nargs="*", metavar="INPUT.pdf", help="input PDF files, in order")
    parser.add_argument("-o", "--output", required=True, type=Path, metavar="OUTPUT.pdf", help="output PDF file")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser.parse_args()

def main() -> int:
    """Validate the inputs and merge them using Poppler's pdfunite.

    Input filenames may be supplied as positional arguments and, when standard
    input is redirected, as one filename per line after those arguments.

    Returns:
        Zero on success, or one if validation, file I/O, or merging fails.

    Raises:
        SystemExit: If argument parsing fails or handles an immediate action
            such as ``--help`` or ``--version``.
    """
    args = parse_args()
    try:
        names = list(args.pdfs)
        if not sys.stdin.isatty():
            # A line is a complete path, so spaces in filenames are preserved.
            names.extend(line.rstrip("\r\n") for line in sys.stdin if line.rstrip("\r\n"))
        if len(names) < 2:
            raise ValueError("provide at least two PDF filenames as arguments or through standard input")

        inputs = [Path(name).expanduser() for name in names]
        output = args.output.expanduser()
        if output.suffix.lower() != ".pdf":
            raise ValueError(f"output file must have a .pdf extension: {output}")
        for pdf in inputs:
            if pdf.suffix.lower() != ".pdf":
                raise ValueError(f"input file must have a .pdf extension: {pdf}")
            if not pdf.is_file():
                raise FileNotFoundError(f"PDF file not found: {pdf}")
            if pdf.resolve() == output.resolve() or (output.exists() and os.path.samefile(pdf, output)):
                raise ValueError(f"output must not be an input file: {pdf}")
        if output.exists():
            raise FileExistsError(f"output already exists: {output}")

        script_directory = Path(__file__).resolve().parent
        executable = next((str(script_directory / name) for name in ("pdfunite.exe", "pdfunite") if (script_directory / name).is_file()), None) or shutil.which("pdfunite")
        if not executable:
            raise RuntimeError("pdfunite not found. Install Poppler and add pdfunite to PATH")

        # Write beside the destination, then publish only after a successful merge.
        with tempfile.TemporaryDirectory(prefix="pdf_merge_", dir=output.parent) as temp_dir:
            temporary_output = Path(temp_dir) / "merged.pdf"
            subprocess.run([executable, *(str(pdf.resolve()) for pdf in inputs), str(temporary_output)], check=True)
            # Exclusive creation avoids overwriting a file created during the merge.
            with temporary_output.open("rb") as source, output.open("xb") as destination:
                shutil.copyfileobj(source, destination)
        print(f"Merged {len(inputs)} PDFs into: {output}")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
