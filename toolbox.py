#!/usr/bin/env python3
# toolbox.py
# Copyright (c) 2026 PiSaucer
# Licensed under the MIT License

# CLI/TUI to browse, download, verify, and run scripts from a toolbox manifest.

import sys
import argparse
import curses
import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile
import textwrap
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from rich.console import Console
from rich.text import Text

__version__ = "1.0.0"
DEFAULT_URL = "https://pisaucer.github.io/toolbox/manifest.json"
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
TOOLBOX_ART = [
    " _              _ _               ",
    "| |_ ___   ___ | | |__   _____  __",
    "| __/ _ \\ / _ \\| | '_ \\ / _ \\ \\/ /",
    "| || (_) | (_) | | |_) | (_) >  < ",
    " \\__\\___/ \\___/|_|_.__/ \\___/_/\\_\\",
]
ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_BLUE = "\033[34m"
ANSI_GREEN = "\033[32m"
ANSI_CYAN = "\033[36m"
ANSI_YELLOW = "\033[33m"
console = Console(highlight=False)
error_console = Console(stderr=True, highlight=False)

def fetch_manifest(url: str) -> dict[str, Any]:
    """Fetch and validate a JSON manifest.

    Args:
        url: HTTP or HTTPS URL of the manifest.

    Returns:
        The decoded manifest object.

    Raises:
        OSError: If the network request fails.
        RuntimeError: If the server returns a non-200 status or the JSON root
            is not an object.
        json.JSONDecodeError: If the response is not valid JSON.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"toolbox-tui/{__version__}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(f"failed to fetch manifest: HTTP {status}")
        data = response.read()
    manifest = json.loads(data.decode("utf-8"))
    if not isinstance(manifest, dict):
        raise RuntimeError("manifest must be a JSON object")
    return manifest

def script_download_details(script: dict[str, Any]) -> tuple[str, str, str]:
    """Validate and extract a script's download metadata.

    Args:
        script: Manifest entry describing a script.

    Returns:
        A tuple containing the download URL, lowercase SHA-256 checksum, and
        filename derived from the URL.

    Raises:
        RuntimeError: If the URL, checksum, or derived filename is invalid.
    """
    download_url = script.get("download_url")
    expected_sha256 = script.get("sha256")

    if not isinstance(download_url, str) or not download_url.strip():
        raise RuntimeError("selected script is missing a download_url")
    if not isinstance(expected_sha256, str) or not SHA256_PATTERN.fullmatch(expected_sha256):
        raise RuntimeError("selected script is missing a valid SHA-256 checksum")

    filename = Path(unquote(urlparse(download_url).path)).name
    if not filename or filename in {".", ".."}:
        raise RuntimeError("selected script download URL has no filename")

    return download_url, expected_sha256.lower(), filename

def download_script(script: dict[str, Any], output_dir: Path) -> Path:
    """Download, verify, and atomically save a script.

    Args:
        script: Manifest entry containing download metadata.
        output_dir: Directory in which to save the downloaded file.

    Returns:
        The absolute path of the saved script.

    Raises:
        OSError: If the request or a filesystem operation fails.
        RuntimeError: If metadata is invalid, the response status is not 200,
            or checksum verification fails.
    """
    download_url, expected_sha256, filename = script_download_details(script)
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / filename

    request = urllib.request.Request(
        download_url,
        headers={"User-Agent": f"toolbox-tui/{__version__}"},
    )
    temporary_path: Path | None = None

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise RuntimeError(f"failed to download script: HTTP {status}")

            digest = hashlib.sha256()
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{filename}.",
                suffix=".tmp",
                dir=output_dir,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    digest.update(chunk)
                    temporary.write(chunk)

        actual_sha256 = digest.hexdigest()
        if actual_sha256 != expected_sha256:
            raise RuntimeError(
                "SHA-256 verification failed "
                f"(expected {expected_sha256}, got {actual_sha256})"
            )

        # Publish only fully downloaded content whose checksum has been verified.
        os.replace(temporary_path, destination)
        temporary_path = None
        return destination
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

def fetch_verified_script(script: dict[str, Any]) -> tuple[bytes, str]:
    """Fetch a script into memory and verify its checksum.

    Args:
        script: Manifest entry containing download metadata.

    Returns:
        A tuple containing the verified file contents and original filename.

    Raises:
        OSError: If the network request fails.
        RuntimeError: If metadata is invalid, the response status is not 200,
            or checksum verification fails.
    """
    download_url, expected_sha256, filename = script_download_details(script)
    request = urllib.request.Request(
        download_url,
        headers={"User-Agent": f"toolbox-tui/{__version__}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(f"failed to fetch script: HTTP {status}")
        contents = response.read()

    actual_sha256 = hashlib.sha256(contents).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            "SHA-256 verification failed "
            f"(expected {expected_sha256}, got {actual_sha256})"
        )
    return contents, filename

def get_scripts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract valid script entries from a manifest.

    Args:
        manifest: Decoded toolbox manifest.

    Returns:
        Script objects with nonempty string IDs, in manifest order.

    Raises:
        RuntimeError: If ``scripts`` is not a list or contains no valid entries.
    """
    scripts = manifest.get("scripts")
    if not isinstance(scripts, list):
        raise RuntimeError("manifest is missing a valid 'scripts' list")
    cleaned: list[dict[str, Any]] = []
    for script in scripts:
        if not isinstance(script, dict):
            continue
        sid = script.get("id")
        if not isinstance(sid, str) or not sid.strip():
            continue
        cleaned.append(script)
    if not cleaned:
        raise RuntimeError("manifest contains no valid scripts")
    return cleaned

