from __future__ import annotations

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skill" / "feishu-requirement-orchestrator" / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("review_gate", SCRIPTS / "review_gate.py")
assert SPEC and SPEC.loader
review_gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review_gate)


def entry(tier: str = "standard"):
    return {
        "status": "in_progress",
        "complexity_tier": tier,
        "review_phase": "implementation",
    }


def prepare_args(**overrides):
    value = {
        "implementation_summary": "全部验收项已实现",
        "test_result": ["targeted tests passed"],
        "candidate_file": ["src/service.py", "tests/test_service.py"],
        "rereview_reason": None,
    }
    value.update(overrides)
    return Namespace(**value)


def complete_args(**overrides):
    value = {
        "resolution_summary": "已集中处理全部成立问题",
        "test_result": ["affected tests passed"],
        "request_rereview": None,
    }
    value.update(overrides)
    return Namespace(**value)


def reviews(count: int):
    return [
        {"role": f"reviewer-{index}", "findings": []}
        for index in range(1, count + 1)
    ]


def test_review_cannot_start_before_complete_candidate_is_prepared():
    with pytest.raises(review_gate.ReviewGateError, match="先 prepare"):
        review_gate.start(entry())


def test_standard_review_starts_only_after_full_implementation_and_tests():
    prepared = review_gate.prepare(entry(), prepare_args())
    started = review_gate.start(prepared)

    assert started["review_phase"] == "reviewing"
    assert started["review_rounds_started"] == 1
    assert started["review_scope"] == "complete_candidate"
    assert started["expected_reviewers"] == 3


def test_fixes_cannot_start_until_all_first_round_reviewers_return():
    started = review_gate.start(review_gate.prepare(entry(), prepare_args()))

    with pytest.raises(review_gate.ReviewGateError, match="一次收齐 3"):
        review_gate.collect(started, reviews(2))

    collected = review_gate.collect(started, reviews(3))
    assert collected["review_phase"] == "review_findings_ready"
    assert collected["all_reviewers_collected"] is True


def test_standard_review_cannot_request_second_round():
    started = review_gate.start(review_gate.prepare(entry(), prepare_args()))
    collected = review_gate.collect(started, reviews(3))

    with pytest.raises(review_gate.ReviewGateError, match="重新分级为 strict"):
        review_gate.complete(
            collected,
            complete_args(request_rereview="high_severity"),
        )


def test_strict_allows_one_targeted_second_round_after_consolidated_fixes():
    first = review_gate.start(review_gate.prepare(entry("strict"), prepare_args()))
    collected = review_gate.collect(first, reviews(3))
    fixing = review_gate.complete(
        collected,
        complete_args(request_rereview="high_severity"),
    )
    ready = review_gate.prepare(
        fixing,
        prepare_args(rereview_reason="high_severity"),
    )
    second = review_gate.start(ready)
    targeted = review_gate.collect(second, reviews(1))
    completed = review_gate.complete(targeted, complete_args())

    assert second["review_rounds_started"] == 2
    assert second["review_scope"] == "targeted_rereview"
    assert completed["review_phase"] == "review_complete"


def test_status_exposes_report_ready_timeline_after_completion():
    started = review_gate.start(review_gate.prepare(entry("fast"), prepare_args()))
    collected = review_gate.collect(started, reviews(1))
    completed = review_gate.complete(collected, complete_args())

    status = review_gate.status_payload(completed)

    assert status["report_ready"] is True
    assert status["review_rounds"] == 1
    assert status["review_process"]["complete_candidate_reviewed"] is True
    assert status["review_process"]["all_reviewers_collected_before_fixes"] is True


def test_candidate_snapshot_detects_changes_during_review(tmp_path):
    candidate = tmp_path / "service.py"
    candidate.write_text("before\n", encoding="utf-8")
    value = entry("fast")
    value.update(
        {
            "repository": str(tmp_path),
            "worktree_path": str(tmp_path),
            "review_candidate_files": ["service.py"],
            "review_candidate_snapshot": review_gate.candidate_snapshot(
                str(tmp_path), ["service.py"]
            ),
        }
    )

    candidate.write_text("after\n", encoding="utf-8")

    with pytest.raises(review_gate.ReviewGateError, match="发生变化"):
        review_gate.verify_candidate_unchanged(value)
