#!/usr/bin/env python3
# goodnotes-audio-extract.py
# Copyright (c) 2026 PiSaucer
# Licensed under the MIT License
# Version 1.1.0

# Extract Goodnotes audio attachments, convert them to MP3, and write a CSV index.
# Usage: python3 goodnotes-audio-extract.py --goodnotes Notes.goodnotes [options]

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Optional, List, Tuple, Dict

def require_command(name: str) -> str:
    """Locate a required executable on ``PATH``.

    Args:
        name: Executable name to locate.

    Returns:
        Resolved executable path reported by ``shutil.which``.

    Raises:
        RuntimeError: If the executable cannot be found.
    """
    executable = shutil.which(name)
    if not executable:
        raise RuntimeError(f"{name} not found in PATH")
    return executable

def collision_safe_path(directory: Path, stem: str, suffix: str) -> Path:
    """Choose a path that does not overwrite an existing file.

    Args:
        directory: Parent directory for the candidate.
        stem: Preferred filename stem.
        suffix: Filename extension, including its leading dot.

    Returns:
        The preferred path when available, otherwise a path with the first
        available numeric suffix.
    """
    candidate = directory / f"{stem}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate

def safe_extract_goodnotes(
    goodnotes_path: Path, extract_dir: Path, overwrite: bool = False
) -> Path:
    """Safely extract a Goodnotes ZIP archive.

    Args:
        goodnotes_path: Input ``.goodnotes`` archive.
        extract_dir: Directory into which archive members are extracted.
        overwrite: Whether to replace files already present in ``extract_dir``.

    Returns:
        The extraction directory.

    Raises:
        FileNotFoundError: If the input archive does not exist.
        ValueError: If the extension or ZIP data is invalid, or an entry could
            escape the extraction root or create a symbolic link.
        OSError: If directories or extracted files cannot be created.
    """
    if not goodnotes_path.is_file():
        raise FileNotFoundError(f"Goodnotes file not found: {goodnotes_path}")
    if goodnotes_path.suffix.lower() != ".goodnotes":
        raise ValueError(f"input must have a .goodnotes extension: {goodnotes_path}")

    print(f"Extracting Goodnotes archive: {goodnotes_path} -> {extract_dir}")

    extract_dir.mkdir(parents=True, exist_ok=True)

    # Resolve once so every archive member can be checked against the same root.
    extraction_root = extract_dir.resolve()

    try:
        archive = zipfile.ZipFile(goodnotes_path, "r")
    except zipfile.BadZipFile as error:
        raise ValueError(f"invalid Goodnotes archive: {goodnotes_path}") from error

    member_count = 0
    with archive:
        for info in archive.infolist():
            member = PurePosixPath(info.filename)

            # Reject absolute paths, parent traversal, and archived symbolic links.
            unix_mode = info.external_attr >> 16
            is_symlink = (unix_mode & 0o170000) == 0o120000
            if member.is_absolute() or ".." in member.parts or is_symlink:
                raise ValueError(f"unsafe archive entry: {info.filename}")

            target = extract_dir.joinpath(*member.parts)
            target_resolved = target.resolve()

            # commonpath catches platform-specific traversal that PurePosixPath
            # validation alone may not recognize after conversion to a local path.
            if os.path.commonpath((str(extraction_root), str(target_resolved))) != str(
                extraction_root
            ):
                raise ValueError(f"unsafe archive entry: {info.filename}")

            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or overwrite:
                with archive.open(info, "r") as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                member_count += 1

            # Preserve the entry timestamp for date fallback and CSV indexing.
            try:
                timestamp = datetime(*info.date_time).timestamp()
                os.utime(target, (timestamp, timestamp))
            except (OSError, OverflowError, ValueError):
                pass

    print(f"Extraction complete: {member_count} file(s) written to {extract_dir}")
    return extract_dir


def find_attachment_files(root: Path) -> List[Path]:
    """Find files stored below Goodnotes attachment directories.

    Args:
        root: Root of an extracted Goodnotes archive.

    Returns:
        Unique files below directories named ``attachments``, sorted
        case-insensitively by path.
    """
    # Goodnotes may contain multiple notebooks with separate attachment trees.
    attachments = []
    for directory in root.rglob("*"):
        if directory.is_dir() and directory.name.lower() == "attachments":
            attachments.extend(path for path in directory.rglob("*") if path.is_file())
    return sorted(set(attachments), key=lambda path: str(path).lower())