def find_script(scripts: list[dict[str, Any]], query: str) -> dict[str, Any]:
    """Find one script by exact ID, name, filename, or filename stem.

    Args:
        scripts: Available manifest script entries.
        query: Case-insensitive lookup value.

    Returns:
        The single matching script entry.

    Raises:
        RuntimeError: If no script matches or multiple entries match.
    """
    wanted = query.strip().casefold()
    matches: list[dict[str, Any]] = []

    for script in scripts:
        candidates = {
            str(script.get("id", "")).strip().casefold(),
            str(script.get("name", "")).strip().casefold(),
        }
        download_url = script.get("download_url")
        if isinstance(download_url, str):
            filename = Path(unquote(urlparse(download_url).path)).name
            candidates.add(filename.casefold())
            candidates.add(Path(filename).stem.casefold())
        if wanted in candidates:
            matches.append(script)

    if not matches:
        available = ", ".join(str(script["id"]) for script in scripts)
        raise RuntimeError(f"script not found: {query!r}. Available scripts: {available}")
    if len(matches) > 1:
        matches_text = ", ".join(str(script["id"]) for script in matches)
        raise RuntimeError(f"script name is ambiguous: {query!r} matches {matches_text}")
    return matches[0]

def search_scripts(
    scripts: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    """Search script metadata using case-insensitive AND matching.

    Args:
        scripts: Available manifest script entries.
        query: Whitespace-delimited search terms.

    Returns:
        Entries whose searchable metadata contains every query term. An empty
        query returns the original list.
    """
    terms = query.strip().casefold().split()
    if not terms:
        return scripts

    matches: list[dict[str, Any]] = []
    for script in scripts:
        tags = script_tags(script)
        values = [
            script.get("id"),
            script.get("name"),
            script.get("description"),
            script.get("language"),
            script.get("category"),
            tags,
        ]
        haystack = " ".join(
            " ".join(str(item) for item in value)
            if isinstance(value, list)
            else str(value or "")
            for value in values
        ).casefold()
        if all(term in haystack for term in terms):
            matches.append(script)
    return matches

def script_tags(script: dict[str, Any]) -> list[str]:
    """Normalize a script entry's tags for display and search.

    Args:
        script: Manifest entry whose ``tags`` value may be a string or list.

    Returns:
        Nonempty, stripped string tags, or an empty list for unsupported data.
    """
    value = script.get("tags")
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        return []
    return [tag.strip() for tag in values if isinstance(tag, str) and tag.strip()]

def parse_tui_command(command: str) -> tuple[str, list[str]]:
    """Parse a command entered in the TUI.

    Args:
        command: Shell-like command text entered by the user.

    Returns:
        A normalized action and the arguments supplied to a ``run`` action.

    Raises:
        ValueError: If tokenization fails, the command is empty or unknown, or
            a non-``run`` action receives arguments.
    """
    parts = shlex.split(command)
    if not parts:
        raise ValueError("Enter download, run [arguments], help, or quit")

    aliases = {"d": "download", "r": "run", "q": "quit", "?": "help"}
    action = aliases.get(parts[0].casefold(), parts[0].casefold())
    if action not in {"download", "run", "help", "quit"}:
        raise ValueError(f"Unknown command: {parts[0]}")
    if action != "run" and len(parts) > 1:
        raise ValueError(f"{action} does not accept arguments")
    return action, parts[1:]

def temporary_script_command(script_path: Path, arguments: list[str]) -> list[str]:
    """Build an interpreter command for a temporary script.

    Args:
        script_path: Path to the downloaded temporary file.
        arguments: Command-line arguments to pass to the script.

    Returns:
        Command components suitable for ``subprocess.run``.

    Raises:
        RuntimeError: If the script is not a Python or shell file.
    """
    filename = script_path.name
    suffix = Path(filename).suffix.casefold()
    if suffix == ".py":
        return [sys.executable, str(script_path), *arguments]
    if suffix == ".sh":
        if os.name == "nt":
            raise RuntimeError(
                "shell scripts cannot run natively on Windows; download the "
                "script and run it in WSL or Git Bash"
            )
        return ["sh", str(script_path), *arguments]
    raise RuntimeError(
        f"cannot run {suffix or 'this file type'}; only .py and .sh scripts "
        "can be run directly"
    )

def run_streamed_script(script: dict[str, Any], arguments: list[str]) -> int:
    """Verify a remote script and run it from a temporary file.

    Args:
        script: Manifest entry containing the script's download metadata.
        arguments: Command-line arguments to pass to the script.

    Returns:
        The child process exit status.

    Raises:
        OSError: If fetching or temporary-file handling fails.
        RuntimeError: If verification fails, the file type is unsupported, or
            the child process cannot be started.
    """
    contents, filename = fetch_verified_script(script)
    suffix = Path(filename).suffix
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix="toolbox-",
        suffix=suffix,
    ) as temporary:
        temporary.write(contents)
        temporary.flush()
        script_path = Path(temporary.name)
        command = temporary_script_command(script_path, arguments)
        console.print(
            Text.assemble(("Running:", "bold cyan"), " ", shlex.join(command)),
            soft_wrap=True,
        )
        try:
            # Inherit stdin so interactive scripts can prompt the user.
            return subprocess.run(command, check=False).returncode
        except OSError as exc:
            raise RuntimeError(f"could not run {filename}: {exc}") from exc

