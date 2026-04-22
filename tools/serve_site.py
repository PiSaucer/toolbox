#!/usr/bin/env python3
"""Serve the generated site locally and reload browsers when source files change."""

import argparse
import http.server
import json
import posixpath
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "toolbox.json"
SITE_DIR = ROOT / "site"
BUILD_SCRIPT = ROOT / "tools" / "build_site.py"
WATCH_DIRS = (ROOT / "templates", ROOT / "metadata", ROOT / "scripts")
WATCH_FILES = (CONFIG_PATH, ROOT / "schema" / "script.schema.json", BUILD_SCRIPT)

@dataclass
class DevState:
    version: int = 0
    last_error: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)

    def mark_success(self) -> None:
        with self.lock:
            self.version += 1
            self.last_error = ""

    def mark_error(self, message: str) -> None:
        with self.lock:
            self.last_error = message

    def payload(self) -> dict[str, object]:
        with self.lock:
            return {"version": self.version, "error": self.last_error}

def load_base_path() -> str:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    parsed = urlparse(config["base_url"])
    return parsed.path.rstrip("/") or ""

def build_site() -> None:
    subprocess.run([sys.executable, str(BUILD_SCRIPT)], cwd=ROOT, check=True)

def iter_watch_files() -> Iterable[Path]:
    for watch_dir in WATCH_DIRS:
        if watch_dir.is_dir():
            for path in watch_dir.rglob("*"):
                if path.is_file():
                    yield path
    for path in WATCH_FILES:
        if path.is_file():
            yield path

def snapshot() -> dict[str, tuple[int, int]]:
    files: dict[str, tuple[int, int]] = {}
    for path in iter_watch_files():
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        files[str(path.relative_to(ROOT))] = (stat.st_mtime_ns, stat.st_size)
    return files

def watch_and_rebuild(state: DevState, stop_event: threading.Event, interval: float) -> None:
    previous = snapshot()
    while not stop_event.wait(interval):
        current = snapshot()
        if current == previous:
            continue
        previous = current
        try:
            build_site()
        except subprocess.CalledProcessError as exc:
            message = f"build failed with exit code {exc.returncode}"
            state.mark_error(message)
            print(message, file=sys.stderr)
            continue
        state.mark_success()
        print(f"Rebuilt site. Live reload version: {state.payload()['version']}")

def strip_base_path(path: str, base_path: str) -> str:
    parsed_path = unquote(urlparse(path).path)
    if base_path and parsed_path == base_path:
        return "/"
    if base_path and parsed_path.startswith(f"{base_path}/"):
        return parsed_path[len(base_path):]
    return parsed_path

def safe_site_path(path: str, base_path: str) -> Path:
    local_path = strip_base_path(path, base_path)
    normalized = posixpath.normpath(local_path)
    if normalized in ("", "."):
        normalized = "/"
    relative = normalized.lstrip("/")
    if relative == "":
        target = SITE_DIR
    else:
        target = SITE_DIR / Path(relative)
    try:
        target.resolve().relative_to(SITE_DIR.resolve())
    except ValueError:
        return SITE_DIR / "__not_found__"
    if target.is_dir():
        target = target / "index.html"
    return target

def live_reload_script(base_path: str, interval_ms: int) -> str:
    endpoint = f"{base_path}/__toolbox_live_reload" if base_path else "/__toolbox_live_reload"
    return f"""<script>
(() => {{
  const endpoint = {json.dumps(endpoint)};
  let version = null;
  async function checkForChanges() {{
    try {{
      const response = await fetch(endpoint, {{ cache: 'no-store' }});
      if (!response.ok) return;
      const data = await response.json();
      if (data.error) {{
        console.warn(`[toolbox] ${{data.error}}`);
        return;
      }}
      if (version === null) {{
        version = data.version;
        return;
      }}
      if (data.version !== version) window.location.reload();
    }} catch (error) {{
      console.warn('[toolbox] live reload unavailable', error);
    }}
  }}
  checkForChanges();
  setInterval(checkForChanges, {interval_ms});
}})();
</script>"""

def inject_live_reload(html: str, snippet: str) -> str:
    marker = "</body>"
    if marker in html:
        return html.replace(marker, f"{snippet}\n</body>", 1)
    return f"{html}\n{snippet}\n"

def make_handler(base_path: str, state: DevState, interval_ms: int) -> type[http.server.SimpleHTTPRequestHandler]:
    class SiteHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(SITE_DIR), **kwargs)

        def redirect_to_base_path(self) -> bool:
            if self.path not in ("", "/") or not base_path:
                return False
            self.send_response(302)
            self.send_header("Location", f"{base_path}/")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return True

        def serve_live_reload_status(self, head_only: bool = False) -> bool:
            if strip_base_path(self.path, base_path) != "/__toolbox_live_reload":
                return False
            body = json.dumps(state.payload()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if not head_only:
                self.wfile.write(body)
            return True

        def serve_html_with_live_reload(self, head_only: bool = False) -> bool:
            target = safe_site_path(self.path, base_path)
            if target.suffix.lower() != ".html" or not target.is_file():
                return False
            html = target.read_text(encoding="utf-8")
            body = inject_live_reload(html, live_reload_script(base_path, interval_ms)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if not head_only:
                self.wfile.write(body)
            return True

        def do_GET(self) -> None:
            if self.redirect_to_base_path():
                return
            if self.serve_live_reload_status():
                return
            if self.serve_html_with_live_reload():
                return
            super().do_GET()

        def do_HEAD(self) -> None:
            if self.redirect_to_base_path():
                return
            if self.serve_live_reload_status(head_only=True):
                return
            if self.serve_html_with_live_reload(head_only=True):
                return
            super().do_HEAD()

        def translate_path(self, path: str) -> str:
            return str(safe_site_path(path, base_path))

    return SiteHandler

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="host to bind; default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="port to bind; default: 8000")
    parser.add_argument("--no-build", action="store_true", help="serve the current site/ folder without rebuilding first")
    parser.add_argument("--no-watch", action="store_true", help="disable source file watching and browser reload")
    parser.add_argument("--poll-interval", type=float, default=0.5, help="file watch interval in seconds; default: 0.5")
    parser.add_argument("--reload-interval", type=int, default=500, help="browser reload polling interval in milliseconds; default: 500")
    args = parser.parse_args()

    if not args.no_build:
        build_site()
    if not SITE_DIR.is_dir():
        print(f"error: missing generated site directory: {SITE_DIR}", file=sys.stderr)
        return 1

    state = DevState(version=1)
    stop_event = threading.Event()
    watcher: threading.Thread | None = None
    if not args.no_watch:
        watcher = threading.Thread(
            target=watch_and_rebuild,
            args=(state, stop_event, args.poll_interval),
            daemon=True,
        )
        watcher.start()

    base_path = load_base_path()
    handler = make_handler(base_path, state, args.reload_interval)
    server = http.server.ThreadingHTTPServer((args.host, args.port), handler)
    url_path = f"{base_path}/" if base_path else "/"
    print(f"Serving {SITE_DIR} at http://{args.host}:{args.port}{url_path}")
    if args.no_watch:
        print("Watching disabled.")
    else:
        watched = ", ".join(str(path.relative_to(ROOT)) for path in (*WATCH_DIRS, *WATCH_FILES))
        print(f"Watching: {watched}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        stop_event.set()
        server.server_close()
        if watcher is not None:
            watcher.join(timeout=2)
    return 0


if __name__ == "__main__":
    main()
