#!/usr/bin/env python3
# pdf_extract_images.py
# Copyright (c) 2026 PiSaucer
# Licensed under the MIT License
# Version 1.0.0

# Extract embedded images from a PDF and remove exact duplicates.
# Usage: python3 pdf_extract_images.py INPUT.pdf [-o OUTPUT_DIRECTORY] [--dry-run]

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0"

def require_pdfimages() -> str:
    """Locate the Poppler ``pdfimages`` executable.

    Returns:
        The executable beside this script, when present, or the
        platform-specific executable path found on ``PATH``.

    Raises:
        RuntimeError: If pdfimages cannot be found.
    """
    # Portable bundles can keep pdfimages beside this script and run without
    # modifying PATH. Windows uses .exe; Unix builds are normally extensionless.
    script_directory = Path(__file__).resolve().parent
    for filename in ("pdfimages.exe", "pdfimages"):
        bundled_executable = script_directory / filename
        if bundled_executable.is_file():
            return str(bundled_executable)

    # Fall back to the user's PATH when no portable copy accompanies the script.
    # shutil.which applies PATHEXT on Windows, so it also finds pdfimages.exe.
    executable = shutil.which("pdfimages")
    if not executable:
        raise RuntimeError(
            "pdfimages not found in PATH. Install Poppler (macOS: "
            "`brew install poppler`; Ubuntu/Debian: "
            "`sudo apt install poppler-utils`; Windows: install a Poppler "
            "build and place pdfimages.exe beside this script or add its "
            "Library/bin or bin directory to PATH)"
        )
    return executable

def sha256_file(path: Path) -> str:
    """Calculate the SHA-256 digest of a file without loading it all at once.

    Args:
        path: File to hash.

    Returns:
        Lowercase hexadecimal SHA-256 digest.

    Raises:
        OSError: If the file cannot be read.
    """
    hasher = hashlib.sha256()

    # Read large images in 1 MiB blocks to keep memory use predictable.
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)

    return hasher.hexdigest()

def extract_images(pdf: Path, output_dir: Path, pdfimages: str) -> None:
    """Extract all supported embedded image formats from a PDF.

    Args:
        pdf: Input PDF file.
        output_dir: Directory in which extracted images are written.
        pdfimages: Path to the Poppler pdfimages executable.

    Raises:
        OSError: If the output directory cannot be created or pdfimages cannot
            be started.
        subprocess.CalledProcessError: If pdfimages reports an error.
    """
    # Create nested output directories requested by the user when necessary.
    output_dir.mkdir(parents=True, exist_ok=True)

    # pdfimages appends a zero-padded number and image extension to this prefix.
    prefix = output_dir / "image"

    print(f"Extracting images from: {pdf}")
    print(f"Output directory:       {output_dir}")
    print()

    # Passing an argument list avoids shell quoting problems on every platform,
    # particularly for Windows paths and filenames containing spaces.
    subprocess.run(
        [
            pdfimages,
            "-all",
            str(pdf),
            str(prefix),
        ],
        check=True,
    )

def remove_duplicates(output_dir: Path, dry_run: bool = False) -> tuple[int, int, list[tuple[Path, Path]]]:
    """Find and optionally remove byte-for-byte duplicate extracted images.

    Args:
        output_dir: Directory containing the extracted image files.
        dry_run: Report duplicate files without deleting them.

    Returns:
        A tuple containing the total file count, unique-file count, and pairs
        of each duplicate path with the matching original path.

    Raises:
        OSError: If the directory cannot be read, a file cannot be hashed, or a
            duplicate cannot be removed.
    """
    # Only inspect files produced with this script's prefix. This prevents an
    # unrelated file in an existing output directory from being deleted.
    files = sorted(
        (file for file in output_dir.glob("image-*") if file.is_file()),
        key=lambda path: path.name.lower(),
    )

    seen: dict[str, Path] = {}
    duplicates: list[tuple[Path, Path]] = []

    for file in files:
        # Identical content produces the same digest regardless of filename or
        # image extension. The first matching file is retained as the original.
        digest = sha256_file(file)

        if digest in seen:
            original = seen[digest]
            duplicates.append((file, original))

            print(f"Duplicate: {file.name}")
            print(f"       of: {original.name}")

            # A dry run exercises extraction and duplicate discovery but leaves
            # every extracted file in place for inspection.
            if not dry_run:
                file.unlink()

        else:
            seen[digest] = file

    return len(files), len(seen), duplicates

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed PDF path, optional output directory, and duplicate-handling
        options.

    Raises:
        SystemExit: If arguments are invalid or argparse handles an immediate
            action such as ``--help`` or ``--version``.
    """
    parser = argparse.ArgumentParser(description="Extract embedded PDF images and remove exact duplicates.")
    parser.add_argument(
        "pdf",
        type=Path,
        metavar="INPUT.pdf",
        help="PDF file from which to extract embedded images",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="DIRECTORY",
        help="output directory (default: INPUT_images beside the PDF)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="extract images and report duplicates without deleting them",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    return parser.parse_args()

def main() -> int:
    """Run the command-line PDF image extractor.

    Returns:
        Zero on success or one when validation, extraction, or file I/O fails.
    """
    args = parse_args()

    # Expand ~ consistently while leaving relative paths readable in messages.
    pdf = args.pdf.expanduser()

    try:
        # Validate before creating an output directory or launching pdfimages.
        if not pdf.is_file():
            raise FileNotFoundError(f"PDF file not found: {pdf}")
        if pdf.suffix.lower() != ".pdf":
            raise ValueError(f"input file must have a .pdf extension: {pdf}")

        # By default, keep extracted files beside the source PDF in a directory
        # named after the document, for example report_images.
        output_dir = (
            args.output.expanduser()
            if args.output
            else pdf.parent / f"{pdf.stem}_images"
        )
        # Resolve the executable once and pass its exact path to subprocess.
        pdfimages = require_pdfimages()
        extract_images(pdf, output_dir, pdfimages)

        print("Checking for exact duplicates...")
        print()

        total, unique, duplicates = remove_duplicates(output_dir, dry_run=args.dry_run)
    # Convert expected validation, filesystem, and tool failures into a concise
    # command-line error instead of displaying a Python traceback.
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print()
    print("Summary")
    print("-------")
    print(f"Extracted:   {total}")
    print(f"Unique:      {unique}")
    print(f"Duplicates:  {len(duplicates)}")

    if args.dry_run:
        print()
        print("Dry run enabled: no files were deleted.")
    else:
        print()
        print("Cleaned images saved to:")
        print(output_dir)
    return 0

if __name__ == "__main__":
    # Returning through SystemExit exposes main's status code to shells and CI.
    raise SystemExit(main())
