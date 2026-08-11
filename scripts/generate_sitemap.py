#!/usr/bin/env python3
# generate_sitemap.py
# Copyright (c) 2026 PiSaucer
# Licensed under the MIT License
# Version 1.2.0

# Generate a sitemap.xml file from HTML files below a website root.
# Usage: python3 generate_sitemap.py --root SITE_DIR --base-url https://example.com/

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse
from xml.sax.saxutils import escape

def find_html_files(root: Path) -> list[Path]:
    """Find HTML files recursively below a website root.

    Args:
        root: Directory to scan.

    Returns:
        HTML and HTM files sorted case-insensitively by relative POSIX path.
    """
    # Sort on relative POSIX paths so output is stable across operating systems.
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".html", ".htm"}
        ),
        key=lambda path: path.relative_to(root).as_posix().lower(),
    )

def build_url(base_url: str, root: Path, file_path: Path, pretty_urls: bool = False) -> str:
    """Build the public URL for a file below the website root.

    Args:
        base_url: Absolute URL corresponding to ``root``.
        root: Local website root directory.
        file_path: Local file located below ``root``.

    Returns:
        An absolute URL with unsafe path characters percent-encoded.

    Raises:
        ValueError: If ``file_path`` is not below ``root``.
    """
    relative_path = file_path.relative_to(root).as_posix()
    if pretty_urls and relative_path.lower().endswith("index.html"):
        relative_path = relative_path[:-len("index.html")]
    
    # Preserve path separators while escaping spaces and other unsafe characters.
    encoded_path = quote(relative_path, safe="/")
    return urljoin(base_url.rstrip("/") + "/", encoded_path)

def format_last_modified(file_path: Path) -> str:
    """Format a file's modification time for a sitemap.

    Args:
        file_path: File whose modification time should be read.

    Returns:
        A UTC timestamp in ``YYYY-MM-DDTHH:MM:SSZ`` format.

    Raises:
        OSError: If file metadata cannot be read.
    """
    modified = datetime.fromtimestamp(file_path.stat().st_mtime, timezone.utc)
    return modified.strftime("%Y-%m-%dT%H:%M:%SZ")

def write_sitemap(entries: list[tuple[str, str]], output: Path) -> None:
    """Write URL and modification-date entries as sitemap XML.

    Args:
        entries: Pairs of absolute URL and W3C-formatted modification date.
        output: Destination XML path.

    Raises:
        OSError: If the output directory or file cannot be created.
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for url, last_modified in entries:
        # XML-escape URLs because valid URL query characters include ampersands.
        lines.extend(
            [
                "  <url>",
                f"    <loc>{escape(url)}</loc>",
                f"    <lastmod>{last_modified}</lastmod>",
                "  </url>",
            ]
        )

    lines.append("</urlset>")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")

def write_text_sitemap(entries: list[tuple[str, str]], output: Path) -> None:
    """Write a plain-text sitemap containing one absolute URL per line."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(f"{url}\n" for url, _last_modified in entries),
        encoding="utf-8",
    )

def validate_base_url(base_url: str) -> str:
    """Validate and normalize a public website base URL.

    Args:
        base_url: Candidate HTTP or HTTPS base URL.

    Returns:
        The URL with unsafe path characters percent-encoded.

    Raises:
        ValueError: If the URL is not absolute HTTP(S) or contains a query
            string or fragment.
    """
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--base-url must be an absolute HTTP or HTTPS URL")
    if parsed.query or parsed.fragment:
        raise ValueError("--base-url cannot contain a query string or fragment")
    
    # Keep existing percent escapes and URL path delimiters from being encoded.
    encoded_path = quote(parsed.path, safe="/%:@")
    return parsed._replace(path=encoded_path).geturl()


def generate_sitemap(
    root: Path,
    base_url: str,
    output: Path | None = None,
    exclude: list[str] | None = None,
    pretty_urls: bool = False,
    text_output: Path | None = None,
) -> int:
    """Generate a sitemap and return the number of URLs written."""
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"root directory not found: {root}")

    normalized_base_url = validate_base_url(base_url)
    destination = output.expanduser().resolve() if output else root / "sitemap.xml"
    excluded_patterns = exclude or []
    html_files = [
        path for path in find_html_files(root)
        if not any(path.relative_to(root).match(pattern) for pattern in excluded_patterns)
    ]
    entries = [
        (build_url(normalized_base_url, root, path, pretty_urls), format_last_modified(path))
        for path in html_files
    ]
    write_sitemap(entries, destination)
    if text_output is not None:
        write_text_sitemap(entries, text_output.expanduser().resolve())
    return len(entries)

def parse_args() -> argparse.Namespace:
    """Parse command-line options.

    Returns:
        Parsed root directory, base URL, and optional output path.

    Raises:
        SystemExit: If arguments are invalid or argparse handles an immediate
            action such as ``--help``.
    """
    parser = argparse.ArgumentParser(
        description="Generate sitemap.xml from HTML files."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Project root to scan (default: this file's directory)",
    )
    parser.add_argument(
        "--base-url",
        default="https://web.eecs.utk.edu/~asaucer/",
        help="Public website base URL",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output path (default: ROOT/sitemap.xml)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="Exclude relative paths matching this glob (repeatable)",
    )
    parser.add_argument(
        "--pretty-urls",
        action="store_true",
        help="Write directory URLs instead of URLs ending in index.html",
    )
    parser.add_argument(
        "--text-output",
        type=Path,
        help="Also write a plain-text sitemap with one URL per line",
    )
    return parser.parse_args()

def main() -> int:
    """Run the sitemap generator.

    Returns:
        Zero on success or one when validation, scanning, or writing fails.
    """
    args = parse_args()
    try:
        root = args.root.expanduser().resolve()
        output = args.output.expanduser().resolve() if args.output else root / "sitemap.xml"
        entry_count = generate_sitemap(
            root=root,
            base_url=args.base_url,
            output=output,
            exclude=args.exclude,
            pretty_urls=args.pretty_urls,
            text_output=args.text_output,
        )
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Wrote {output} ({entry_count} URLs)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