def run_usage_examples(script: dict[str, Any]) -> list[str]:
    """Translate manifest usage examples into TUI commands.

    Args:
        script: Manifest entry that may contain a list of usage strings.

    Returns:
        Valid examples rewritten as ``:run`` commands. Malformed examples are
        omitted.
    """
    usage = script.get("usage")
    if not isinstance(usage, list):
        return []

    examples: list[str] = []
    for value in usage:
        if not isinstance(value, str):
            continue
        try:
            parts = shlex.split(value)
        except ValueError:
            continue
        if not parts:
            continue
        if Path(parts[0]).name.casefold() in {"python", "python3", "bash", "sh"}:
            parts = parts[2:]
        else:
            parts = parts[1:]
        examples.append(":run" + (f" {shlex.join(parts)}" if parts else ""))
    return examples

def colorize(text: str, *codes: str, stream: Any = None) -> str:
    """Conditionally wrap text in ANSI styling codes.

    Args:
        text: Text to style.
        *codes: ANSI escape sequences to prepend.
        stream: Output stream used to detect terminal support. Defaults to
            ``sys.stdout``.

    Returns:
        Styled text when color is supported and allowed; otherwise ``text``.
    """
    output = sys.stdout if stream is None else stream
    if not output.isatty() or os.environ.get("NO_COLOR") is not None:
        return text
    return "".join(codes) + text + ANSI_RESET

def print_download_receipt(script: dict[str, Any], destination: Path) -> None:
    """Print a receipt for a downloaded script.

    Args:
        script: Downloaded script's manifest entry.
        destination: Path at which the script was saved.

    Raises:
        RuntimeError: If the manifest entry's download metadata is invalid.
    """
    _, sha256, _ = script_download_details(script)
    name = str(script.get("name") or script["id"])
    console.print(Text.assemble(("Downloaded:", "bold cyan"), " ", (name, "bold")))
    console.print(Text.assemble(("SHA-256:", "bold yellow"), " ", (sha256, "yellow")))
    console.print(
        Text.assemble(("Saved to:", "bold green"), " ", (str(destination), "green"))
    )

def print_toolbox_art(
    message: str | None = None,
    message_color: str = ANSI_CYAN,
    stream: Any = None,
) -> None:
    """Print the toolbox banner and an optional message.

    Args:
        message: Text to print below the banner, if any.
        message_color: ANSI color to use for the optional message.
        stream: Destination stream. Defaults to ``sys.stdout``.
    """
    output = sys.stdout if stream is None else stream
    rich_console = Console(file=output, highlight=False)
    for line in TOOLBOX_ART:
        rich_console.print(line, style="bold blue")
    if message:
        style = {
            ANSI_CYAN: "bold cyan",
            ANSI_YELLOW: "bold yellow",
            ANSI_GREEN: "bold green",
            ANSI_BLUE: "bold blue",
        }.get(message_color, "bold")
        rich_console.print(message, style=style)

