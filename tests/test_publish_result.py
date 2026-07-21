from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skill" / "feishu-requirement-orchestrator" / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("publish_result", SCRIPTS / "publish_result.py")
assert SPEC and SPEC.loader
publish_result = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publish_result)


def report():
    return {
        "requirement_id": "REQ-1",
        "project_name": "OA",
        "title": "Test requirement",
        "status": "completed",
        "selection_reason": "P1 and implementable",
        "plain_language_summary": "现状：系统会重复处理。影响：用户看到重复结果。目标：避免重复处理。",
        "complexity_tier": "standard",
        "complexity_reason": "修改三个相关模块，需要三路审查",
        "review_rounds": 1,
        "review_process": {
            "implementation_completed_at": "2026-07-16T17:00:00+08:00",
            "first_review_started_at": "2026-07-16T17:10:00+08:00",
            "complete_candidate_reviewed": True,
            "all_reviewers_collected_before_fixes": True,
        },
        "necessity_assessment": {
            "status": "partially_done",
            "reason": "Base query exists, deduplication is missing",
            "evidence": ["src/service.py:120"],
            "remaining_criteria": ["Do not process completed requirements twice"],
        },
        "repository": "D:\\workspace\\example",
        "branch": "main",
        "changes": ["Changed behavior"],
        "tests": [{"command": "uv run pytest", "result": "passed"}],
        "reviews": [
            {"role": "functionality", "finding_count": 0, "summary": "clear"},
            {"role": "testing", "finding_count": 0, "summary": "clear"},
            {"role": "quality-security", "finding_count": 0, "summary": "clear"},
        ],
        "residual_risks": [],
        "next_action": "Confirm acceptance",
        "completed_at": "2026-07-16T18:00:00+08:00",
    }


def test_hash_binds_report_to_chat():
    validated = publish_result.validate_report(report())
    first = publish_result.report_hash(validated, "oc_first")
    second = publish_result.report_hash(validated, "oc_second")
    assert first != second


def test_card_shows_concise_user_facing_result():
    card = publish_result.build_card(publish_result.validate_report(report()))
    content = "\n".join(
        element.get("text", {}).get("content", "") for element in card["elements"]
    )
    assert "未 commit、未 push、未 merge、未发布" in content
    assert "需求说明" in content
    assert "现状：系统会重复处理" in content
    assert "修改内容" in content
    assert "待确认" in content
    assert "复杂度与验证策略" not in content
    assert "实施必要性核验" not in content
    assert "验证结果" not in content
    assert "Review 结果" not in content
    assert "残余风险" not in content
    assert card["header"]["title"]["content"] == "【OA】Test requirement"
    assert "**项目：** OA" in content


def test_project_name_is_required_for_group_title():
    payload = report()
    del payload["project_name"]
    with pytest.raises(publish_result.ReportError, match="project_name"):
        publish_result.validate_report(payload)


def test_plain_language_summary_is_required():
    payload = report()
    del payload["plain_language_summary"]
    with pytest.raises(publish_result.ReportError, match="plain_language_summary"):
        publish_result.validate_report(payload)


def test_fast_report_accepts_one_combined_reviewer():
    payload = report()
    payload["complexity_tier"] = "fast"
    payload["complexity_reason"] = "局部两文件修改"
    payload["reviews"] = [
        {"role": "combined", "finding_count": 0, "summary": "未发现问题"}
    ]

    validated = publish_result.validate_report(payload)

    assert len(validated["reviews"]) == 1


def test_fast_report_rejects_three_reviewers():
    payload = report()
    payload["complexity_tier"] = "fast"
    with pytest.raises(publish_result.ReportError, match="1 个 Reviewer"):
        publish_result.validate_report(payload)


def test_standard_report_rejects_second_review_round():
    payload = report()
    payload["review_rounds"] = 2
    with pytest.raises(publish_result.ReportError, match="review_rounds"):
        publish_result.validate_report(payload)


def test_strict_report_accepts_second_review_round():
    payload = report()
    payload["complexity_tier"] = "strict"
    payload["review_rounds"] = 2

    assert publish_result.validate_report(payload)["review_rounds"] == 2


def test_report_rejects_review_started_before_implementation_completed():
    payload = report()
    payload["review_process"]["implementation_completed_at"] = (
        "2026-07-16T17:20:00+08:00"
    )

    with pytest.raises(publish_result.ReportError, match="不得早于"):
        publish_result.validate_report(payload)
