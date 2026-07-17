#!/usr/bin/env python3
"""Validate the distributable Codex Skill without relying on a local Codex install."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml


NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def error(message: str) -> None:
    raise ValueError(message)


def frontmatter(skill_md: Path) -> tuple[dict[str, object], str]:
    content = skill_md.read_text(encoding="utf-8")
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", content, re.DOTALL)
    if not match:
        error("SKILL.md must start with YAML frontmatter enclosed by ---")
    metadata = yaml.safe_load(match.group(1))
    if not isinstance(metadata, dict):
        error("SKILL.md frontmatter must be a YAML object")
    return metadata, match.group(2)


def validate(skill_dir: Path) -> None:
    if not skill_dir.is_dir():
        error(f"Skill directory does not exist: {skill_dir}")
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        error("Skill directory must contain SKILL.md")
    metadata, body = frontmatter(skill_md)
    if set(metadata) != {"name", "description"}:
        error("SKILL.md frontmatter must contain only name and description")
    name = metadata["name"]
    description = metadata["description"]
    if not isinstance(name, str) or not NAME_RE.fullmatch(name) or len(name) > 64:
        error("Skill name must be <=64 lowercase letters, digits, and hyphens")
    if skill_dir.name != name:
        error(f"Skill directory name must match frontmatter name: {name}")
    if not isinstance(description, str) or not description.strip():
        error("Skill description must be a non-empty string")
    if not body.strip():
        error("SKILL.md body must not be empty")

    agent_file = skill_dir / "agents" / "openai.yaml"
    if agent_file.is_file():
        agent = yaml.safe_load(agent_file.read_text(encoding="utf-8"))
        interface = agent.get("interface") if isinstance(agent, dict) else None
        if not isinstance(interface, dict):
            error("agents/openai.yaml must contain an interface object")
        short_description = interface.get("short_description")
        if not isinstance(short_description, str) or not 25 <= len(short_description) <= 64:
            error("interface.short_description must contain 25-64 characters")
        default_prompt = interface.get("default_prompt")
        if not isinstance(default_prompt, str) or f"${name}" not in default_prompt:
            error(f"interface.default_prompt must explicitly mention ${name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill_dir", type=Path)
    args = parser.parse_args()
    try:
        validate(args.skill_dir.resolve())
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Skill validation failed: {exc}", file=sys.stderr)
        return 1
    print("Skill is valid!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
