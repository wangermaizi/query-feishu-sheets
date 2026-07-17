#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Read and atomically update the local requirement-processing ledger."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


VALID_STATUSES = {
    "discovered",
    "awaiting_analysis_confirmation",
    "approved",
    "needs_confirmation",
    "awaiting_branch_choice",
    "in_progress",
    "report_failed",
    "reported",
    "completed",
    "obsolete",
    "duplicate",
    "skipped",
}
NECESSITY_STATUSES = {
    "not_started",
    "partially_done",
    "completed",
    "obsolete",
    "duplicate",
    "needs_confirmation",
}


def config_dir() -> Path:
    return Path(
        os.environ.get(
            "FEISHU_ORCHESTRATOR_CONFIG_DIR",
            Path.home() / ".codex" / "feishu-requirement-orchestrator",
        )
    ).expanduser()


def state_path() -> Path:
    return config_dir() / "state.json"


def load_state() -> dict[str, Any]:
    try:
        payload = json.loads(state_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"requirements": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("requirements"), dict):
        raise ValueError("state.json 必须包含 requirements 对象")
    return payload


def atomic_write(payload: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=".state.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    mark = commands.add_parser("mark")
    mark.add_argument("--id", required=True)
    mark.add_argument("--status", required=True, choices=sorted(VALID_STATUSES))
    mark.add_argument("--title")
    mark.add_argument("--reason")
    mark.add_argument("--evidence", action="append", default=[])
    mark.add_argument("--batch-id")
    mark.add_argument("--rank", type=int)
    mark.add_argument("--proposed-status", choices=sorted(NECESSITY_STATUSES))
    mark.add_argument("--remaining-criterion", action="append", default=[])
    args = parser.parse_args()
    try:
        state = load_state()
        if args.command == "mark":
            previous = state["requirements"].get(args.id, {})
            entry = dict(previous) if isinstance(previous, dict) else {}
            entry.update(
                {
                    "status": args.status,
                    "updated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                }
            )
            if args.title:
                entry["title"] = args.title
            if args.reason:
                entry["reason"] = args.reason
            if args.evidence:
                entry["evidence"] = args.evidence
            if args.batch_id:
                entry["batch_id"] = args.batch_id
            if args.rank is not None:
                if args.rank < 1:
                    raise ValueError("rank 必须大于等于 1")
                entry["rank"] = args.rank
            if args.proposed_status:
                entry["proposed_status"] = args.proposed_status
            if args.remaining_criterion:
                entry["remaining_criteria"] = args.remaining_criterion
            state["requirements"][args.id] = entry
            atomic_write(state)
        json.dump(state, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
