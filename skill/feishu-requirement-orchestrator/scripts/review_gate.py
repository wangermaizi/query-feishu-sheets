#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Enforce implementation-complete-before-review workflow gates."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import run_state


POLICIES = {
    "fast": {"reviewer_count": 1, "round_limit": 1},
    "standard": {"reviewer_count": 3, "round_limit": 1},
    "strict": {"reviewer_count": 3, "round_limit": 2},
}
REREVIEW_REASONS = {"high_severity", "public_contract", "scope_upgrade"}


class ReviewGateError(ValueError):
    pass


def timestamp() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def load_entry(
    requirements: dict[str, Any], requirement_id: str, repository: str
) -> tuple[str, dict[str, Any]]:
    scope = run_state.resolve_scope(repository)
    state_key = run_state.find_state_key(
        requirements, requirement_id, scope["repository_identity"]
    )
    if state_key is None:
        raise ReviewGateError(f"找不到当前仓库中的需求: {requirement_id}")
    raw_entry = requirements.get(state_key)
    if not isinstance(raw_entry, dict):
        raise ReviewGateError(f"需求状态无效: {requirement_id}")
    return state_key, dict(raw_entry)


def policy_for(entry: dict[str, Any]) -> dict[str, int]:
    tier = entry.get("complexity_tier")
    if tier not in POLICIES:
        raise ReviewGateError("开始 Review 前必须完成 complexity_tier 分级")
    return POLICIES[tier]


def require_strings(values: list[str], label: str) -> list[str]:
    normalized = [value.strip() for value in values if isinstance(value, str) and value.strip()]
    if not normalized or len(normalized) != len(values):
        raise ReviewGateError(f"{label} 必须为非空字符串列表")
    return normalized


