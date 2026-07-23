#!/usr/bin/env python3
"""Validate the repository's distributable Codex plugin structure."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class PluginValidationError(ValueError):
    pass


def read_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PluginValidationError(f"{label} is invalid: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PluginValidationError(f"{label} must be a JSON object: {path}")
    return value


def required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PluginValidationError(f"{label} must be a non-empty string")
    return value.strip()


def relative_file(root: Path, value: object, label: str) -> Path:
    relative = required_string(value, label)
    if not relative.startswith("./"):
        raise PluginValidationError(f"{label} must start with ./")
    resolved = (root / relative[2:]).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise PluginValidationError(f"{label} escapes plugin root") from exc
    if not resolved.exists():
        raise PluginValidationError(f"{label} does not exist: {relative}")
    return resolved


def validate(plugin: Path) -> None:
    plugin = plugin.resolve()
    manifest_path = plugin / ".codex-plugin" / "plugin.json"
    manifest = read_object(manifest_path, "plugin manifest")
    serialized = json.dumps(manifest, ensure_ascii=False)
    if "[TODO:" in serialized:
        raise PluginValidationError("plugin manifest contains TODO placeholders")

    name = required_string(manifest.get("name"), "name")
    if not NAME.fullmatch(name) or name != plugin.name:
        raise PluginValidationError("plugin name must be kebab-case and match its folder")
    version = required_string(manifest.get("version"), "version")
    if not SEMVER.fullmatch(version):
        raise PluginValidationError("version must be strict semver")
    required_string(manifest.get("description"), "description")
    author = manifest.get("author")
    if not isinstance(author, dict):
        raise PluginValidationError("author must be an object")
    required_string(author.get("name"), "author.name")

    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        raise PluginValidationError("interface must be an object")
    for field in (
        "displayName",
        "shortDescription",
        "longDescription",
        "developerName",
        "category",
    ):
        required_string(interface.get(field), f"interface.{field}")
    prompts = interface.get("defaultPrompt")
    if not isinstance(prompts, list) or not 1 <= len(prompts) <= 3:
        raise PluginValidationError("interface.defaultPrompt must contain 1 to 3 strings")
    for index, prompt in enumerate(prompts):
        if len(required_string(prompt, f"interface.defaultPrompt[{index}]")) > 128:
            raise PluginValidationError("default prompts must be at most 128 characters")

    skills = relative_file(plugin, manifest.get("skills"), "skills")
    if not skills.is_dir() or not any(skills.glob("*/SKILL.md")):
        raise PluginValidationError("skills must contain at least one Skill")
    mcp_path = relative_file(plugin, manifest.get("mcpServers"), "mcpServers")
    mcp = read_object(mcp_path, "MCP configuration")
    servers = mcp.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        raise PluginValidationError("MCP configuration must contain at least one server")
    for server_name, server in servers.items():
        if not isinstance(server, dict) or not server.get("command"):
            raise PluginValidationError(f"MCP server is invalid: {server_name}")

    gateway = plugin / "scripts" / "gateway"
    for filename in ("package.json", "package-lock.json", "src/main.js", "src/mcp-server.js"):
        if not (gateway / filename).is_file():
            raise PluginValidationError(f"gateway file is missing: {filename}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin", type=Path)
    args = parser.parse_args()
    try:
        validate(args.plugin)
        print("Plugin is valid!")
        return 0
    except PluginValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
