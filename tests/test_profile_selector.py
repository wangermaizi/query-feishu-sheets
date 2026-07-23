from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugin" / "feishu-codex-orchestrator" / "skills" / "feishu-requirement-orchestrator" / "scripts" / "profile_selector.py"
SPEC = importlib.util.spec_from_file_location("profile_selector", SCRIPT)
assert SPEC and SPEC.loader
profile_selector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profile_selector)


PROFILES = {
    "product-requirements": {
        "display_name": "产品研发需求表",
        "aliases": ["研发需求", "产品需求"],
        "description": "产品和研发团队待开发需求",
    },
    "support-requirements": {
        "display_name": "客户支持需求表",
        "aliases": ["客服需求"],
        "description": "客户反馈和支持需求",
    },
}


def test_resolve_ignores_generic_table_suffix():
    result = profile_selector.resolve_profiles("产品研发", PROFILES)
    assert [item["profile_id"] for item in result["exact_matches"]] == [
        "product-requirements"
    ]


def test_resolve_returns_multiple_approximate_candidates():
    result = profile_selector.resolve_profiles("需求", PROFILES)
    assert {item["profile_id"] for item in result["approximate_matches"]} == set(PROFILES)


def test_switch_persists_exact_profile_id(tmp_path, monkeypatch):
    monkeypatch.setenv("FEISHU_ORCHESTRATOR_CONFIG_DIR", str(tmp_path))
    (tmp_path / "profiles.json").write_text(
        json.dumps({"profiles": PROFILES}, ensure_ascii=False), encoding="utf-8"
    )
    settings = {"delivery": {"chat_id": "oc_test"}, "profile": "support-requirements"}
    profile_selector.atomic_write(tmp_path / "orchestrator.json", settings)
    monkeypatch.setattr(
        sys,
        "argv",
        ["profile_selector.py", "switch", "--profile-id", "product-requirements"],
    )
    assert profile_selector.main() == 0
    saved = json.loads((tmp_path / "orchestrator.json").read_text(encoding="utf-8"))
    assert saved["profile"] == "product-requirements"
    assert saved["delivery"] == settings["delivery"]
