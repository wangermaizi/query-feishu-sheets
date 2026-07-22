from __future__ import annotations

import importlib.util
import sys
from argparse import Namespace
from datetime import datetime, timedelta, timezone
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


STANDARD_ROLES = ["functionality", "testing", "quality-security"]


def reviews(roles: list[str]):
    return [{"role": role, "findings": []} for role in roles]


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
    assert started["expected_review_roles"] == STANDARD_ROLES
    assert started["review_timeout_seconds"] == 900


def test_fixes_cannot_start_until_all_first_round_reviewers_return():
    started = review_gate.start(review_gate.prepare(entry(), prepare_args()))

    with pytest.raises(review_gate.ReviewGateError, match="精确角色集合"):
        review_gate.collect(started, reviews(STANDARD_ROLES[:2]))

    collected = review_gate.collect(started, reviews(STANDARD_ROLES))
    assert collected["review_phase"] == "review_findings_ready"
    assert collected["all_reviewers_collected"] is True


def test_standard_review_cannot_request_second_round():
    started = review_gate.start(review_gate.prepare(entry(), prepare_args()))
    collected = review_gate.collect(started, reviews(STANDARD_ROLES))

    with pytest.raises(review_gate.ReviewGateError, match="重新分级为 strict"):
        review_gate.complete(
            collected,
            complete_args(request_rereview="high_severity"),
        )


def test_strict_allows_one_targeted_second_round_after_consolidated_fixes():
    first = review_gate.start(review_gate.prepare(entry("strict"), prepare_args()))
    collected = review_gate.collect(first, reviews(STANDARD_ROLES))
    fixing = review_gate.complete(
        collected,
        complete_args(request_rereview="high_severity"),
    )
    ready = review_gate.prepare(
        fixing,
        prepare_args(rereview_reason="high_severity"),
    )
    second = review_gate.start(ready, ["testing"])
    targeted = review_gate.collect(second, reviews(["testing"]))
    completed = review_gate.complete(targeted, complete_args())

    assert second["review_rounds_started"] == 2
    assert second["review_scope"] == "targeted_rereview"
    assert completed["review_phase"] == "review_complete"


def test_status_exposes_report_ready_timeline_after_completion():
    started = review_gate.start(review_gate.prepare(entry("fast"), prepare_args()))
    collected = review_gate.collect(started, reviews(["combined"]))
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


@pytest.mark.parametrize(
    ("tier", "seconds"),
    [("fast", 600), ("standard", 900), ("strict", 1200)],
)
def test_timeout_depends_on_complexity_tier(tier, seconds):
    now = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
    started = review_gate.start(review_gate.prepare(entry(tier), prepare_args()), now=now)

    assert started["review_timeout_seconds"] == seconds
    assert set(started["review_role_deadlines"].values()) == {
        review_gate.timestamp(now + timedelta(seconds=seconds))
    }


def test_timeout_retry_requires_deadline_and_only_resets_affected_role():
    now = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
    started = review_gate.start(review_gate.prepare(entry(), prepare_args()), now=now)
    original_deadlines = dict(started["review_role_deadlines"])

    with pytest.raises(review_gate.ReviewGateError, match="尚未超时"):
        review_gate.retry(started, "testing", "timeout", now + timedelta(minutes=14))

    retried = review_gate.retry(
        started, "testing", "timeout", now + timedelta(minutes=15)
    )
    assert retried["review_attempts"] == {
        "functionality": 1,
        "testing": 2,
        "quality-security": 1,
    }
    assert retried["review_role_deadlines"]["functionality"] == original_deadlines["functionality"]
    assert retried["review_role_deadlines"]["quality-security"] == original_deadlines["quality-security"]
    assert retried["review_role_deadlines"]["testing"] == review_gate.timestamp(
        now + timedelta(minutes=30)
    )


@pytest.mark.parametrize("reason", ["failed", "exited"])
def test_failed_or_exited_reviewer_can_be_replaced_immediately(reason):
    now = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
    started = review_gate.start(review_gate.prepare(entry("fast"), prepare_args()), now=now)

    retried = review_gate.retry(started, "combined", reason, now)

    assert retried["review_attempts"]["combined"] == 2
    assert retried["review_retry_history"][0]["reason"] == reason


def test_each_role_can_only_be_replaced_once():
    started = review_gate.start(review_gate.prepare(entry("fast"), prepare_args()))
    retried = review_gate.retry(started, "combined", "failed")

    with pytest.raises(review_gate.ReviewGateError, match="用完一次"):
        review_gate.retry(retried, "combined", "exited")


def test_replacement_result_under_same_role_can_complete_collection():
    started = review_gate.start(review_gate.prepare(entry("fast"), prepare_args()))
    retried = review_gate.retry(started, "combined", "failed")

    collected = review_gate.collect(retried, reviews(["combined"]))

    assert collected["review_phase"] == "review_findings_ready"


def test_second_failure_blocks_review_and_prevents_successful_report():
    started = review_gate.start(review_gate.prepare(entry("fast"), prepare_args()))
    retried = review_gate.retry(started, "combined", "failed")
    blocked = review_gate.block(retried, "combined", "替换 Reviewer 也已退出")

    status = review_gate.status_payload(blocked)
    assert blocked["review_phase"] == "review_blocked"
    assert status["report_ready"] is False
    assert status["review_blocked_role"] == "combined"
    with pytest.raises(review_gate.ReviewGateError, match="reviewing"):
        review_gate.collect(blocked, reviews(["combined"]))


def test_status_lists_overdue_roles():
    now = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
    started = review_gate.start(review_gate.prepare(entry("fast"), prepare_args()), now=now)

    status = review_gate.status_payload(started, now + timedelta(minutes=10))

    assert status["overdue_review_roles"] == ["combined"]
