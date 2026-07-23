from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_plugin.py"
SPEC = importlib.util.spec_from_file_location("validate_plugin", SCRIPT)
assert SPEC and SPEC.loader
validate_plugin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_plugin)


def test_repository_plugin_is_valid():
    validate_plugin.validate(ROOT / "plugin" / "feishu-codex-orchestrator")


def test_plugin_rejects_empty_mcp_servers(tmp_path):
    plugin = tmp_path / "sample-plugin"
    (plugin / ".codex-plugin").mkdir(parents=True)
    (plugin / "skills" / "sample-skill").mkdir(parents=True)
    (plugin / "skills" / "sample-skill" / "SKILL.md").write_text("", encoding="utf-8")
    (plugin / ".mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    (plugin / ".codex-plugin" / "plugin.json").write_text(
        """{
          "name": "sample-plugin",
          "version": "1.0.0",
          "description": "sample",
          "author": {"name": "test"},
          "skills": "./skills/",
          "mcpServers": "./.mcp.json",
          "interface": {
            "displayName": "Sample",
            "shortDescription": "Sample plugin",
            "longDescription": "Sample plugin used for tests.",
            "developerName": "test",
            "category": "Productivity",
            "defaultPrompt": ["Test sample plugin."]
          }
        }""",
        encoding="utf-8",
    )

    with pytest.raises(validate_plugin.PluginValidationError, match="at least one server"):
        validate_plugin.validate(plugin)
