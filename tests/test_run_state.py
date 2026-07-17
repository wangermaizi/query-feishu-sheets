from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skill" / "feishu-requirement-orchestrator" / "scripts" / "run_state.py"
SPEC = importlib.util.spec_from_file_location("run_state", SCRIPT)
assert SPEC and SPEC.loader
run_state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_state)


def test_atomic_state_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("FEISHU_ORCHESTRATOR_CONFIG_DIR", str(tmp_path))
    payload = {
        "requirements": {
            "REQ-1": {"status": "awaiting_branch_choice", "title": "Test"}
        }
    }
    run_state.atomic_write(payload)
    assert run_state.load_state() == payload
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8")) == payload


def test_necessity_terminal_statuses_are_supported():
    assert {
        "awaiting_analysis_confirmation",
        "approved",
        "needs_confirmation",
        "completed",
        "obsolete",
        "duplicate",
    } <= run_state.VALID_STATUSES
    assert {"not_started", "partially_done", "needs_confirmation"} <= run_state.NECESSITY_STATUSES


def test_batch_confirmation_metadata_is_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("FEISHU_ORCHESTRATOR_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_state.py",
            "mark",
            "--id",
            "REQ-2",
            "--status",
            "awaiting_analysis_confirmation",
            "--batch-id",
            "batch-1",
            "--rank",
            "2",
            "--proposed-status",
            "partially_done",
            "--reason",
            "已有部分实现",
            "--evidence",
            "src/example.ts:42",
            "--remaining-criterion",
            "补充异常路径",
        ],
    )
    assert run_state.main() == 0
    entry = run_state.load_state()["requirements"]["REQ-2"]
    assert entry["batch_id"] == "batch-1"
    assert entry["rank"] == 2
    assert entry["proposed_status"] == "partially_done"
    assert entry["remaining_criteria"] == ["补充异常路径"]
