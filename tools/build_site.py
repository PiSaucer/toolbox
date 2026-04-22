#!/usr/bin/env python3
"""Validate script metadata and generate the GitHub Pages website."""

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
METADATA_DIR = ROOT / "metadata"
SITE_DIR = ROOT / "site"
TEMPLATE_DIR = ROOT / "templates"
CONFIG_PATH = ROOT / "toolbox.json"
SCHEMA_PATH = ROOT / "schema" / "script.schema.json"

@dataclass(frozen=True)
class MetadataSchema:
    required_fields: set[str]
    properties: dict[str, dict[str, Any]]

    @property
    def allowed_fields(self) -> set[str]:
        return set(self.properties)

def fail(message: str) -> None:
    raise ValueError(message)

def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        fail(f"{path}: file does not exist")
    except json.JSONDecodeError as exc:
        fail(f"{path}: invalid JSON: {exc}")
    if not isinstance(data, dict):
        fail(f"{path}: expected a JSON object")
    return data

def read_template(name: str) -> str:
    path = TEMPLATE_DIR / name
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        fail(f"missing template: {path}")

def render_template(name: str, values: dict[str, Any]) -> str:
    output = read_template(name)
    for key, value in values.items():
        output = output.replace("{{" + key + "}}", str(value))
    if "{{" in output or "}}" in output:
        fail(f"{TEMPLATE_DIR / name}: unresolved template placeholder")
    return output

def load_metadata_schema() -> MetadataSchema:
    schema = load_json(SCHEMA_PATH)
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    if not isinstance(required, list) or not all(isinstance(field, str) for field in required):
        fail(f"{SCHEMA_PATH}: required must be an array of strings")
    if not isinstance(properties, dict) or not properties:
        fail(f"{SCHEMA_PATH}: properties must be a non-empty object")
    for field, rules in properties.items():
        if not isinstance(field, str) or not isinstance(rules, dict):
            fail(f"{SCHEMA_PATH}: properties must map field names to rule objects")
    return MetadataSchema(required_fields=set(required), properties=properties)

def validate_string_field(path: Path, field: str, value: Any, rules: dict[str, Any]) -> None:
    if not isinstance(value, str):
        fail(f"{path}: {field} must be a string")
    min_length = rules.get("minLength")
    if isinstance(min_length, int) and len(value) < min_length:
        fail(f"{path}: {field} must be at least {min_length} character(s)")
    pattern = rules.get("pattern")
    if isinstance(pattern, str) and re.search(pattern, value) is None:
        fail(f"{path}: {field} must match pattern {pattern}")

def validate_array_field(path: Path, field: str, value: Any, rules: dict[str, Any]) -> None:
    if not isinstance(value, list):
        fail(f"{path}: {field} must be an array")
    min_items = rules.get("minItems", 1 if field in rules else None)
    if isinstance(min_items, int) and len(value) < min_items:
        fail(f"{path}: {field} must contain at least {min_items} item(s)")
    item_rules = rules.get("items", {})
    if not isinstance(item_rules, dict):
        item_rules = {}
    for entry in value:
        if item_rules.get("type") == "string":
            if not isinstance(entry, str):
                fail(f"{path}: {field} must contain only strings")
            min_length = item_rules.get("minLength")
            if isinstance(min_length, int) and len(entry) < min_length:
                fail(f"{path}: {field} must contain only strings with at least {min_length} character(s)")
    if rules.get("uniqueItems") is True and len(value) != len(set(value)):
        fail(f"{path}: {field} contains duplicate values")

def validate_metadata(path: Path, item: dict[str, Any], schema: MetadataSchema) -> None:
    extra = set(item) - schema.allowed_fields
    if extra:
        fail(f"{path}: unsupported fields: {', '.join(sorted(extra))}")

    missing = schema.required_fields - set(item)
    if missing:
        fail(f"{path}: missing required fields: {', '.join(sorted(missing))}")

    for field, value in item.items():
        rules = schema.properties[field]
        field_type = rules.get("type")
        if field_type == "string":
            validate_string_field(path, field, value, rules)
        elif field_type == "array":
            validate_array_field(path, field, value, rules)
        else:
            fail(f"{SCHEMA_PATH}: unsupported type for {field}: {field_type}")

    if not item["path"].startswith("scripts/"):
        fail(f"{path}: path must point inside scripts/")
    if Path(item["path"]).name != item["entry"]:
        fail(f"{path}: entry must match the filename in path")

