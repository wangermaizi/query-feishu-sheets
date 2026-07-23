#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Resolve approximate profile names and persist an explicitly selected default."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any


GENERIC_SUFFIXES = ("需求表格", "需求表", "电子表格", "表格", "表")


class SelectorError(ValueError):
    pass


def config_dir() -> Path:
    return Path(
        os.environ.get(
            "FEISHU_ORCHESTRATOR_CONFIG_DIR",
            Path.home() / ".codex" / "feishu-requirement-orchestrator",
        )
    ).expanduser()


def load_object(path: Path, root_key: str | None = None) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if root_key:
            return {root_key: {}}
        return {}
    except json.JSONDecodeError as exc:
        raise SelectorError(f"JSON 配置无效: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SelectorError(f"配置必须为 JSON 对象: {path}")
    if root_key and not isinstance(payload.get(root_key), dict):
        raise SelectorError(f"配置缺少对象字段 {root_key}: {path}")
    return payload


def normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(char for char in normalized if char.isalnum())


def name_forms(value: str) -> set[str]:
    base = normalize(value)
    forms = {base} if base else set()
    for suffix in GENERIC_SUFFIXES:
        normalized_suffix = normalize(suffix)
        if base.endswith(normalized_suffix) and len(base) > len(normalized_suffix):
            forms.add(base[: -len(normalized_suffix)])
    return forms


def public_profile(profile_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    aliases = profile.get("aliases", [])
    if not isinstance(aliases, list):
        aliases = []
    return {
        "profile_id": profile_id,
        "display_name": profile.get("display_name", profile_id),
        "aliases": [value for value in aliases if isinstance(value, str)],
        "description": profile.get("description", ""),
        "default_sheet": profile.get("default_sheet"),
        "default_table": profile.get("default_table"),
    }


def resolve_profiles(name: str, profiles: dict[str, Any]) -> dict[str, Any]:
    query_forms = name_forms(name)
    exact: list[dict[str, Any]] = []
    approximate: list[dict[str, Any]] = []
    all_profiles: list[dict[str, Any]] = []
    for profile_id, value in sorted(profiles.items()):
        if not isinstance(value, dict):
            continue
        public = public_profile(profile_id, value)
        all_profiles.append(public)
        names = [profile_id, str(public["display_name"]), *public["aliases"]]
        candidate_forms = set().union(*(name_forms(item) for item in names))
        if name == profile_id or query_forms & candidate_forms:
            exact.append({**public, "match_type": "exact_or_normalized"})
        elif any(
            query in candidate or candidate in query
            for query in query_forms
            for candidate in candidate_forms
            if query and candidate
        ):
            approximate.append({**public, "match_type": "contains"})
    return {
        "query": name,
        "exact_matches": exact,
        "approximate_matches": approximate,
        "profiles": all_profiles,
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    resolve = commands.add_parser("resolve")
    resolve.add_argument("--name", required=True)
    switch = commands.add_parser("switch")
    switch.add_argument("--profile-id", required=True)
    commands.add_parser("current")
    args = parser.parse_args()
    try:
        profiles_payload = load_object(config_dir() / "profiles.json", "profiles")
        profiles = profiles_payload["profiles"]
        if args.command == "resolve":
            result = resolve_profiles(args.name, profiles)
        elif args.command == "switch":
            if args.profile_id not in profiles:
                raise SelectorError(f"找不到 profile_id: {args.profile_id}")
            path = config_dir() / "orchestrator.json"
            settings = load_object(path)
            previous = settings.get("profile")
            settings["profile"] = args.profile_id
            atomic_write(path, settings)
            result = {"switched": True, "previous_profile": previous, "profile": args.profile_id}
        else:
            settings = load_object(config_dir() / "orchestrator.json")
            result = {"profile": settings.get("profile")}
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    except (OSError, SelectorError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