def clip_text(text: str, width: int) -> str:
    """Clip text to a display width.

    Args:
        text: Text to clip.
        width: Maximum number of characters to return.

    Returns:
        The original text if it fits, otherwise an ellipsis-terminated prefix.
        Nonpositive widths produce an empty string.
    """
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width == 1:
        return "…"
    return text[: width - 1] + "…"

def safe_addstr(win: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
    """Draw text without allowing curses boundary errors to escape.

    Args:
        win: Curses window to draw in.
        y: Zero-based row.
        x: Zero-based column.
        text: Text to draw; it is clipped to the remaining window width.
        attr: Optional curses display attributes.
    """
    height, width = win.getmaxyx()
    if y < 0 or y >= height or x >= width:
        return
    if x < 0:
        text = text[-x:]
        x = 0
    if not text:
        return
    max_len = max(0, width - x)
    if max_len <= 0:
        return
    try:
        win.addnstr(y, x, text, max_len, attr)
    except curses.error:
        pass

def draw_hline(win: curses.window, y: int, x: int, width: int) -> None:
    """Draw a horizontal curses line.

    Args:
        win: Curses window to draw in.
        y: Zero-based row.
        x: Zero-based starting column.
        width: Number of line characters to attempt to draw.
    """
    if width <= 0:
        return
    for i in range(width):
        try:
            win.addch(y, x + i, curses.ACS_HLINE)
        except curses.error:
            return

def draw_box(win: curses.window, y: int, x: int, h: int, w: int) -> None:
    """Draw a bordered rectangle while suppressing curses boundary errors.

    Args:
        win: Curses window to draw in.
        y: Zero-based top row.
        x: Zero-based left column.
        h: Box height in terminal cells.
        w: Box width in terminal cells.
    """
    if h < 2 or w < 2:
        return
    try:
        win.addch(y, x, curses.ACS_ULCORNER)
        win.addch(y, x + w - 1, curses.ACS_URCORNER)
        win.addch(y + h - 1, x, curses.ACS_LLCORNER)
        win.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER)
        for i in range(1, w - 1):
            win.addch(y, x + i, curses.ACS_HLINE)
            win.addch(y + h - 1, x + i, curses.ACS_HLINE)
        for i in range(1, h - 1):
            win.addch(y + i, x, curses.ACS_VLINE)
            win.addch(y + i, x + w - 1, curses.ACS_VLINE)
    except curses.error:
        pass

def init_colors() -> dict[str, int]:
    """Initialize the TUI color palette.

    Returns:
        A mapping from semantic style names to curses attributes. Monochrome
        attributes are returned when terminal colors are unavailable.
    """
    colors = {
        "banner": curses.A_BOLD,
        "title": curses.A_BOLD,
        "selected": curses.A_REVERSE | curses.A_BOLD,
        "muted": curses.A_DIM,
        "accent": curses.A_BOLD,
        "link": curses.A_UNDERLINE,
        "normal": 0,
    }

    if not curses.has_colors():
        return colors

    try:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_BLUE, -1)
        curses.init_pair(2, curses.COLOR_CYAN, -1)
        curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_WHITE)
        curses.init_pair(4, curses.COLOR_YELLOW, -1)

        colors["banner"] = curses.color_pair(1) | curses.A_BOLD
        colors["title"] = curses.color_pair(2) | curses.A_BOLD
        colors["selected"] = curses.color_pair(3) | curses.A_BOLD
        colors["accent"] = curses.color_pair(4) | curses.A_BOLD
        colors["link"] = curses.color_pair(2) | curses.A_UNDERLINE
    except curses.error:
        pass

    return colors

