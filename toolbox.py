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
import platform
import re
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import urllib.request
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, unquote, urlparse

from rich.console import Console
from rich.text import Text

__version__ = "1.0.6"
DEFAULT_URL = "https://pisaucer.github.io/toolbox/manifest.json"
LATEST_RELEASE_URL = "https://api.github.com/repos/PiSaucer/toolbox/releases/latest"
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
TOOLFILE_NAME = "Toolfile"
LOCKFILE_NAME = "Toolfile.lock"
DEPENDENCY_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?P<constraints>(?:(?:==|!=|>=|<=|>|<)[^,\s#]+)(?:,(?:(?:==|!=|>=|<=|>|<)[^,\s#]+)*)?)?$"
)
TOOLBOX_ART = [
    " _              _ _               ",
    "| |_ ___   ___ | | |__   _____  __",
    "| __/ _ \\ / _ \\| | '_ \\ / _ \\ \\/ /",
    "| || (_) | (_) | | |_) | (_) >  < ",
    " \\__\\___/ \\___/|_|_.__/ \\___/_/\\_\\",
]
console = Console(highlight=False)
error_console = Console(stderr=True, highlight=False)

def installation_source(module_path: Optional[Path] = None) -> str:
    """Describe how the running copy of toolbox was installed.

    The project is also distributed as a single Python file, so package
    metadata is not always available.  Use the locations chosen by each
    supported installer and fall back to a standalone download.

    Args:
        module_path: Path to inspect. ``None`` uses the running module's path.

    Returns:
        A short description of the detected installation source.
    """
    path = (module_path or Path(__file__)).expanduser().resolve()
    normalized = path.as_posix().lower()

    if "/cellar/toolbox/" in normalized or "/homebrew/cellar/toolbox/" in normalized:
        return "Homebrew"
    if "/pipx/venvs/" in normalized:
        return "pipx (PyPI)"
    if "/uv/tools/" in normalized or "/uv/tool/" in normalized:
        return "uv tool (PyPI)"
    if "/site-packages/" in normalized or "/dist-packages/" in normalized:
        return "pip (PyPI)"

    home = Path.home().expanduser().resolve()
    if path == home / "Library" / "Application Support" / "toolbox" / "toolbox.py":
        return "Toolbox Desktop"
    if path == home / ".local" / "bin" / "toolbox":
        return "install.sh download"
    if normalized.endswith("/programs/toolbox/toolbox.py"):
        return "install.ps1 download"
    if any((parent / ".git").is_dir() for parent in path.parents):
        return "source checkout"
    return "standalone download"

def version_text(
    program: str = "toolbox",
    module_path: Optional[Path] = None,
) -> str:
    """Build version output with installation source and location.

    Args:
        program: Command name displayed before the version number.
        module_path: Installed module path. ``None`` uses the running module's
            path.

    Returns:
        Version text containing the install source and resolved location.
    """
    path = (module_path or Path(__file__)).expanduser().resolve()
    source = installation_source(path)
    return (
        f"{program} {__version__}\n"
        f"python: {platform.python_version()}\n"
        f"source: {source}\n"
        f"location: {path}"
    )

def version_tuple(version: str) -> tuple[int, int, int]:
    """Convert a stable semantic version (optionally prefixed with ``v``)."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version.strip())
    if match is None:
        raise ValueError(f"invalid version: {version}")
    return tuple(int(part) for part in match.groups())

def fetch_latest_version() -> str:
    """Return the version from the latest GitHub release."""
    request = urllib.request.Request(
        LATEST_RELEASE_URL,
        headers={
            "User-Agent": f"toolbox-tui/{__version__}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(f"failed to check for updates: HTTP {status}")
        release = json.loads(response.read().decode("utf-8"))
    tag = release.get("tag_name") if isinstance(release, dict) else None
    if not isinstance(tag, str):
        raise RuntimeError("latest release is missing a version tag")
    version_tuple(tag)
    return tag.removeprefix("v")

def upgrade_command(source: str) -> str:
    """Return the appropriate upgrade command for an installation source."""
    if source == "Homebrew":
        return "brew update && brew upgrade PiSaucer/tap/toolbox"
    if source == "pipx (PyPI)":
        return "pipx upgrade pisaucer-toolbox"
    if source == "uv tool (PyPI)":
        return "uv tool upgrade pisaucer-toolbox"
    if source == "pip (PyPI)":
        return "python -m pip install --upgrade pisaucer-toolbox"
    if source == "install.sh download":
        return "curl -fsSL https://pisaucer.github.io/toolbox/install.sh | sh"
    if source == "install.ps1 download":
        return "irm https://pisaucer.github.io/toolbox/install.ps1 | iex"
    if source == "source checkout":
        return "git pull"
    if source == "Toolbox Desktop":
        return "Update Toolbox Desktop to update its bundled toolbox CLI"
    if source == "standalone download":
        return (
            "curl -fL https://pisaucer.github.io/toolbox/toolbox.py "
            "-o toolbox.py"
        )
    return "https://github.com/PiSaucer/toolbox/releases/latest"

def version_text_with_update(
    program: str = "toolbox",
    module_path: Optional[Path] = None,
) -> str:
    """Build version output and, when available, include an update notice."""
    text = version_text(program, module_path)
    try:
        latest = fetch_latest_version()
        if version_tuple(latest) > version_tuple(__version__):
            source = installation_source(module_path)
            text += (
                f"\n\nUpdate available: {__version__} -> {latest}\n"
                f"Upgrade: {upgrade_command(source)}"
            )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        # Version reporting should continue to work when GitHub is unavailable.
        pass
    return text

class VersionAction(argparse.Action):
    """Print version information, checking for an update only on demand."""

    def __init__(self, option_strings: list[str], dest: str, **kwargs: Any) -> None:
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: Optional[str] = None,
    ) -> None:
        parser.exit(message=version_text_with_update(parser.prog) + "\n")

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
    temporary_path: Optional[Path] = None

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
    message: Optional[str] = None,
    message_style: str = "bold cyan",
    stream: Any = None,
) -> None:
    """Print the toolbox banner and an optional message.

    Args:
        message: Text to print below the banner, if any.
        message_style: Rich style to use for the optional message.
        stream: Destination stream. Defaults to ``sys.stdout``.
    """
    output = sys.stdout if stream is None else stream
    rich_console = Console(file=output, highlight=False)
    for line in TOOLBOX_ART:
        rich_console.print(line, style="bold blue")
    if message:
        rich_console.print(message, style=message_style)

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
    link: Optional[str] = None,
) -> list[tuple[str, str, Optional[str]]]:
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
) -> Optional[tuple[str, str, list[str]]]:
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
    input_mode: Optional[str] = None
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
            detail_lines: list[tuple[str, str, Optional[str]]] = []
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

def semantic_version(value: str) -> tuple[int, ...]:
    """Parse a simple stable semantic version for dependency comparisons.

    Args:
        value: A version with one to three numeric components.

    Returns:
        Three numeric components suitable for tuple comparison.

    Raises:
        ValueError: If ``value`` is not a supported stable semantic version.
    """
    match = re.fullmatch(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", value.strip())
    if match is None:
        raise ValueError(f"invalid semantic version: {value}")
    return tuple(int(part or 0) for part in match.groups())

def version_satisfies(version: str, constraints: str) -> bool:
    """Return whether a version satisfies comma-separated Toolfile bounds.

    Args:
        version: Version to evaluate.
        constraints: Empty or comma-separated no-space version constraints.

    Returns:
        ``True`` when every supplied constraint is satisfied.

    Raises:
        ValueError: If a version in a syntactically valid constraint is not
            semantic-version compatible.
    """
    candidate = semantic_version(version)
    if not constraints:
        return True
    for constraint in constraints.split(","):
        match = re.fullmatch(r"(==|!=|>=|<=|>|<)([^,\s]+)", constraint)
        if match is None:
            return False
        operator, required_text = match.groups()
        required = semantic_version(required_text)
        if not {
            "==": candidate == required, "!=": candidate != required,
            ">=": candidate >= required, "<=": candidate <= required,
            ">": candidate > required, "<": candidate < required,
        }[operator]:
            return False
    return True

def parse_toolfile(path: Path) -> list[dict[str, Any]]:
    """Parse a Toolfile, retaining source locations for useful diagnostics.

    Args:
        path: Toolfile to read.

    Returns:
        Normalized dependency records in source order.

    Raises:
        RuntimeError: If the file cannot be read, has invalid syntax, or
            declares the same dependency more than once.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(f"could not read {path}: {exc}") from exc
    dependencies: list[dict[str, Any]] = []
    seen: set[str] = set()
    for number, raw in enumerate(lines, 1):
        declaration = raw.split("#", 1)[0].strip()
        if not declaration:
            continue
        match = DEPENDENCY_PATTERN.fullmatch(declaration)
        if match is None:
            raise RuntimeError(
                f"{path}:{number}: Invalid dependency specification:\n{raw}\n"
                "Dependency declarations cannot contain spaces and must use "
                "a supported version operator."
            )
        name = match.group("name")
        key = name.casefold()
        if key in seen:
            raise RuntimeError(f"{path}:{number}: duplicate dependency: {name}")
        seen.add(key)
        dependencies.append({"name": name, "constraints": match.group("constraints") or "", "line": number})
    return dependencies

def toolfile_fingerprint(dependencies: list[dict[str, Any]]) -> str:
    """Create a comment- and whitespace-independent Toolfile fingerprint.

    Args:
        dependencies: Parsed Toolfile dependency records.

    Returns:
        SHA-256 digest of normalized declarations in stable order.
    """
    normalized = "\n".join(
        f"{item['name'].casefold()}{item['constraints']}"
        for item in sorted(dependencies, key=lambda item: item["name"].casefold())
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def canonical_dependency(script: dict[str, Any]) -> str:
    """Return the manifest spelling suitable for a no-space declaration.

    Args:
        script: Manifest script entry.

    Returns:
        A canonical script name or ID compatible with Toolfile syntax.

    Raises:
        RuntimeError: If the manifest entry has no usable script ID.
    """
    name = script.get("name")
    if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name.strip()):
        return name.strip()
    value = script.get("id")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("selected script is missing a canonical id")
    return value.strip()

def read_lockfile(path: Path) -> dict[str, Any]:
    """Read and validate Toolbox's deterministic JSON lock file.

    Args:
        path: Lock file to read.

    Returns:
        Validated lock-file object.

    Raises:
        RuntimeError: If the file is malformed or uses an unsupported format.
    """
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"malformed lock file {path}: {exc}") from exc
    if not isinstance(lock, dict) or lock.get("lock_version") != 1:
        raise RuntimeError(f"unsupported lock-file version in {path}")
    if not isinstance(lock.get("scripts"), list) or not isinstance(lock.get("toolfile_hash"), str):
        raise RuntimeError(f"malformed lock file {path}")
    return lock