def candidate_snapshot(repository: str, files: list[str]) -> str:
    root = Path(repository).resolve()
    digest = hashlib.sha256()
    for value in sorted(files):
        candidate = Path(value)
        path = (candidate if candidate.is_absolute() else root / candidate).resolve()
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise ReviewGateError(f"候选文件不在目标 worktree 内: {value}") from exc
        digest.update(str(relative).replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        if path.is_dir():
            raise ReviewGateError(f"candidate-file 不能是目录: {value}")
        if path.exists():
            digest.update(path.read_bytes())
        else:
            digest.update(b"<deleted-or-missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def verify_candidate_unchanged(entry: dict[str, Any]) -> None:
    expected = entry.get("review_candidate_snapshot")
    files = entry.get("review_candidate_files")
    repository = entry.get("worktree_path") or entry.get("repository")
    if not isinstance(expected, str) or not expected:
        raise ReviewGateError("候选实现缺少文件快照，请重新 prepare")
    if not isinstance(files, list) or not isinstance(repository, str):
        raise ReviewGateError("候选实现范围无效，请重新 prepare")
    if candidate_snapshot(repository, files) != expected:
        raise ReviewGateError("候选文件在 Review 门禁后发生变化，请重新 prepare")


def prepare(entry: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if entry.get("status") != "in_progress":
        raise ReviewGateError("只有 in_progress 需求可以进入 review_ready")
    phase = entry.get("review_phase")
    if phase not in {None, "implementation", "review_fixes"}:
        raise ReviewGateError(f"当前 review_phase={phase}，不能执行 prepare")
    if phase == "review_fixes" and not args.rereview_reason:
        raise ReviewGateError("复审前必须提供 --rereview-reason")
    if args.rereview_reason and args.rereview_reason not in REREVIEW_REASONS:
        raise ReviewGateError("复审原因无效")
    summary = args.implementation_summary.strip()
    if not summary:
        raise ReviewGateError("implementation-summary 不能为空")
    tests = require_strings(args.test_result, "test-result")
    files = require_strings(args.candidate_file, "candidate-file")
    policy = policy_for(entry)
    started = int(entry.get("review_rounds_started", 0))
    if phase == "review_fixes":
        if args.rereview_reason != entry.get("pending_rereview_reason"):
            raise ReviewGateError("rereview-reason 必须与集中修复时申请的原因一致")
        if entry.get("complexity_tier") != "strict":
            raise ReviewGateError("只有 strict 级需求允许第二轮复审")
        if started >= policy["round_limit"]:
            raise ReviewGateError("已达到 Review 轮次上限")
        entry["review_scope"] = "targeted_rereview"
        entry["rereview_reason"] = args.rereview_reason
    else:
        if started:
            raise ReviewGateError("初次 Review 已经开始，不能重新创建完整候选")
        entry["review_scope"] = "complete_candidate"
        entry["implementation_completed_at"] = timestamp()
    entry.update(
        {
            "review_phase": "review_ready",
            "implementation_summary": summary,
            "implementation_test_results": tests,
            "review_candidate_files": files,
            "expected_reviewers": policy["reviewer_count"],
            "review_round_limit": policy["round_limit"],
        }
    )
    return entry


def start(entry: dict[str, Any]) -> dict[str, Any]:
    if entry.get("review_phase") != "review_ready":
        raise ReviewGateError("必须先 prepare 完整候选实现，才能启动 Reviewer")
    policy = policy_for(entry)
    started = int(entry.get("review_rounds_started", 0))
    if started >= policy["round_limit"]:
        raise ReviewGateError("已达到 Review 轮次上限")
    round_number = started + 1
    history = list(entry.get("review_started_at", []))
    history.append(timestamp())
    entry.update(
        {
            "review_phase": "reviewing",
            "review_rounds_started": round_number,
            "current_review_round": round_number,
            "review_started_at": history,
        }
    )
    return entry


def read_review_results(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewGateError(f"无法读取 Review 结果: {exc}") from exc
    reviews = payload.get("reviews") if isinstance(payload, dict) else None
    if not isinstance(reviews, list) or not reviews:
        raise ReviewGateError("Review 结果必须包含非空 reviews 数组")
    roles: set[str] = set()
    for index, review in enumerate(reviews):
        if not isinstance(review, dict):
            raise ReviewGateError(f"reviews[{index}] 必须是对象")
        role = review.get("role")
        findings = review.get("findings")
        if not isinstance(role, str) or not role.strip():
            raise ReviewGateError(f"reviews[{index}].role 不能为空")
        if role in roles:
            raise ReviewGateError(f"Reviewer 角色重复: {role}")
        if not isinstance(findings, list):
            raise ReviewGateError(f"reviews[{index}].findings 必须为数组")
        roles.add(role)
    return reviews


def collect(entry: dict[str, Any], reviews: list[dict[str, Any]]) -> dict[str, Any]:
    if entry.get("review_phase") != "reviewing":
        raise ReviewGateError("只有 reviewing 阶段可以收集结果")
    round_number = int(entry.get("current_review_round", 0))
    expected = int(entry.get("expected_reviewers", 0))
    if round_number == 1 and len(reviews) != expected:
        raise ReviewGateError(f"首轮必须一次收齐 {expected} 个 Reviewer 结果")
    if round_number > 1 and not 1 <= len(reviews) <= expected:
        raise ReviewGateError(f"定向复审必须包含 1 到 {expected} 个 Reviewer 结果")
    rounds = list(entry.get("review_results", []))
    rounds.append(
        {
            "round": round_number,
            "scope": entry.get("review_scope"),
            "collected_at": timestamp(),
            "reviews": reviews,
        }
    )
    entry.update(
        {
            "review_phase": "review_findings_ready",
            "review_results": rounds,
            "all_reviewers_collected": True,
        }
    )
    return entry


def complete(entry: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if entry.get("review_phase") != "review_findings_ready":
        raise ReviewGateError("必须先一次收齐本轮全部 Reviewer 结果")
    summary = args.resolution_summary.strip()
    if not summary:
        raise ReviewGateError("resolution-summary 不能为空")
    tests = require_strings(args.test_result, "test-result")
    entry["review_resolution_summary"] = summary
    entry["review_fix_test_results"] = tests
    if args.request_rereview:
        if args.request_rereview not in REREVIEW_REASONS:
            raise ReviewGateError("复审原因无效")
        policy = policy_for(entry)
        if entry.get("complexity_tier") != "strict":
            raise ReviewGateError("复审前必须把需求重新分级为 strict")
        if int(entry.get("review_rounds_started", 0)) >= policy["round_limit"]:
            raise ReviewGateError("已达到 Review 轮次上限")
        entry["review_phase"] = "review_fixes"
        entry["pending_rereview_reason"] = args.request_rereview
    else:
        entry["review_phase"] = "review_complete"
        entry["review_completed_at"] = timestamp()
    return entry


def status_payload(entry: dict[str, Any]) -> dict[str, Any]:
    started_at = entry.get("review_started_at", [])
    review_results = entry.get("review_results", [])
    first_scope = (
        review_results[0].get("scope")
        if isinstance(review_results, list)
        and review_results
        and isinstance(review_results[0], dict)
        else None
    )
    review_process = {
        "implementation_completed_at": entry.get("implementation_completed_at"),
        "first_review_started_at": started_at[0]
        if isinstance(started_at, list) and started_at
        else None,
        "complete_candidate_reviewed": first_scope == "complete_candidate",
        "all_reviewers_collected_before_fixes": entry.get(
            "all_reviewers_collected"
        )
        is True,
    }
    return {
        "requirement_id": entry.get("requirement_id"),
        "review_phase": entry.get("review_phase"),
        "report_ready": entry.get("review_phase") == "review_complete",
        "review_rounds": entry.get("review_rounds_started", 0),
        "review_process": review_process,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "start", "collect", "complete", "status"):
        command = commands.add_parser(name)
        command.add_argument("--id", required=True)
        command.add_argument("--repository", required=True)
        if name == "prepare":
            command.add_argument("--implementation-summary", required=True)
            command.add_argument("--test-result", action="append", default=[])
            command.add_argument("--candidate-file", action="append", default=[])
            command.add_argument("--rereview-reason", choices=sorted(REREVIEW_REASONS))
        elif name == "collect":
            command.add_argument("--results", required=True, type=Path)
        elif name == "complete":
            command.add_argument("--resolution-summary", required=True)
            command.add_argument("--test-result", action="append", default=[])
            command.add_argument("--request-rereview", choices=sorted(REREVIEW_REASONS))
    args = parser.parse_args()
    try:
        if args.command == "status":
            state = run_state.load_state()
            _, entry = load_entry(state["requirements"], args.id, args.repository)
            result = status_payload(entry)
        else:
            with run_state.state_lock():
                state = run_state.load_state()
                state_key, entry = load_entry(
                    state["requirements"], args.id, args.repository
                )
                if args.command == "prepare":
                    entry = prepare(entry, args)
                    entry["review_candidate_snapshot"] = candidate_snapshot(
                        entry.get("worktree_path") or entry["repository"],
                        entry["review_candidate_files"],
                    )
                elif args.command == "start":
                    verify_candidate_unchanged(entry)
                    entry = start(entry)
                elif args.command == "collect":
                    verify_candidate_unchanged(entry)
                    entry = collect(entry, read_review_results(args.results))
                else:
                    entry = complete(entry, args)
                entry["updated_at"] = timestamp()
                state["requirements"][state_key] = entry
                run_state.atomic_write(state)
                result = entry
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
