#!/usr/bin/env python3
# whisper_transcribe.py
# Copyright (c) 2026 PiSaucer
# Licensed under the MIT License
# Version 1.0.0

# Find audio files without Whisper transcripts and transcribe the missing files.
# Usage: python3 whisper_transcribe.py DIRECTORY [options]

import argparse
import sys
from pathlib import Path
from typing import List, Set, Optional

# Required package: pip install whisper
import whisper

VERSION = "1.0.0"

DEFAULT_FORMATS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}
OUTPUT_FORMATS = (
    "txt",
    "vtt",
    "srt",
    "tsv",
    "json",
)

def parse_formats(value: str) -> Set[str]:
    """Parse a comma-separated list of audio file extensions.

    Args:
        value: Comma-separated extensions such as ``mp3,m4a,wav``.

    Returns:
        Normalized lowercase extensions including the leading dot.

    Raises:
        argparse.ArgumentTypeError: If no valid extensions are supplied.
    """
    formats = set()

    for item in value.split(","):
        extension = item.strip().lower()
        if not extension:
            continue
        if not extension.startswith("."):
            extension = f".{extension}"
        formats.add(extension)
    if not formats:
        raise argparse.ArgumentTypeError("at least one audio format is required")

    return formats

def find_audio_files(directory: Path, formats: Set[str], recursive: bool = True) -> List[Path]:
    """Find supported audio files below a directory.

    Args:
        directory: Directory to search.
        formats: Accepted lowercase file extensions.
        recursive: Whether to search nested directories.

    Returns:
        Matching audio files sorted case-insensitively by path.

    Raises:
        FileNotFoundError: If the directory does not exist.
        ValueError: If the input path is not a directory.
        OSError: If the directory cannot be searched.
    """
    if not directory.exists():
        raise FileNotFoundError(f"directory not found: {directory}")

    if not directory.is_dir():
        raise ValueError(f"input path is not a directory: {directory}")

    iterator = directory.rglob("*") if recursive else directory.glob("*")
    files = [path for path in iterator if path.is_file() and path.suffix.lower() in formats]
    return sorted(files, key=lambda path: str(path).lower())

def transcript_path(audio_file: Path, output_format: str, output_dir: Optional[Path] = None) -> Path:
    """Determine the expected transcript path for an audio file.

    Args:
        audio_file: Source audio file.
        output_format: Whisper output format.
        output_dir: Optional common output directory.

    Returns:
        Expected transcript path.
    """
    filename = f"{audio_file.stem}.{output_format}"
    if output_dir is not None:
        return output_dir / filename
    return audio_file.parent / filename

def find_missing_transcripts(audio_files: List[Path], output_format: str, output_dir: Optional[Path] = None) -> List[Path]:
    """Find audio files whose expected transcript does not exist.

    Args:
        audio_files: Audio files to inspect.
        output_format: Whisper output format.
        output_dir: Optional common transcript directory.

    Returns:
        Audio files without a matching transcript.
    """
    return [
        audio_file
        for audio_file in audio_files
        if not transcript_path(audio_file, output_format, output_dir).is_file()
    ]

def transcribe_audio(
    model,
    audio_file: Path,
    output_format: str,
    output_dir: Optional[Path] = None,
    language: Optional[str] = None,
) -> Path:
    """Transcribe one audio file with Whisper.

    Args:
        model: Loaded Whisper model.
        audio_file: Audio file to transcribe.
        output_format: Transcript output format.
        output_dir: Optional common output directory.
        language: Optional Whisper language code.

    Returns:
        Path to the generated transcript.

    Raises:
        OSError: If output files cannot be written.
        RuntimeError: If Whisper transcription fails.
    """
    destination = output_dir if output_dir is not None else audio_file.parent
    destination.mkdir(parents=True, exist_ok=True)

    options = {}

    if language:
        options["language"] = language

    result = model.transcribe(str(audio_file), **options)
    writer = whisper.utils.get_writer(output_format, str(destination))
    writer(result, str(audio_file))

    return transcript_path(audio_file, output_format, output_dir)

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed directory, Whisper model, audio formats, and output options.

    Raises:
        SystemExit: If arguments are invalid or argparse handles an immediate
            action such as ``--help`` or ``--version``.
    """
    parser = argparse.ArgumentParser(description=("Find audio files without matching Whisper transcripts and transcribe the missing files."))
    parser.add_argument(
        "directory",
        type=Path,
        help="directory containing audio files",
    )
    parser.add_argument(
        "-m",
        "--model",
        default="turbo",
        help="Whisper model to use (default: turbo)",
    )
    parser.add_argument(
        "-l",
        "--language",
        help="audio language code such as en (default: auto-detect)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        help="transcript output directory (default: beside each audio file)",
    )
    parser.add_argument(
        "--output-format",
        choices=OUTPUT_FORMATS,
        default="all",
        help="Whisper output format (default: all)",
    )
    parser.add_argument(
        "--formats",
        type=parse_formats,
        default=DEFAULT_FORMATS,
        metavar="FORMATS",
        help=(
            "comma-separated audio extensions "
            "(default: aac,flac,m4a,mp3,ogg,opus,wav,wma)"
        ),
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="do not search subdirectories",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list missing transcripts without running Whisper",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    return parser.parse_args()

def main() -> int:
    """Find missing transcripts and run Whisper on each unfinished file.

    Returns:
        Zero on success or one when validation, transcription, model loading,
        or file I/O fails.
    """
    args = parse_args()

    directory = args.directory.expanduser()
    output_dir = args.output_dir.expanduser() if args.output_dir else None

    try:
        audio_files = find_audio_files(directory, args.formats, recursive=not args.no_recursive)
        missing_files = find_missing_transcripts(audio_files, args.output_format, output_dir)
        completed = len(audio_files) - len(missing_files)

        print(f"Found {len(audio_files)} audio file(s)")
        print(f"Already transcribed: {completed}")
        print(f"Missing transcripts: {len(missing_files)}")

        if not missing_files:
            print("No transcription needed.")
            return 0

        if args.dry_run:
            print()

            for audio_file in missing_files:
                print(audio_file)

            print()
            print("Dry run enabled: no files were transcribed.")
            return 0

        print(f"Loading Whisper model: {args.model}")
        model = whisper.load_model(args.model)

        completed_count = 0
        failed_count = 0

        for index, audio_file in enumerate(missing_files, start=1):
            print()
            print(f"[{index}/{len(missing_files)}] Transcribing: {audio_file}")

            try:
                output_file = transcribe_audio(model, audio_file, args.output_format, output_dir, args.language)
            except Exception as error:
                failed_count += 1
                print(
                    f"Error transcribing {audio_file}: {error}",
                    file=sys.stderr,
                )
                continue

            completed_count += 1
            print(f"Transcript: {output_file}")

    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print()
    print(f"Completed: {completed_count} file(s) transcribed, \n{failed_count} failed, {completed} skipped")
    return 1 if failed_count else 0

if __name__ == "__main__":
    raise SystemExit(main())
