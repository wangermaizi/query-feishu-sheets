#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Validate assessed requirements and select the highest-ranked eligible item."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
SCORE_FIELDS = ("impact", "urgency", "ease", "risk")


class AssessmentError(ValueError):
    pass


def load_assessments(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssessmentError(f"无法读取评估 JSON: {exc}") from exc
    requirements = payload.get("requirements") if isinstance(payload, dict) else None
    if not isinstance(requirements, list):
        raise AssessmentError("评估 JSON 必须包含 requirements 数组")
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for index, item in enumerate(requirements):
        if not isinstance(item, dict):
            raise AssessmentError(f"requirements[{index}] 必须是对象")
        requirement_id = item.get("id")
        title = item.get("title")
        if not isinstance(requirement_id, str) or not requirement_id.strip():
            raise AssessmentError(f"requirements[{index}].id 不能为空")
        if requirement_id in seen:
            raise AssessmentError(f"需求 ID 重复: {requirement_id}")
        seen.add(requirement_id)
        if not isinstance(title, str) or not title.strip():
            raise AssessmentError(f"需求 {requirement_id} 缺少 title")
        priority = str(item.get("priority", "P3")).upper()
        if priority not in PRIORITY_ORDER:
            raise AssessmentError(f"需求 {requirement_id} priority 必须为 P0-P3")
        for field in SCORE_FIELDS:
            value = item.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
                raise AssessmentError(f"需求 {requirement_id} 的 {field} 必须为 1-5 整数")
        if not isinstance(item.get("eligible"), bool):
            raise AssessmentError(f"需求 {requirement_id} 的 eligible 必须为布尔值")
        reasons = item.get("blocked_reasons", [])
        if not isinstance(reasons, list) or not all(isinstance(value, str) for value in reasons):
            raise AssessmentError(f"需求 {requirement_id} 的 blocked_reasons 必须为字符串数组")
        normalized = dict(item)
        normalized["priority"] = priority
        normalized["_source_order"] = index
        validated.append(normalized)
    return validated


def rank_key(item: dict[str, Any]) -> tuple[int, int, int, int, int, int]:
    return (
        PRIORITY_ORDER[item["priority"]],
        -item["ease"],
        -item["impact"],
        -item["urgency"],
        item["risk"],
        item["_source_order"],
    )


def rank_requirements(items: list[dict[str, Any]]) -> dict[str, Any]:
    working = []
    for index, item in enumerate(items):
        normalized = dict(item)
        normalized.setdefault("_source_order", index)
        working.append(normalized)
    eligible = sorted((item for item in working if item["eligible"]), key=rank_key)
    blocked = [item for item in working if not item["eligible"]]
    for item in eligible + blocked:
        item.pop("_source_order", None)
    return {
        "selected": eligible[0] if eligible else None,
        "queue": eligible,
        "blocked": blocked,
        "eligible_count": len(eligible),
        "blocked_count": len(blocked),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = rank_requirements(load_assessments(args.input))
    except AssessmentError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
