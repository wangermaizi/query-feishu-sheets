from __future__ import annotations

import importlib.util
import json
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
    assert {"needs_confirmation", "completed", "obsolete", "duplicate"} <= run_state.VALID_STATUSES
