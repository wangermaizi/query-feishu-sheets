from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugin" / "feishu-codex-orchestrator" / "skills" / "feishu-requirement-orchestrator" / "scripts" / "complexity_policy.py"
SPEC = importlib.util.spec_from_file_location("complexity_policy", SCRIPT)
assert SPEC and SPEC.loader
complexity_policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(complexity_policy)


def assessment(**overrides):
    value = {
        "estimated_files": ["src/view.ts", "tests/view.test.ts"],
        "acceptance_clear": True,
        "cross_module": False,
        "risk_flags": [],
        "reason": "局部行为修改，范围明确",
    }
    value.update(overrides)
    return value


def test_two_file_local_change_uses_fast_policy():
    result = complexity_policy.classify(assessment())

    assert result["tier"] == "fast"
    assert result["policy"] == {
        "test_scope": "focused",
        "reviewer_count": 1,
        "review_round_limit": 1,
        "review_timeout_minutes": 10,
    }


def test_more_than_two_files_uses_standard_policy():
    result = complexity_policy.classify(
        assessment(estimated_files=["a", "b", "c"])
    )

    assert result["tier"] == "standard"
    assert result["policy"]["reviewer_count"] == 3
    assert result["policy"]["review_timeout_minutes"] == 15


def test_high_risk_signal_forces_strict_policy():
    result = complexity_policy.classify(
        assessment(risk_flags=["database_migration"])
    )

    assert result["tier"] == "strict"
    assert result["policy"]["review_round_limit"] == 2
    assert result["policy"]["review_timeout_minutes"] == 20


def test_large_file_scope_forces_strict_policy():
    result = complexity_policy.classify(
        assessment(estimated_files=[f"src/file-{index}.ts" for index in range(9)])
    )

    assert result["tier"] == "strict"


def test_main_agent_can_raise_but_not_lower_tier():
    result = complexity_policy.classify(assessment(minimum_tier="strict"))

    assert result["tier"] == "strict"