def detail_field_lines(
    label: str,
    value: str,
    width: int,
    style: str = "normal",
    link: str | None = None,
) -> list[tuple[str, str, str | None]]:
    """Wrap a labeled value into styled detail-pane lines.

    Args:
        label: Field label displayed before the first line.
        value: Field value to wrap.
        width: Maximum display width for each line.
        style: Semantic style name associated with every returned line.
        link: Optional hyperlink target associated with every returned line.

    Returns:
        Tuples containing rendered text, semantic style, and hyperlink target.
    """
    prefix = f"{label}: "
    available = max(1, width - len(prefix))
    wrapped = textwrap.wrap(
        value or "N/A",
        width=available,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=False,
    ) or ["N/A"]
    lines = [(prefix + wrapped[0], style, link)]
    continuation_width = max(1, width)
    for part in wrapped[1:]:
        lines.extend(
            (chunk, style, link)
            for chunk in textwrap.wrap(
                part,
                width=continuation_width,
                break_long_words=True,
                break_on_hyphens=False,
            )
        )
    return lines

def terminal_hyperlink(y: int, x: int, text: str, url: str) -> None:
    """Overlay an OSC 8 hyperlink after curses paints the screen.

    Args:
        y: Zero-based terminal row at which to place the link.
        x: Zero-based terminal column at which to place the link.
        text: Visible hyperlink text.
        url: HTTP or HTTPS hyperlink target.
    """
    if (
        not sys.stdout.isatty()
        or not url.startswith(("https://", "http://"))
        or any(ord(char) < 32 for char in url)
    ):
        return
    sys.stdout.write(
        f"\0337\033[{y + 1};{x + 1}H"
        f"\033]8;;{url}\033\\{text}\033]8;;\033\\"
        "\0338"
    )
    sys.stdout.flush()

def format_script_row(script: dict[str, Any], width: int) -> str:
    """Format a script for a fixed-width list row.

    Args:
        script: Manifest entry to display.
        width: Maximum display width.

    Returns:
        A clipped name, with the ID included when it differs from the name.
    """
    sid = str(script.get("id", "")).strip()
    name = str(script.get("name", "")).strip()

    if name and name != sid:
        text = f"{name} ({sid})"
    else:
        text = sid

    return clip_text(text, width)

def format_detail_line(label: str, value: str, width: int) -> str:
    """Format a labeled value for a fixed-width detail line.

    Args:
        label: Field label.
        value: Field value.
        width: Maximum display width.

    Returns:
        The labeled value clipped to ``width`` characters.
    """
    prefix = f"{label}: "
    if width <= len(prefix):
        return clip_text(prefix, width)
    return prefix + clip_text(value, width - len(prefix))

