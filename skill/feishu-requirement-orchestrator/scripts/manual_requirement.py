#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["tzdata>=2025.2"]
# ///
"""Validate directly supplied requirements and assign stable local IDs."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


MANUAL_ID_RE = re.compile(r"^MANUAL-(\d{8})-(\d{3,})$")
PRIORITIES = {"P0", "P1", "P2", "P3"}


class ManualRequirementError(ValueError):
    pass


def config_dir() -> Path:
    return Path(
        os.environ.get(
            "FEISHU_ORCHESTRATOR_CONFIG_DIR",
            Path.home() / ".codex" / "feishu-requirement-orchestrator",
        )
    ).expanduser()


def load_state_requirements() -> dict[str, Any]:
    path = config_dir() / "state.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ManualRequirementError(f"无法读取 state.json: {exc}") from exc
    requirements = payload.get("requirements") if isinstance(payload, dict) else None
    if not isinstance(requirements, dict):
        raise ManualRequirementError("state.json 必须包含 requirements 对象")
    return requirements


def parse_day(value: str | None) -> str:
    if value is None:
        return dt.datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
    try:
        parsed = dt.datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ManualRequirementError("日期必须是有效的 YYYYMMDD") from exc
    return parsed.strftime("%Y%m%d")


def required_text(item: dict[str, Any], field: str, index: int) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ManualRequirementError(f"requirements[{index}].{field} 不能为空")
    return value.strip()


def string_list(value: Any, field: str, index: int, *, required: bool) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    elif value is None and not required:
        return []
    else:
        raise ManualRequirementError(f"requirements[{index}].{field} 必须是字符串或字符串数组")
    normalized = [entry.strip() for entry in values if isinstance(entry, str) and entry.strip()]
    if len(normalized) != len(values) or (required and not normalized):
        raise ManualRequirementError(f"requirements[{index}].{field} 包含空值或非字符串")
    return normalized


def normalized_for_hash(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def fingerprint(item: dict[str, Any]) -> str:
    canonical = {
        "title": normalized_for_hash(item["title"]),
        "description": normalized_for_hash(item["description"]),
        "acceptance_criteria": [
            normalized_for_hash(value) for value in item["acceptance_criteria"]
        ],
        "project_name": normalized_for_hash(item["project_name"]),
        "repository": normalized_for_hash(item["repository"]),
    }
    serialized = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def load_input(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManualRequirementError(f"无法读取手动需求 JSON: {exc}") from exc
    values = payload.get("requirements") if isinstance(payload, dict) else None
    if values is None and isinstance(payload, dict):
        values = [payload]
    if not isinstance(values, list) or not values:
        raise ManualRequirementError("输入必须是单条需求对象或包含 requirements 的非空对象")
    if not all(isinstance(value, dict) for value in values):
        raise ManualRequirementError("requirements 中的每一项都必须是对象")
    return values


def normalize_requirements(
    items: list[dict[str, Any]],
    state_requirements: dict[str, Any],
    day: str,
    *,
    allow_duplicate: bool = False,
) -> list[dict[str, Any]]:
    recorded_ids = [
        entry.get("requirement_id", state_key)
        if isinstance(entry, dict)
        else state_key
        for state_key, entry in state_requirements.items()
    ]
    used_sequences = [
        int(match.group(2))
        for requirement_id in recorded_ids
        if isinstance(requirement_id, str)
        and (match := MANUAL_ID_RE.fullmatch(requirement_id))
        and match.group(1) == day
    ]
    next_sequence = max(used_sequences, default=0) + 1
    known_fingerprints = {
        entry.get("source_fingerprint"): entry.get("requirement_id", state_key)
        for state_key, entry in state_requirements.items()
        if isinstance(entry, dict) and isinstance(entry.get("source_fingerprint"), str)
    }
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(items):
        title = required_text(raw, "title", index)
        description = required_text(raw, "description", index)
        project_name = required_text(raw, "project_name", index)
        repository_value = required_text(raw, "repository", index)
        repository = Path(repository_value).expanduser()
        if not repository.is_absolute() or not repository.is_dir():
            raise ManualRequirementError(
                f"requirements[{index}].repository 必须是已存在的绝对目录"
            )
        acceptance_criteria = string_list(
            raw.get("acceptance_criteria"), "acceptance_criteria", index, required=True
        )
        references = string_list(raw.get("references"), "references", index, required=False)
        priority_value = raw.get("priority")
        priority = None
        if priority_value is not None:
            priority = str(priority_value).upper()
            if priority not in PRIORITIES:
                raise ManualRequirementError(
                    f"requirements[{index}].priority 必须为 P0-P3"
                )
        item = {
            "title": title,
            "description": description,
            "acceptance_criteria": acceptance_criteria,
            "project_name": project_name,
            "repository": str(repository.resolve()),
            "references": references,
        }
        if priority is not None:
            item["priority"] = priority
        source_fingerprint = fingerprint(item)
        duplicate_id = known_fingerprints.get(source_fingerprint)
        if duplicate_id and not allow_duplicate:
            raise ManualRequirementError(
                f"手动需求与已记录的 {duplicate_id} 内容相同；请继续该需求，或确认后使用 --allow-duplicate"
            )
        requirement_id = f"MANUAL-{day}-{next_sequence:03d}"
        next_sequence += 1
        known_fingerprints[source_fingerprint] = requirement_id
        normalized.append(
            {
                "id": requirement_id,
                **item,
                "source_type": "manual",
                "source_fingerprint": source_fingerprint,
                "source": dict(raw),
            }
        )
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--date")
    parser.add_argument("--allow-duplicate", action="store_true")
    args = parser.parse_args()
    try:
        requirements = normalize_requirements(
            load_input(args.input),
            load_state_requirements(),
            parse_day(args.date),
            allow_duplicate=args.allow_duplicate,
        )
        json.dump({"requirements": requirements}, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    except ManualRequirementError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