def write_lockfile(path: Path, lock: dict[str, Any]) -> None:
    """Write lock data with stable ordering and no generated timestamps.

    Args:
        path: Destination ``Toolfile.lock`` path.
        lock: Lock-file object to serialize.
    """
    lock["scripts"] = sorted(lock.get("scripts", []), key=lambda item: item["name"].casefold())
    lock["system_tools"] = sorted(lock.get("system_tools", []), key=lambda item: item["name"].casefold())
    path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def script_commit(script: dict[str, Any]) -> str:
    """Obtain the immutable source commit advertised by a manifest entry.

    Current manifests can include ``commit`` directly.  A raw GitHub URL with
    a 40-character revision is also immutable.  Older manifests do not carry
    enough provenance to lock safely, so fail rather than recording HEAD.

    Args:
        script: Manifest entry with source metadata.

    Returns:
        Lowercase Git commit hash for the exact script artifact.

    Raises:
        RuntimeError: If immutable commit provenance is unavailable.
    """
    commit = script.get("commit") or script.get("git_commit")
    if isinstance(commit, str) and re.fullmatch(r"[0-9a-fA-F]{7,64}", commit.strip()):
        return commit.strip().lower()
    url = script.get("download_url")
    if isinstance(url, str):
        match = re.match(r"https://raw\.githubusercontent\.com/[^/]+/[^/]+/([0-9a-fA-F]{40})/", url)
        if match:
            return match.group(1).lower()
        github = re.match(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.*)", url)
        if github:
            owner, repository, revision, path = github.groups()
            api_url = (f"https://api.github.com/repos/{owner}/{repository}/commits?"
                       f"path={quote(path)}&sha={quote(revision)}&per_page=1")
            request = urllib.request.Request(api_url, headers={"User-Agent": f"toolbox-tui/{__version__}", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(request, timeout=10) as response:
                commits = json.loads(response.read().decode("utf-8"))
            if isinstance(commits, list) and commits and isinstance(commits[0], dict):
                sha = commits[0].get("sha")
                if isinstance(sha, str) and re.fullmatch(r"[0-9a-fA-F]{40}", sha):
                    return sha.lower()
    raise RuntimeError("selected script is missing an immutable Git commit hash")

def system_tool_records(scripts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect script-declared host commands and return reproducibility records.

    Args:
        scripts: Resolved manifest entries whose ``requirements`` are commands.

    Returns:
        Stable system-tool records including path, detected version, and users.

    Raises:
        RuntimeError: If a required host command cannot be found.
    """
    required_by: dict[str, list[str]] = {}
    for script in scripts:
        requirements = script.get("requirements", [])
        if not isinstance(requirements, list):
            continue
        for requirement in requirements:
            if isinstance(requirement, str) and requirement.strip():
                required_by.setdefault(requirement.strip(), []).append(canonical_dependency(script))
    records: list[dict[str, Any]] = []
    for name in sorted(required_by, key=str.casefold):
        executable = shutil.which(name)
        if executable is None:
            joined = ", ".join(sorted(required_by[name], key=str.casefold))
            raise RuntimeError(f"Missing required system tool: {name}\nRequired by: {joined}")
        version = "unknown"
        try:
            output = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=3, check=False)
            match = re.search(r"\d+(?:\.\d+){1,3}", output.stdout + output.stderr)
            if match:
                version = match.group(0)
        except (OSError, subprocess.SubprocessError):
            pass
        records.append({"name": name, "path": executable, "version": version,
                        "required_by": sorted(required_by[name], key=str.casefold)})
    return records

def locked_entry_is_compatible(entry: dict[str, Any], dependency: dict[str, Any]) -> bool:
    """Return whether one lock entry can reproduce a dependency declaration.

    Args:
        entry: Candidate record from ``Toolfile.lock``.
        dependency: Parsed, canonicalized Toolfile dependency record.

    Returns:
        ``True`` when name, version constraint, hash, commit, and URL are valid.
    """
    return (entry.get("name", "").casefold() == dependency["name"].casefold()
            and isinstance(entry.get("version"), str)
            and version_satisfies(entry["version"], dependency["constraints"])
            and isinstance(entry.get("sha256"), str) and isinstance(entry.get("commit"), str)
            and isinstance(entry.get("url"), str))

def install_project_dependencies(toolfile: Path, manifest: dict[str, Any], output_dir: Path,
                                 refresh: bool = False, only: Optional[str] = None) -> int:
    """Resolve/install a Toolfile and regenerate its exact lock when needed.

    Args:
        toolfile: Project dependency specification to install.
        manifest: Fetched Toolbox manifest.
        output_dir: Directory receiving verified script files.
        refresh: Replace a locked artifact only when a newer allowed manifest
            version is available.
        only: Optional canonical dependency to refresh; all others stay locked.

    Returns:
        Number of Toolfile dependencies installed.

    Raises:
        RuntimeError: If resolution, provenance, download verification, or host
            system-tool validation cannot be completed safely.
    """
    dependencies = parse_toolfile(toolfile)
    scripts = get_scripts(manifest)
    lock_path = toolfile.with_name(LOCKFILE_NAME)
    fingerprint = toolfile_fingerprint(dependencies)
    existing = read_lockfile(lock_path) if lock_path.exists() else None
    compatible_lock = existing if existing and existing.get("toolfile_hash") == fingerprint else None
    resolved_entries: list[dict[str, Any]] = []
    resolved_scripts: list[dict[str, Any]] = []
    for dependency in dependencies:
        script = find_script(scripts, dependency["name"])
        canonical = canonical_dependency(script)
        dependency = {**dependency, "name": canonical}
        locked = next((item for item in (compatible_lock or {}).get("scripts", [])
                       if isinstance(item, dict) and locked_entry_is_compatible(item, dependency)), None)
        use_locked = bool(locked)
        refresh_this = refresh and (only is None or canonical.casefold() == only.casefold())
        if refresh_this and locked:
            available_version = script.get("version")
            if (isinstance(available_version, str)
                    and version_satisfies(available_version, dependency["constraints"])
                    and semantic_version(available_version) > semantic_version(locked["version"])):
                use_locked = False
        elif refresh_this:
            use_locked = False
        if use_locked:
            entry = locked
            artifact = {"download_url": entry["url"], "sha256": entry["sha256"]}
            download_script(artifact, output_dir)
        else:
            version = script.get("version")
            if not isinstance(version, str) or not version_satisfies(version, dependency["constraints"]):
                raise RuntimeError(f"no available version of {canonical} satisfies {dependency['constraints'] or 'the requested constraint'}")
            url, sha256, _ = script_download_details(script)
            entry = {"name": canonical, "id": script.get("id"), "version": version,
                     "commit": script_commit(script), "sha256": sha256, "url": url}
            download_script(script, output_dir)
        resolved_entries.append(entry)
        resolved_scripts.append(script)
    records = system_tool_records(resolved_scripts)
    if compatible_lock:
        previous_tools = {
            item.get("name"): item for item in compatible_lock.get("system_tools", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        for record in records:
            previous = previous_tools.get(record["name"])
            if (previous and previous.get("version") not in {None, "unknown"}
                    and record["version"] not in {"unknown", previous.get("version")}):
                console.print(
                    f"System dependency changed: {record['name']}: locked "
                    f"{previous['version']}, installed {record['version']}", style="yellow"
                )
    write_lockfile(lock_path, {"lock_version": 1, "toolfile_hash": fingerprint,
                               "scripts": resolved_entries, "system_tools": records})
    return len(resolved_entries)

def modify_toolfile(toolfile: Path, declaration: str, scripts: list[dict[str, Any]], remove: bool = False) -> None:
    """Add, update, or remove one declaration while preserving unrelated lines.

    Args:
        toolfile: Toolfile to create or update.
        declaration: User-supplied no-space dependency declaration.
        scripts: Available manifest entries used for canonicalization.
        remove: Remove the declaration instead of adding or updating it.

    Raises:
        RuntimeError: If the declaration is invalid, unknown, unversioned, or
            cannot be removed because it is absent.
    """
    match = DEPENDENCY_PATTERN.fullmatch(declaration)
    if match is None:
        raise RuntimeError(f"Invalid dependency specification: {declaration}")
    script = find_script(scripts, match.group("name"))
    canonical = canonical_dependency(script)
    constraints = match.group("constraints")
    if not constraints and not remove:
        version = script.get("version")
        if not isinstance(version, str):
            raise RuntimeError(f"selected script is missing a version: {canonical}")
        # A bare add should not silently permit versions older than the one the
        # user selected from today's manifest.
        constraints = f">={version}"
    replacement = canonical + (constraints or "")
    lines = toolfile.read_text(encoding="utf-8").splitlines() if toolfile.exists() else []
    changed = False
    retained: list[str] = []
    for raw in lines:
        body, marker, comment = raw.partition("#")
        old = body.strip()
        old_match = DEPENDENCY_PATTERN.fullmatch(old)
        if old_match and old_match.group("name").casefold() == canonical.casefold():
            if not changed and not remove:
                indent = body[:len(body) - len(body.lstrip())]
                retained.append(indent + replacement + ((" #" + comment) if marker else ""))
            changed = True
            continue
        retained.append(raw)
    if not remove and not changed:
        if retained and retained[-1].strip():
            retained.append("")
        retained.append(replacement)
    if remove and not changed:
        raise RuntimeError(f"dependency not found in {toolfile}: {canonical}")
    toolfile.write_text("\n".join(retained) + ("\n" if retained else ""), encoding="utf-8")

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
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
        description="Select and securely download a script from the toolbox manifest.",
        epilog=("Toolfile: toolbox install [SCRIPT] [--file Toolfile], "
                "toolbox add SCRIPT[CONSTRAINT], toolbox remove SCRIPT, "
                "toolbox update [SCRIPT]."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action=VersionAction,
        help="show installed version and check for updates",
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
    parser.add_argument(
        "--file",
        type=Path,
        help="Toolfile path for install (default: ./Toolfile)",
    )
    return parser.parse_args(argv)

def main(argv: Optional[list[str]] = None) -> int:
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

        command = args.script_names[0].casefold() if args.script_names else ""
        if command in {"install", "add", "remove", "update"}:
            command_args = args.script_names[1:]
            toolfile = (args.file or Path.cwd() / TOOLFILE_NAME).expanduser().resolve()
            installed_count: int
            if command == "install":
                if command_args:
                    if len(command_args) != 1:
                        raise RuntimeError("usage: toolbox install [SCRIPT[VERSION-CONSTRAINT]]")
                    # A named install is a convenient, backward-compatible
                    # alias for adding that script to the current project.
                    modify_toolfile(toolfile, command_args[0], scripts)
                    installed_count = install_project_dependencies(toolfile, manifest, args.output_dir)
                else:
                    if not toolfile.is_file():
                        raise RuntimeError(f"Toolfile not found: {toolfile}")
                    installed_count = install_project_dependencies(toolfile, manifest, args.output_dir)
            elif command == "add":
                if len(command_args) != 1:
                    raise RuntimeError("usage: toolbox add SCRIPT[VERSION-CONSTRAINT]")
                modify_toolfile(toolfile, command_args[0], scripts)
                installed_count = install_project_dependencies(toolfile, manifest, args.output_dir)
            elif command == "remove":
                if len(command_args) != 1:
                    raise RuntimeError("usage: toolbox remove SCRIPT")
                modify_toolfile(toolfile, command_args[0], scripts, remove=True)
                # A removed final dependency still gets a valid empty lock.
                installed_count = install_project_dependencies(toolfile, manifest, args.output_dir)
            else:
                if len(command_args) > 1:
                    raise RuntimeError("usage: toolbox update [SCRIPT]")
                if not toolfile.is_file():
                    raise RuntimeError(f"Toolfile not found: {toolfile}")
                target = command_args[0] if command_args else None
                if target is not None:
                    target = canonical_dependency(find_script(scripts, target))
                installed_count = install_project_dependencies(
                    toolfile, manifest, args.output_dir, refresh=True, only=target
                )
            print_toolbox_art(
                f"Installed {installed_count} Toolfile dependenc"
                f"{'y' if installed_count == 1 else 'ies'}.",
                "bold green",
            )
            return 0

        if args.script_names:
            selected_scripts = [find_script(scripts, name) for name in args.script_names]
        else:
            selection = curses.wrapper(tui_select, scripts, args.manifest)
            if selection is None:
                print_toolbox_art(
                    "Toolbox closed — no scripts were downloaded.",
                    "bold yellow",
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
