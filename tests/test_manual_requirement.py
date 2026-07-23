from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugin" / "feishu-codex-orchestrator" / "skills" / "feishu-requirement-orchestrator" / "scripts" / "manual_requirement.py"
SPEC = importlib.util.spec_from_file_location("manual_requirement", SCRIPT)
assert SPEC and SPEC.loader
manual_requirement = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manual_requirement)


def requirement(repository: Path):
    return {
        "title": "回款金额异常提醒",
        "description": "回款金额超过最新应收金额时提醒用户",
        "acceptance_criteria": ["列表显示异常提醒", "用户可以定位错误记录"],
        "project_name": "应收系统",
        "repository": str(repository),
    }


def test_normalizes_manual_requirement_and_assigns_next_daily_id(tmp_path):
    state = {
        "MANUAL-20260721-002": {"status": "completed"},
        "MANUAL-20260720-009": {"status": "completed"},
    }

    result = manual_requirement.normalize_requirements(
        [requirement(tmp_path)], state, "20260721"
    )

    assert result[0]["id"] == "MANUAL-20260721-003"
    assert result[0]["source_type"] == "manual"
    assert len(result[0]["source_fingerprint"]) == 64


def test_rejects_duplicate_manual_requirement(tmp_path):
    first = manual_requirement.normalize_requirements(
        [requirement(tmp_path)], {}, "20260721"
    )[0]
    state = {
        first["id"]: {
            "status": "reported",
            "source_fingerprint": first["source_fingerprint"],
        }
    }

    with pytest.raises(manual_requirement.ManualRequirementError, match=first["id"]):
        manual_requirement.normalize_requirements(
            [requirement(tmp_path)], state, "20260721"
        )


def test_allows_confirmed_duplicate_with_new_id(tmp_path):
    first = manual_requirement.normalize_requirements(
        [requirement(tmp_path)], {}, "20260721"
    )[0]
    state = {
        first["id"]: {
            "status": "reported",
            "source_fingerprint": first["source_fingerprint"],
        }
    }

    result = manual_requirement.normalize_requirements(
        [requirement(tmp_path)], state, "20260721", allow_duplicate=True
    )

    assert result[0]["id"] == "MANUAL-20260721-002"


def test_requires_existing_absolute_repository(tmp_path):
    payload = requirement(tmp_path)
    payload["repository"] = "relative-repository"

    with pytest.raises(manual_requirement.ManualRequirementError, match="绝对目录"):
        manual_requirement.normalize_requirements([payload], {}, "20260721")
