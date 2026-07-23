#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["tzdata>=2025.2"]
# ///
"""Generate and validate requirement branch names."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import unicodedata
from zoneinfo import ZoneInfo


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


TYPES = {"feature", "fix", "refactor"}
DATE_RE = re.compile(r"^\d{8}$")
HYPHENS_RE = re.compile(r"-+")


class BranchNameError(ValueError):
    pass


def sanitize_summary(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    characters: list[str] = []
    for character in normalized:
        if character.isalnum():
            characters.append(character)
        elif character.isspace() or character in {"-", "_"}:
            characters.append("-")
    summary = HYPHENS_RE.sub("-", "".join(characters)).strip("-")
    if not summary:
        raise BranchNameError("分支摘要清理后为空")
    if len(summary) > 60:
        raise BranchNameError("分支摘要不能超过 60 个字符")
    return summary


def parse_day(value: str | None) -> dt.date:
    if value is None:
        return dt.datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if not DATE_RE.fullmatch(value):
        raise BranchNameError("日期必须使用 YYYYMMDD 格式")
    try:
        return dt.datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise BranchNameError("日期不是有效日历日期") from exc


def propose(change_type: str, summary: str, day: str | None = None) -> str:
    if change_type not in TYPES:
        raise BranchNameError("分支类型只能为 feature、fix 或 refactor")
    date = parse_day(day).strftime("%Y%m%d")
    return f"{change_type}/{date}/{sanitize_summary(summary)}"


def validate(name: str) -> str:
    parts = name.split("/")
    if len(parts) != 3:
        raise BranchNameError("分支名必须包含 type、YYYYMMDD、summary 三段")
    expected = propose(parts[0], parts[2], parts[1])
    if name != expected:
        raise BranchNameError(f"分支名不符合规范，建议使用: {expected}")
    return name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    propose_parser = commands.add_parser("propose")
    propose_parser.add_argument("--type", required=True, choices=sorted(TYPES))
    propose_parser.add_argument("--summary", required=True)
    propose_parser.add_argument("--date")
    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        branch = (
            propose(args.type, args.summary, args.date)
            if args.command == "propose"
            else validate(args.name)
        )
        json.dump({"branch": branch}, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    except BranchNameError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