def probe_audio(path: Path, ffprobe: str) -> dict:
    """Probe the first audio stream in a media file.

    Args:
        path: Media file to inspect.
        ffprobe: Path to the ffprobe executable.

    Returns:
        Parsed ffprobe JSON when an audio stream is present; otherwise an empty
        dictionary.

    Raises:
        OSError: If ffprobe cannot be started.
    """
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,duration,bit_rate:format=duration,bit_rate:format_tags",
        "-of",
        "json",
        str(path),
    ]
    # Unsupported attachments are expected, so probe failures become empty data.
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return {}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return data if data.get("streams") else {}

def audio_duration(probe: dict) -> float:
    """Read an audio duration from ffprobe data.

    Args:
        probe: Parsed ffprobe result.

    Returns:
        Duration in seconds, or ``0.0`` if no valid duration is available.
    """
    stream = (probe.get("streams") or [{}])[0]

    # Some containers expose duration only at the format level.
    raw_duration = stream.get("duration") or probe.get("format", {}).get("duration") or 0
    try:
        return float(raw_duration)
    except (TypeError, ValueError):
        return 0.0

def format_duration(seconds: float) -> str:
    """Format a duration in seconds as an ``HH:MM:SS`` string.

    Args:
        seconds: Duration in seconds.

    Returns:
        A zero-padded ``HH:MM:SS`` string. Fractional seconds are truncated.
    """
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def iso_utc_micro(dt: datetime) -> str:
    """Format a ``datetime`` as ISO 8601 UTC with microseconds and a ``Z`` suffix.

    Args:
        dt: Datetime to format (treated as UTC regardless of tzinfo).

    Returns:
        A string such as ``2026-08-17T18:38:56.000000Z``.
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

def recording_date(path: Path, probe: dict) -> str:
    """Determine a recording date from metadata or file modification time.

    Args:
        path: Media file used for the modification-time fallback.
        probe: Parsed ffprobe result.

    Returns:
        An ISO 8601 UTC timestamp with microseconds, such as
        ``2026-08-17T18:38:56.000000Z``. Metadata tags that only carry a date
        (or a bare year) are expanded to midnight; unparseable or absent
        metadata falls back to the attachment's modification time.

    Raises:
        OSError: If fallback file metadata cannot be read.
    """
    tags = probe.get("format", {}).get("tags") or {}
    normalized_tags = {str(key).lower(): value for key, value in tags.items()}

    for key in ("date", "originaldate", "recordingdate", "creation_time", "year"):
        value = normalized_tags.get(key)
        if not value:
            continue
        value = str(value).strip()
        if len(value) == 4 and value.isdigit():
            value = f"{value}-01-01"
        for candidate in (value, value.replace("Z", "+00:00")):
            try:
                return iso_utc_micro(datetime.fromisoformat(candidate))
            except ValueError:
                continue
        for date_format in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%m/%d/%Y"):
            try:
                return iso_utc_micro(datetime.strptime(value, date_format))
            except ValueError:
                continue

    return iso_utc_micro(datetime.fromtimestamp(path.stat().st_mtime))


def date_filename_stem(date_value: str, fallback_path: Path) -> str:
    """Convert a recording date to a ``YYYY-MM-DD`` filename stem.

    Args:
        date_value: Recording date returned by ``recording_date``.
        fallback_path: Source file whose mtime is used if the date cannot be parsed.

    Returns:
        A filename stem such as ``2026-08-19``.
    """
    value = date_value.strip()
    candidates = [value, value.replace("Z", "+00:00")]

    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate).strftime("%Y-%m-%d")
        except ValueError:
            pass

    for date_format in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, date_format).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return datetime.fromtimestamp(fallback_path.stat().st_mtime).strftime("%Y-%m-%d")

def copy_or_convert_audio(
    source: Path,
    output_dir: Path,
    ffmpeg: str,
    ffprobe: str,
    bitrate: str,
    min_duration: float,
    output_stem: str,
) -> Tuple[Optional[Path], str, float]:
    """Validate an audio attachment and produce an MP3.

    Args:
        source: Attachment to inspect and process.
        output_dir: Directory for the resulting MP3.
        ffmpeg: Path to the ffmpeg executable.
        ffprobe: Path to the ffprobe executable.
        bitrate: ffmpeg MP3 bitrate value, such as ``192k``.
        min_duration: Minimum accepted duration in seconds; recordings must be
            strictly longer than this value.
        output_stem: Preferred output filename stem.

    Returns:
        The output path, status text, and duration in seconds. The path is ``None``
        when the input is skipped or conversion validation fails.

    Raises:
        OSError: If a subprocess cannot start or a filesystem operation fails.
    """
    probe = probe_audio(source, ffprobe)
    if not probe:
        return None, "no audio stream", 0.0

    duration = audio_duration(probe)
    if duration <= min_duration:
        return None, f"duration {duration:.2f}s does not exceed {min_duration:.2f}s", duration

    stream = probe["streams"][0]
    is_mp3 = str(stream.get("codec_name", "")).lower() == "mp3"
    output_path = collision_safe_path(output_dir, output_stem, ".mp3")

    if is_mp3:
        # Avoid generation loss when the attachment is already MP3.
        shutil.copy2(source, output_path)
        action = "copied"
    else:
        # Convert beside the final path and publish only after ffmpeg succeeds.
        temporary_path = output_path.with_name(f"{output_path.stem}.part.mp3")
        command = [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-map_metadata",
            "0",
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            str(temporary_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            temporary_path.unlink(missing_ok=True)
            details = result.stderr.strip().splitlines()
            return None, details[-1] if details else "ffmpeg conversion failed", duration
        temporary_path.replace(output_path)
        action = "converted"

    # Re-probe the output rather than assuming a successful exit produced a
    # usable recording.
    output_probe = probe_audio(output_path, ffprobe)
    output_duration = audio_duration(output_probe)
    if not output_probe or output_duration <= min_duration:
        output_path.unlink(missing_ok=True)
        return None, "output MP3 failed validation", output_duration

    # Preserve the archive timestamp after copying or conversion.
    try:
        source_mtime = source.stat().st_mtime
        os.utime(output_path, (source_mtime, source_mtime))
    except OSError:
        pass

    return output_path, f"{action}, {output_duration:.2f}s", output_duration

CSV_FIELDNAMES = ["original_file", "current_file", "date", "duration", "duration_string"]

def read_existing_csv(csv_path: Optional[Path]) -> Tuple[List[dict], set]:
    """Load an existing audio index.

    Args:
        csv_path: Existing CSV path, or ``None`` to start without prior rows.

    Returns:
        Normalized row dictionaries and the set of already-indexed original
        filenames (used to skip re-processing an attachment).

    Raises:
        OSError: If the CSV cannot be opened.
        csv.Error: If CSV parsing fails.
    """
    if csv_path is None or not csv_path.exists():
        return [], set()

    rows = []
    existing_originals = set()

    # utf-8-sig accepts both ordinary UTF-8 and spreadsheet-exported BOM files.
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            original_file = row.get("original_file", "").strip()
            current_file = row.get("current_file", "").strip()
            date = row.get("date", "").strip()
            duration = row.get("duration", "").strip()
            duration_string = row.get("duration_string", "").strip()
            if original_file:
                rows.append(
                    {
                        "original_file": original_file,
                        "current_file": current_file,
                        "date": date,
                        "duration": duration,
                        "duration_string": duration_string,
                    }
                )
                existing_originals.add(original_file)
    return rows, existing_originals

def write_csv(csv_path: Path, rows: List[dict]) -> None:
    """Write a stable, date-sorted audio index.

    Args:
        csv_path: Destination CSV path.
        rows: Dictionaries containing the ``CSV_FIELDNAMES`` fields.

    Raises:
        OSError: If the destination directory or file cannot be written.
        csv.Error: If CSV serialization fails.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(
            sorted(rows, key=lambda row: (row.get("date", ""), row.get("original_file", "")))
        )

