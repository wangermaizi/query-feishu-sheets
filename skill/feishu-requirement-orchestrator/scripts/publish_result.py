#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["tzdata>=2025.2"]
# ///
"""Preview or publish a reviewed implementation report to an authorized Feishu group."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import query_sheet


class ReportError(ValueError):
    pass


def config_dir() -> Path:
    return Path(
        os.environ.get(
            "FEISHU_ORCHESTRATOR_CONFIG_DIR",
            Path.home() / ".codex" / "feishu-requirement-orchestrator",
        )
    ).expanduser()


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"无法读取{label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReportError(f"{label}必须是 JSON 对象")
    return payload


def load_settings() -> dict[str, Any]:
    settings = read_json(config_dir() / "orchestrator.json", "运行配置")
    delivery = settings.get("delivery")
    if not isinstance(delivery, dict):
        raise ReportError("运行配置缺少 delivery")
    for key in ("credential", "chat_id", "chat_name"):
        if not isinstance(delivery.get(key), str) or not delivery[key].strip():
            raise ReportError(f"delivery.{key} 不能为空")
    if delivery.get("auto_publish") is not True:
        raise ReportError("固定群未授权自动发送：delivery.auto_publish 必须为 true")
    if not delivery["chat_id"].startswith("oc_"):
        raise ReportError("delivery.chat_id 格式无效")
    return settings


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    required_strings = (
        "requirement_id",
        "project_name",
        "title",
        "status",
        "selection_reason",
        "plain_language_summary",
        "complexity_tier",
        "complexity_reason",
        "repository",
        "branch",
        "next_action",
        "completed_at",
    )
    for key in required_strings:
        if not isinstance(report.get(key), str) or not report[key].strip():
            raise ReportError(f"报告字段 {key} 不能为空")
    if report["status"] not in {"completed", "blocked", "failed"}:
        raise ReportError("status 必须为 completed、blocked 或 failed")
    if report["complexity_tier"] not in {"fast", "standard", "strict"}:
        raise ReportError("complexity_tier 必须为 fast、standard 或 strict")
    review_rounds = report.get("review_rounds")
    if not isinstance(review_rounds, int) or isinstance(review_rounds, bool):
        raise ReportError("review_rounds 必须为整数")
    allowed_rounds = {1} if report["complexity_tier"] != "strict" else {1, 2}
    if review_rounds not in allowed_rounds:
        raise ReportError(
            f"{report['complexity_tier']} 级 review_rounds 必须为 "
            + " 或 ".join(str(value) for value in sorted(allowed_rounds))
        )
    for key in ("changes", "tests", "reviews", "residual_risks"):
        if not isinstance(report.get(key), list):
            raise ReportError(f"报告字段 {key} 必须为数组")
    expected_reviews = 1 if report["complexity_tier"] == "fast" else 3
    if len(report["reviews"]) != expected_reviews:
        raise ReportError(
            f"{report['complexity_tier']} 级报告必须包含 {expected_reviews} 个 Reviewer 的结果"
        )
    necessity = report.get("necessity_assessment")
    if not isinstance(necessity, dict):
        raise ReportError("报告必须包含 necessity_assessment")
    if necessity.get("status") not in {"not_started", "partially_done"}:
        raise ReportError("实施报告的必要性状态必须为 not_started 或 partially_done")
    evidence = necessity.get("evidence")
    if not isinstance(evidence, list) or not evidence or not all(
        isinstance(value, str) and value.strip() for value in evidence
    ):
        raise ReportError("necessity_assessment.evidence 必须为非空字符串数组")
    review_process = report.get("review_process")
    if not isinstance(review_process, dict):
        raise ReportError("报告必须包含 review_process")
    for key in ("implementation_completed_at", "first_review_started_at"):
        value = review_process.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ReportError(f"review_process.{key} 不能为空")
    for key in ("complete_candidate_reviewed", "all_reviewers_collected_before_fixes"):
        if review_process.get(key) is not True:
            raise ReportError(f"review_process.{key} 必须为 true")
    try:
        implementation_completed_at = dt.datetime.fromisoformat(
            review_process["implementation_completed_at"]
        )
        first_review_started_at = dt.datetime.fromisoformat(
            review_process["first_review_started_at"]
        )
    except ValueError as exc:
        raise ReportError("review_process 时间必须为 ISO 8601") from exc
    if (
        implementation_completed_at.utcoffset() is None
        or first_review_started_at.utcoffset() is None
    ):
        raise ReportError("review_process 时间必须包含时区")
    if implementation_completed_at > first_review_started_at:
        raise ReportError("Review 不得早于完整实现完成时间")
    serialized = json.dumps(report, ensure_ascii=False).lower()
    forbidden = ("app_secret", "tenant_access_token", "authorization: bearer")
    if any(marker in serialized for marker in forbidden):
        raise ReportError("报告疑似包含敏感凭证字段")
    return report


def report_hash(report: dict[str, Any], chat_id: str) -> str:
    canonical = json.dumps(
        {"chat_id": chat_id, "report": report},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def text(value: Any, limit: int = 1800) -> str:
    rendered = str(value).strip() or "无"
    return rendered if len(rendered) <= limit else rendered[: limit - 1] + "…"


def bullet_list(values: list[Any]) -> str:
    if not values:
        return "- 无"
    lines = []
    for value in values:
        if isinstance(value, dict):
            value = " | ".join(f"{key}: {item}" for key, item in value.items())
        lines.append(f"- {text(value, 600)}")
    return "\n".join(lines)


def build_card(report: dict[str, Any]) -> dict[str, Any]:
    status_template = {"completed": "green", "blocked": "orange", "failed": "red"}
    card_title = f"【{report['project_name']}】{report['title']}"
    elements: list[dict[str, Any]] = []
    sections = [
        (
            "执行信息",
            f"**项目：** {text(report['project_name'])}\n"
            f"**需求 ID：** {text(report['requirement_id'])}\n"
            f"**状态：** {text(report['status'])}\n"
            f"**仓库：** {text(report['repository'])}\n"
            f"**分支：** {text(report['branch'])}\n"
            "**Git 操作：** 未 commit、未 push、未 merge、未发布",
        ),
        ("需求说明", text(report["plain_language_summary"])),
        ("修改内容", bullet_list(report["changes"])),
        ("待确认", text(report["next_action"])),
    ]
    for index, (heading, content) in enumerate(sections):
        if index:
            elements.append({"tag": "hr"})
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**{heading}**\n{content}"},
            }
        )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": status_template[report["status"]],
            "title": {"tag": "plain_text", "content": text(card_title, 80)},
        },
        "elements": elements,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("preview", "publish"):
        command = commands.add_parser(name)
        command.add_argument("--report", required=True, type=Path)
        if name == "publish":
            command.add_argument("--expected-hash", required=True)
            command.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    try:
        settings = load_settings()
        delivery = settings["delivery"]
        report = validate_report(read_json(args.report, "结果报告"))
        digest = report_hash(report, delivery["chat_id"])
        card = build_card(report)
        result: dict[str, Any] = {
            "chat_id": delivery["chat_id"],
            "chat_name": delivery["chat_name"],
            "result_hash": digest,
            "card": card,
        }
        if args.command == "publish":
            if not args.confirm:
                raise ReportError("publish 必须显式传入 --confirm")
            if args.expected_hash != digest:
                raise ReportError("报告或目标群已变化，result_hash 不匹配，请重新预览")
            access_token = query_sheet.get_access_token(delivery["credential"])
            result["message_id"] = query_sheet.send_card(
                access_token, delivery["chat_id"], card
            )
            result["published"] = True
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    except (ReportError, query_sheet.FeishuSheetError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