def tui_select(
    stdscr: curses.window, scripts: list[dict[str, Any]], url: str
) -> tuple[str, str, list[str]] | None:
    """Run the interactive script selector.

    Args:
        stdscr: Root curses window supplied by ``curses.wrapper``.
        scripts: Available manifest script entries.
        url: Manifest URL associated with the entries.

    Returns:
        A tuple containing the selected action, script ID, and run arguments,
        or ``None`` when the user quits without choosing an action.

    Note:
        The ``url`` argument is retained as part of the selector interface but
        is not currently displayed.
    """
    try:
        curses.curs_set(0)
    except curses.error:
        pass

    stdscr.keypad(True)
    colors = init_colors()

    selected = 0
    offset = 0
    query = ""
    input_mode: str | None = None
    input_text = ""
    message = ""
    detail_offset = 0
    focused_pane = "scripts"

    while True:
        filtered = search_scripts(scripts, query)
        if filtered:
            selected = min(selected, len(filtered) - 1)
        else:
            selected = 0
        current_scripts = filtered

        stdscr.erase()
        height, width = stdscr.getmaxyx()

        # Collapse the two-pane layout as terminal space becomes constrained.
        compact = height < 18 or width < 70
        ultra_compact = height < 12 or width < 45

        y = 0

        if not compact:
            for line in TOOLBOX_ART:
                x = max(0, (width - len(line)) // 2)
                safe_addstr(stdscr, y, x, line, colors["banner"])
                y += 1
            y += 1

        title = f"toolbox v{__version__}"
        subtitle = "Select a script"
        safe_addstr(stdscr, y, max(0, (width - len(title)) // 2), title, colors["title"])
        y += 1

        if not ultra_compact:
            safe_addstr(stdscr, y, max(0, (width - len(subtitle)) // 2), subtitle, colors["muted"])
            y += 1

        prompt = f"/ {query}" if query else "/ Search scripts and tags"
        safe_addstr(stdscr, y, 2, clip_text(prompt, max(1, width - 4)), colors["muted"])
        y += 1
        top = y + 1
        footer_y = height - 1

        if footer_y <= top:
            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord("q"), ord("Q")):
                return None
            continue

        if ultra_compact:
            list_x = 0
            list_y = top
            list_w = width
            list_h = max(1, footer_y - list_y)
            detail_mode = False
        elif compact:
            list_x = 1
            list_y = top
            list_w = max(10, width - 2)
            list_h = max(3, footer_y - list_y - 1)
            detail_mode = False
        else:
            list_x = 2
            list_y = top
            list_w = max(24, width // 2 - 3)
            list_h = max(6, footer_y - list_y - 1)
            detail_mode = True

        show_details = detail_mode or (compact and focused_pane == "details")

        if compact and not ultra_compact:
            draw_box(stdscr, list_y - 1, list_x - 1, list_h + 2, list_w + 2)
            safe_addstr(
                stdscr,
                list_y - 1,
                list_x + 1,
                " Details " if show_details else " Scripts ",
                colors["title"],
            )
        elif not compact:
            draw_box(stdscr, list_y - 1, list_x - 1, list_h + 2, list_w + 2)
            safe_addstr(
                stdscr,
                list_y - 1,
                list_x + 1,
                " Scripts ",
                colors["title"] if focused_pane == "scripts" else colors["accent"],
            )

        if detail_mode:
            detail_x = list_x + list_w + 3
            detail_y = list_y
            detail_w = max(20, width - detail_x - 2)
            detail_h = list_h

            draw_box(stdscr, detail_y - 1, detail_x - 1, detail_h + 2, detail_w + 2)
            safe_addstr(
                stdscr,
                detail_y - 1,
                detail_x + 1,
                " Details ",
                colors["title"] if focused_pane == "details" else colors["accent"],
            )
        else:
            if show_details:
                detail_x = list_x
                detail_y = list_y
                detail_w = list_w
                detail_h = list_h
            else:
                detail_x = detail_y = detail_w = detail_h = 0

        if selected < offset:
            offset = selected
        elif selected >= offset + list_h:
            offset = selected - list_h + 1

        visible = current_scripts[offset : offset + list_h]

        if not show_details or detail_mode:
            for row, script in enumerate(visible):
                idx = offset + row
                item_y = list_y + row

                if ultra_compact:
                    prefix = ">" if idx == selected else " "
                    line = f"{prefix} {format_script_row(script, max(1, list_w - 2))}"
                    attr = colors["selected"] if idx == selected else colors["normal"]
                    safe_addstr(stdscr, item_y, list_x, line.ljust(max(1, list_w)), attr)
                else:
                    prefix = "›" if idx == selected else " "
                    line = f" {prefix} {format_script_row(script, max(1, list_w - 3))}"
                    attr = colors["selected"] if idx == selected else colors["normal"]
                    safe_addstr(stdscr, item_y, list_x, line.ljust(max(1, list_w)), attr)

        if not current_scripts:
            if not show_details:
                safe_addstr(
                    stdscr, list_y, list_x + 1, "No matching scripts", colors["muted"]
                )
            selected_script = {}
        else:
            selected_script = current_scripts[selected]
        sid = str(selected_script.get("id", "")).strip()
        name = str(selected_script.get("name", "")).strip()
        desc = str(selected_script.get("description", "")).strip()
        tags = script_tags(selected_script)
        usage = run_usage_examples(selected_script)
        sha256 = str(selected_script.get("sha256", "")).strip()
        download = str(
            selected_script.get("download_url")
            or selected_script.get("url")
            or selected_script.get("download")
            or ""
        ).strip()

        # Hyperlinks are overlaid after curses refreshes to avoid escape-sequence
        # widths interfering with curses' screen-position accounting.
        visible_links: list[tuple[int, int, str, str]] = []
        if show_details:
            detail_lines: list[tuple[str, str, str | None]] = []
            detail_lines.extend(detail_field_lines("Name", name or sid, detail_w))
            detail_lines.extend(detail_field_lines("ID", sid, detail_w))
            detail_lines.extend(
                detail_field_lines("Tags", ", ".join(tags) if tags else "None", detail_w)
            )
            detail_lines.extend(
                detail_field_lines("SHA256", sha256, detail_w, "muted")
            )
            detail_lines.extend(
                detail_field_lines("URL", download, detail_w, "link", download)
            )
            detail_lines.append(("", "normal", None))
            detail_lines.append(("Description:", "normal", None))
            detail_lines.extend(
                (line, "muted", None)
                for line in textwrap.wrap(
                    desc or "No description.",
                    width=max(1, detail_w),
                    break_long_words=True,
                    break_on_hyphens=False,
                )
            )
            detail_lines.append(("", "normal", None))
            detail_lines.append(("Usage:", "normal", None))
            if usage:
                for example in usage:
                    detail_lines.extend(
                        (line, "accent", None)
                        for line in textwrap.wrap(
                            example,
                            width=max(1, detail_w),
                            break_long_words=True,
                            break_on_hyphens=False,
                        )
                    )
            else:
                detail_lines.append(("No usage examples.", "muted", None))

            max_detail_offset = max(0, len(detail_lines) - detail_h)
            detail_offset = min(detail_offset, max_detail_offset)
            for row, (line, style, link) in enumerate(
                detail_lines[detail_offset : detail_offset + detail_h]
            ):
                rendered = clip_text(line, detail_w)
                if link:
                    label = "URL: " if rendered.startswith("URL: ") else ""
                    link_text = rendered[len(label) :]
                    safe_addstr(
                        stdscr,
                        detail_y + row,
                        detail_x,
                        label,
                        colors["normal"],
                    )
                    safe_addstr(
                        stdscr,
                        detail_y + row,
                        detail_x + len(label),
                        link_text,
                        colors[style],
                    )
                    visible_links.append(
                        (
                            detail_y + row,
                            detail_x + len(label),
                            link_text,
                            link,
                        )
                    )
                else:
                    safe_addstr(
                        stdscr,
                        detail_y + row,
                        detail_x,
                        rendered,
                        colors[style],
                    )

        status = (
            f"{selected + 1}/{len(current_scripts)}"
            if current_scripts
            else f"0/{len(scripts)}"
        )
        if compact and focused_pane == "details":
            help_text = "Tab scripts   ↑/↓ scroll   PgUp/PgDn page   q quit"
        elif compact:
            help_text = "↑/↓ move   Tab details   / search   Enter download   q quit"
        elif focused_pane == "details":
            help_text = "←/Tab scripts   ↑/↓ scroll details   PgUp/PgDn page   q quit"
        else:
            help_text = "↑/↓ move   →/Tab details   / search   : command   Enter download   q quit"

        # Input mode gives printable keys to the search or command prompt;
        # otherwise the same keys drive list and detail-pane navigation.
        if input_mode:
            marker = "/" if input_mode == "search" else ":"
            help_text = f"{marker}{input_text}"
        elif message:
            help_text = message
        safe_addstr(stdscr, footer_y, 1, clip_text(help_text, max(1, width - len(status) - 3)), colors["muted"])
        safe_addstr(stdscr, footer_y, max(0, width - len(status) - 1), status, colors["accent"])

        try:
            curses.curs_set(1 if input_mode else 0)
        except curses.error:
            pass
        if input_mode:
            cursor_x = min(width - len(status) - 2, 2 + len(input_text))
            try:
                stdscr.move(footer_y, max(1, cursor_x))
            except curses.error:
                pass
        stdscr.refresh()
        for link_y, link_x, link_text, link_url in visible_links:
            terminal_hyperlink(link_y, link_x, link_text, link_url)
        key = stdscr.getch()

        if input_mode:
            if key == 27:
                input_mode = None
                input_text = ""
                message = ""
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                input_text = input_text[:-1]
                if input_mode == "search":
                    query = input_text
                    selected = offset = 0
            elif key in (10, 13, curses.KEY_ENTER):
                if input_mode == "search":
                    query = input_text
                    message = f"{len(search_scripts(scripts, query))} match(es)"
                    input_mode = None
                    input_text = ""
                else:
                    try:
                        action, arguments = parse_tui_command(input_text)
                        if action == "help":
                            message = "Commands: download | run [args] | help | quit"
                        elif action == "quit":
                            return None
                        elif current_scripts:
                            return action, sid, arguments
                        else:
                            message = "No script selected"
                    except ValueError as exc:
                        message = str(exc)
                    input_mode = None
                    input_text = ""
            elif 32 <= key <= 126:
                input_text += chr(key)
                if input_mode == "search":
                    query = input_text
                    selected = offset = 0
            continue

        if key in (ord("q"), ord("Q")):
            return None
        if key == 9:
            focused_pane = "details" if focused_pane == "scripts" else "scripts"
            detail_offset = 0
            continue
        if key == curses.KEY_LEFT:
            focused_pane = "scripts"
            continue
        if key == curses.KEY_RIGHT and detail_mode:
            focused_pane = "details"
            continue
        if key == ord("J") and show_details:
            detail_offset = min(max_detail_offset, detail_offset + 1)
            continue
        if key == ord("K") and show_details:
            detail_offset = max(0, detail_offset - 1)
            continue
        if key == ord("/"):
            input_mode = "search"
            input_text = query
            message = ""
            continue
        if key == ord(":"):
            input_mode = "command"
            input_text = ""
            message = ""
            continue
        if key == curses.KEY_UP and focused_pane == "details":
            detail_offset = max(0, detail_offset - 1)
        elif key == curses.KEY_DOWN and focused_pane == "details":
            detail_offset = min(max_detail_offset, detail_offset + 1)
        elif key == curses.KEY_PPAGE and focused_pane == "details":
            detail_offset = max(0, detail_offset - max(1, detail_h))
        elif key == curses.KEY_NPAGE and focused_pane == "details":
            detail_offset = min(
                max_detail_offset, detail_offset + max(1, detail_h)
            )
        elif key == curses.KEY_HOME and focused_pane == "details":
            detail_offset = 0
        elif key == curses.KEY_END and focused_pane == "details":
            detail_offset = max_detail_offset
        elif key in (curses.KEY_UP, ord("k")):
            if selected > 0:
                selected -= 1
        elif key in (curses.KEY_DOWN, ord("j")):
            if selected < len(current_scripts) - 1:
                selected += 1
        elif key == curses.KEY_PPAGE:
            selected = max(0, selected - max(1, list_h))
        elif key == curses.KEY_NPAGE:
            if current_scripts:
                selected = min(
                    len(current_scripts) - 1, selected + max(1, list_h)
                )
        elif key == curses.KEY_HOME:
            selected = 0
        elif key == curses.KEY_END:
            selected = max(0, len(current_scripts) - 1)
        elif key in (10, 13, curses.KEY_ENTER):
            if current_scripts:
                return "download", sid, []

def wrap_text(text: str, width: int) -> list[str]:
    """Wrap whitespace-delimited text to a fixed width.

    Args:
        text: Text to wrap.
        width: Maximum line width.

    Returns:
        Wrapped lines. Empty input or widths of one character or less produce
        a list containing one empty string.
    """
    if width <= 1:
        return [""]
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]

    for word in words[1:]:
        if len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(clip_text(current, width))
            current = word

    lines.append(clip_text(current, width))
    return lines

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse toolbox command-line arguments.

    Args:
        argv: Arguments excluding the program name. ``None`` uses
            ``sys.argv[1:]``.

    Returns:
        Parsed command-line values.

    Raises:
        SystemExit: If arguments are invalid or an immediate argparse action,
            such as ``--help`` or ``--version``, is requested.
    """
    parser = argparse.ArgumentParser(
        prog="toolbox",
        description="Select and securely download a script from the toolbox manifest."
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--completion-script-ids",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "script_names",
        nargs="*",
        metavar="SCRIPT",
        help="script ID, name, or filename; provide multiple values to download a batch",
    )
    parser.add_argument(
        "-m",
        "--manifest",
        default=DEFAULT_URL,
        help=f"manifest URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path.cwd(),
        help="directory where the selected script will be saved (default: current directory)",
    )
    return parser.parse_args(argv)

def main(argv: list[str] | None = None) -> int:
    """Run the toolbox command-line application.

    Args:
        argv: Arguments excluding the program name. ``None`` uses
            ``sys.argv[1:]``.

    Returns:
        Zero on success, 130 after a keyboard interrupt, the selected script's
        nonzero status when execution fails, or one for other failures and
        user cancellation.
    """
    args = parse_args(argv)

    try:
        manifest = fetch_manifest(args.manifest)
        scripts = get_scripts(manifest)

        if args.completion_script_ids:
            for script in scripts:
                console.print(script["id"], markup=False, highlight=False)
            return 0

        if args.script_names:
            selected_scripts = [find_script(scripts, name) for name in args.script_names]
        else:
            selection = curses.wrapper(tui_select, scripts, args.manifest)
            if selection is None:
                print_toolbox_art(
                    "Toolbox closed — no scripts were downloaded.",
                    ANSI_YELLOW,
                    sys.stderr,
                )
                return 1
            action, selected_id, run_arguments = selection
            selected_scripts = [find_script(scripts, selected_id)]

        for selected_script in selected_scripts:
            if not args.script_names and action == "run":
                returncode = run_streamed_script(selected_script, run_arguments)
                if returncode:
                    return returncode
                continue

            destination = download_script(selected_script, args.output_dir)
            print_download_receipt(selected_script, destination)

        print_toolbox_art()
        return 0

    except KeyboardInterrupt:
        error_console.print("\nCancelled.", style="yellow")
        return 130
    except Exception as exc:
        error_console.print(Text.assemble(("Error:", "bold red"), f" {exc}"))
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