def parse_args() -> argparse.Namespace:
    """Parse command-line options.

    Returns:
        Parsed archive, output, indexing, conversion, and filtering options.

    Raises:
        SystemExit: If arguments are invalid or argparse handles an immediate
            action such as ``--help``.
    """
    parser = argparse.ArgumentParser(
        description="Extract audio attachments from a Goodnotes file as MP3s."
    )
    parser.add_argument(
        "-g", "--goodnotes", required=True, type=Path, help="Input .goodnotes file"
    )
    parser.add_argument(
        "-p",
        "--processed-dir",
        "--output-dir",
        dest="output_dir",
        type=Path,
        help="MP3 output directory (default: GOODNOTES_STEM_audio)",
    )
    parser.add_argument(
        "-e",
        "--extract-dir",
        type=Path,
        help="Archive extraction directory (default: GOODNOTES_STEM_extract)",
    )
    parser.add_argument("-i", "--input-csv", type=Path, help="Existing CSV index")
    parser.add_argument("-o", "--output-csv", type=Path, help="Updated CSV index")
    parser.add_argument(
        "--skip-input-csv",
        action="store_true",
        help="Ignore the existing input CSV and start a new index",
    )
    parser.add_argument(
        "--overwrite-extracted",
        action="store_true",
        help="Replace files already present in the extraction directory",
    )
    parser.add_argument(
        "--skip-extract",
        "--no-reextract",
        dest="skip_extract",
        action="store_true",
        help=(
            "Skip re-extracting the .goodnotes archive if the extraction "
            "directory already exists. By default the archive is re-extracted "
            "on every run."
        ),
    )
    parser.add_argument(
        "--bitrate", default="192k", help="Converted MP3 bitrate (default: 192k)"
    )
    parser.add_argument(
        "--min-duration",
        type=float,
        default=2.0,
        help="Minimum recording duration in seconds (default: 2.0)",
    )
    return parser.parse_args()

