#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Classify implementation complexity and return the required verification policy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


TIERS = {"fast": 0, "standard": 1, "strict": 2}
RISK_FLAGS = {
    "architecture",
    "auth_permissions",
    "concurrency",
    "data_loss",
    "database_migration",
    "dependency_upgrade",
    "deployment",
    "external_contract",
    "public_api",
    "scope_uncertain",
    "security",
}
POLICIES = {
    "fast": {
        "test_scope": "focused",
        "reviewer_count": 1,
        "review_round_limit": 1,
    },
    "standard": {
        "test_scope": "related",
        "reviewer_count": 3,
        "review_round_limit": 1,
    },
    "strict": {
        "test_scope": "broad",
        "reviewer_count": 3,
        "review_round_limit": 2,
    },
}


class ComplexityError(ValueError):
    pass


def load_input(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComplexityError(f"无法读取复杂度评估 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ComplexityError("复杂度评估必须是 JSON 对象")
    return payload


def classify(payload: dict[str, Any]) -> dict[str, Any]:
    estimated_files = payload.get("estimated_files")
    if (
        not isinstance(estimated_files, list)
        or not estimated_files
        or not all(isinstance(value, str) and value.strip() for value in estimated_files)
    ):
        raise ComplexityError("estimated_files 必须为非空字符串数组")
    if not isinstance(payload.get("acceptance_clear"), bool):
        raise ComplexityError("acceptance_clear 必须为布尔值")
    if not isinstance(payload.get("cross_module"), bool):
        raise ComplexityError("cross_module 必须为布尔值")
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ComplexityError("reason 不能为空")
    risk_flags = payload.get("risk_flags", [])
    if not isinstance(risk_flags, list) or not all(
        isinstance(value, str) and value in RISK_FLAGS for value in risk_flags
    ):
        raise ComplexityError(
            "risk_flags 包含未知值；可用值: " + ", ".join(sorted(RISK_FLAGS))
        )
    minimum_tier = payload.get("minimum_tier", "fast")
    if minimum_tier not in TIERS:
        raise ComplexityError("minimum_tier 必须为 fast、standard 或 strict")

    calculated_tier = "fast"
    if len(estimated_files) > 2:
        calculated_tier = "standard"
    if (
        len(estimated_files) > 8
        or risk_flags
        or payload["cross_module"]
        or not payload["acceptance_clear"]
    ):
        calculated_tier = "strict"
    tier = max((calculated_tier, minimum_tier), key=TIERS.__getitem__)
    return {
        "tier": tier,
        "reason": reason.strip(),
        "estimated_files": estimated_files,
        "risk_flags": risk_flags,
        "acceptance_clear": payload["acceptance_clear"],
        "cross_module": payload["cross_module"],
        "policy": dict(POLICIES[tier]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = classify(load_input(args.input))
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    except ComplexityError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