def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    for field in ("site_title", "site_description", "base_url", "repository", "branch"):
        if not isinstance(config.get(field), str) or not config[field].strip():
            fail(f"{CONFIG_PATH}: {field} must be a non-empty string")

    parsed = urlparse(config["base_url"])
    base_path = parsed.path.rstrip("/") or ""
    repository = config["repository"].strip("/")
    return {
        **config,
        "base_url": config["base_url"].rstrip("/"),
        "base_path": base_path,
        "repository": repository,
        "repository_url": f"https://github.com/{repository}",
    }

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def load_scripts(config: dict[str, Any], schema: MetadataSchema) -> list[dict[str, Any]]:
    scripts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()

    for metadata_path in sorted(METADATA_DIR.glob("*.json")):
        item = load_json(metadata_path)
        validate_metadata(metadata_path, item, schema)

        if item["id"] in seen_ids:
            fail(f"{metadata_path}: duplicate id {item['id']}")
        if item["path"] in seen_paths:
            fail(f"{metadata_path}: duplicate script path {item['path']}")
        seen_ids.add(item["id"])
        seen_paths.add(item["path"])

        script_path = ROOT / item["path"]
        if not script_path.is_file():
            fail(f"{metadata_path}: script file does not exist: {item['path']}")

        enriched = dict(item)
        enriched["sha256"] = sha256_file(script_path)
        enriched["download_url"] = f"https://raw.githubusercontent.com/{config['repository']}/{config['branch']}/{item['path']}"
        enriched["source_url"] = f"{config['repository_url']}/blob/{config['branch']}/{item['path']}"
        enriched["page_url"] = f"{config['base_url']}/scripts/{item['id']}/"
        enriched["page_path"] = f"{config['base_path']}/scripts/{item['id']}/"
        enriched["metadata_path"] = str(metadata_path.relative_to(ROOT))
        enriched["script_content"] = script_path.read_text(encoding="utf-8")
        scripts.append(enriched)

    if not scripts:
        fail("metadata/: no script metadata files found")
    return scripts

def escaped(value: Any) -> str:
    return html.escape(str(value), quote=True)

def render_badges(values: list[str]) -> str:
    return "".join(render_template("components/badge.html", {"value": escaped(value)}).strip() for value in values)

def platform_icon_class(platform: str) -> str:
    key = platform.strip().lower()
    if key in {"macos", "mac", "osx", "darwin"}:
        return "bi-apple"
    if key in {"steam", "steamdeck", "proton", "deck"}:
        return "bi-steam"
    if key in {"ubuntu"}:
        return "bi-ubuntu"
    if key in {"linux", "debian", "fedora", "arch"}:
        return "bi-tux"
    if key in {"windows", "win", "win10", "win11", "microsoft"}:
        return "bi-microsoft"
    return "bi-hdd-stack"

def render_platform_badges(values: list[str]) -> str:
    return "".join(
        render_template(
            "components/platform-badge.html",
            {"value": escaped(value), "icon_class": escaped(platform_icon_class(value))},
        ).strip()
        for value in values
    )

def render_list_items(values: list[str]) -> str:
    return "".join(render_template("components/list-item.html", {"value": escaped(value)}).strip() for value in values)