def main() -> int:
    """Run the Goodnotes audio extraction workflow.

    Returns:
        Zero on success or one when validation, extraction, conversion setup,
        or file I/O fails.
    """
    args = parse_args()
    goodnotes_path = args.goodnotes.expanduser()
    base_path = goodnotes_path.with_suffix("")
    extract_dir = (
        args.extract_dir.expanduser()
        if args.extract_dir
        else base_path.with_name(f"{base_path.name}_extract")
    )
    output_dir = (
        args.output_dir.expanduser()
        if args.output_dir
        else base_path.with_name(f"{base_path.name}_audio")
    )

    if args.min_duration < 0:
        print("Error: --min-duration cannot be negative", file=sys.stderr)
        return 1

    explicit_input_csv = None
    if args.input_csv:
        explicit_input_csv = args.input_csv.expanduser()
        if not explicit_input_csv.is_file():
            print(f"Error: input CSV not found: {explicit_input_csv}", file=sys.stderr)
            return 1

    output_csv = (
        args.output_csv.expanduser()
        if args.output_csv
        else explicit_input_csv or output_dir / "mp3_files.csv"
    )

    # If no --input-csv was given, still load prior rows from the output CSV
    # path itself when it already exists, so reruns don't wipe out previously
    # exported entries.
    input_csv = None
    if not args.skip_input_csv:
        if explicit_input_csv is not None:
            input_csv = explicit_input_csv
        elif output_csv.is_file():
            input_csv = output_csv

    new_rows: List[dict] = []
    skipped = 0

    try:
        ffmpeg = require_command("ffmpeg")
        ffprobe = require_command("ffprobe")

        if args.skip_extract and extract_dir.is_dir():
            print(f"Skipping re-extraction; using existing extraction directory: {extract_dir}")
            extracted_root = extract_dir
        else:
            extracted_root = safe_extract_goodnotes(
                goodnotes_path, extract_dir, args.overwrite_extracted
            )

        attachments = find_attachment_files(extracted_root)
        if not attachments:
            raise ValueError("no 'attachments' directory found in the Goodnotes archive")

        output_dir.mkdir(parents=True, exist_ok=True)
        all_rows, existing_originals = read_existing_csv(input_csv)

        print(f"Found {len(attachments)} attachment(s); {len(existing_originals)} already indexed")

        for attachment in attachments:
            original_file = attachment.name

            if original_file in existing_originals:
                skipped += 1
                print(f"Skipped (already indexed): {original_file}")
                continue

            source_probe = probe_audio(attachment, ffprobe)
            date = recording_date(attachment, source_probe)
            output_stem = date_filename_stem(date, attachment)
            output_path, details, duration = copy_or_convert_audio(
                attachment,
                output_dir,
                ffmpeg,
                ffprobe,
                args.bitrate,
                args.min_duration,
                output_stem,
            )
            if output_path is None:
                skipped += 1
                print(f"Skipped {original_file}: {details}", file=sys.stderr)
                continue

            row = {
                "original_file": original_file,
                "current_file": output_path.name,
                "date": date,
                "duration": f"{duration:.2f}",
                "duration_string": format_duration(duration),
            }
            new_rows.append(row)
            all_rows.append(row)
            existing_originals.add(original_file)

            print(f"Extracted {original_file} -> {output_path.name} ({details})")

            # Write the CSV after every successful extraction so progress is
            # never lost if a later attachment fails.
            write_csv(output_csv, all_rows)
            print(f"Updated CSV index: {output_csv}")

        if not new_rows:
            # Make sure the CSV still reflects any pre-existing rows even when
            # nothing new was extracted this run.
            write_csv(output_csv, all_rows)

    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"\nCompleted: {len(new_rows)} audio file(s) extracted, {skipped} skipped")
    print(f"MP3 directory: {output_dir}")
    print(f"CSV index: {output_csv}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
