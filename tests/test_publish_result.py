from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


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
        "title": "Test requirement",
        "status": "completed",
        "selection_reason": "P1 and implementable",
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


def test_card_states_no_git_side_effects():
    card = publish_result.build_card(publish_result.validate_report(report()))
    content = "\n".join(
        element.get("text", {}).get("content", "") for element in card["elements"]
    )
    assert "未 commit、未 push、未 merge、未发布" in content
    assert "实施必要性核验" in content