def highlight_language(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in {".sh", ".bash", ".zsh"}:
        return "language-bash"
    if ext in {".ps1", ".psm1"}:
        return "language-powershell"
    if ext == ".py":
        return "language-python"
    if ext in {".js", ".mjs", ".cjs"}:
        return "language-javascript"
    return "language-plaintext"


def minimal_manifest(scripts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = [
        "id",
        "name",
        "version",
        "description",
        "requirements",
        "tags",
        "platforms",
        "category",
        "download_url",
        "source_url",
        "page_url",
        "sha256",
    ]
    return [{key: script[key] for key in keys if key in script} for script in scripts]


def render_layout(config: dict[str, Any], title: str, content: str, script_data: list[dict[str, Any]] | None = None) -> str:
    data = ""
    if script_data is not None:
        safe_json = html.escape(json.dumps(script_data, sort_keys=True), quote=False)
        data = render_template("components/script-data.html", {"json": safe_json}).strip()
    return render_template(
        "layout.html",
        {
            "title": escaped(title),
            "site_title": escaped(config["site_title"]),
            "site_description": escaped(config["site_description"]),
            "base_path": escaped(config["base_path"]),
            "repository_url": escaped(config["repository_url"]),
            "content": content,
            "script_data": data,
        },
    )


def render_index(config: dict[str, Any], scripts: list[dict[str, Any]]) -> str:
    cards = []
    for script in scripts:
        search_blob = " ".join([
            script["name"],
            script["id"],
            script["description"],
            script.get("category", ""),
            " ".join(script.get("tags", [])),
            " ".join(script.get("platforms", [])),
            " ".join(script.get("requirements", [])),
        ]).lower()
        category = script.get("category", "script")
        cards.append(render_template(
            "components/script-card.html",
            {
                "search_blob": escaped(search_blob),
                "tag_data": escaped(" ".join([*script.get("tags", []), *script.get("platforms", [])])),
                "category": escaped(category),
                "page_path": escaped(script["page_path"]),
                "name": escaped(script["name"]),
                "description": escaped(script["description"]),
                "tags": render_badges(script.get("tags", [])),
                "platforms": render_platform_badges(script.get("platforms", [])),
            },
        ).rstrip())

    content = render_template(
        "index.html",
        {
            "site_description": escaped(config["site_description"]),
            "base_path": escaped(config["base_path"]),
            "repository_url": escaped(config["repository_url"]),
            "cards": "\n".join(cards),
        },
    )
    return render_layout(config, config["site_title"], content, minimal_manifest(scripts))


def render_script_page(config: dict[str, Any], script: dict[str, Any]) -> str:
    platforms = render_platform_badges(script.get("platforms", [])) or escaped("Not specified")
    category = script.get("category", "script")
    filename = script["entry"]
    download_url = script["download_url"]
    script_language = highlight_language(filename)
    content = render_template(
        "script.html",
        {
            "base_path": escaped(config["base_path"]),
            "category": escaped(category),
            "version": escaped(script["version"]),
            "name": escaped(script["name"]),
            "description": escaped(script["description"]),
            "long_description": escaped(script["long_description"]),
            "requirements": render_list_items(script.get("requirements", [])),
            "platforms": platforms,
            "script_language": escaped(script_language),
            "usage": escaped("\n".join(script["usage"])),
            "download_url": escaped(download_url),
            "sha256": escaped(script["sha256"]),
            "source_url": escaped(script["source_url"]),
            "tags": render_badges(script.get("tags", [])),
            "curl_command": escaped(f'curl -fsSL "{download_url}" -o "{filename}"'),
            "wget_command": escaped(f'wget -O "{filename}" "{download_url}"'),
            "powershell_command": escaped(f'Invoke-WebRequest -Uri "{download_url}" -OutFile "{filename}"'),
            "script_content": escaped(script["script_content"]),
        },
    )
    return render_layout(config, f"{script['name']} | {config['site_title']}", content)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def copy_assets() -> None:
    source = TEMPLATE_DIR / "assets"
    target = SITE_DIR / "assets"
    if not source.is_dir():
        fail(f"missing template assets directory: {source}")
    shutil.copytree(source, target)


def generate(config: dict[str, Any], scripts: list[dict[str, Any]]) -> None:
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir(parents=True)
    write_text(SITE_DIR / ".nojekyll", "")
    copy_assets()
    write_text(SITE_DIR / "index.html", render_index(config, scripts))
    write_text(SITE_DIR / "manifest.json", json.dumps({"scripts": minimal_manifest(scripts)}, indent=None, sort_keys=True) + "\n")
    for script in scripts:
        write_text(SITE_DIR / "scripts" / script["id"] / "index.html", render_script_page(config, script))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate metadata and templates without writing site/")
    args = parser.parse_args()

    try:
        config = validate_config(load_json(CONFIG_PATH))
        schema = load_metadata_schema()
        scripts = load_scripts(config, schema)
        for template in ("layout.html", "index.html", "script.html", "components/script-card.html", "components/badge.html", "components/platform-badge.html", "components/list-item.html", "components/script-data.html"):
            read_template(template)
        if not args.check:
            generate(config, scripts)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    action = "Validated" if args.check else "Generated"
    print(f"{action} {len(scripts)} script(s).")
    return 0


if __name__ == "__main__":
    main()
