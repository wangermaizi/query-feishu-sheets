from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skill" / "feishu-requirement-orchestrator" / "scripts" / "branch_name.py"
SPEC = importlib.util.spec_from_file_location("branch_name", SCRIPT)
assert SPEC and SPEC.loader
branch_name = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(branch_name)


def test_proposes_three_part_chinese_branch():
    assert branch_name.propose("feature", "新增超额支付预警", "20260717") == (
        "feature/20260717/新增超额支付预警"
    )


def test_sanitizes_spaces_punctuation_and_english_case():
    assert branch_name.propose("fix", "Fix Payment: Warning", "20260717") == (
        "fix/20260717/fix-payment-warning"
    )


def test_validates_refactor_branch():
    name = "refactor/20260717/重构通知匹配逻辑"
    assert branch_name.validate(name) == name


def test_rejects_unknown_type():
    with pytest.raises(branch_name.BranchNameError, match="只能为"):
        branch_name.propose("chore", "更新依赖", "20260717")


def test_rejects_invalid_calendar_date():
    with pytest.raises(branch_name.BranchNameError, match="有效日历日期"):
        branch_name.propose("feature", "新增需求", "20260230")
