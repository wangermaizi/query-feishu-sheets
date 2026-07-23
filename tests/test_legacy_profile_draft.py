from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "plugin"
    / "feishu-codex-orchestrator"
    / "skills"
    / "feishu-requirement-orchestrator"
    / "scripts"
    / "legacy_profile_draft.py"
)
SPEC = importlib.util.spec_from_file_location("legacy_profile_draft", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_generates_sanitized_draft_and_only_reports_missing_routes():
    result = MODULE.generate_draft(
        {
            "chixiao": {
                "display_name": "赤霄需求",
                "credential": "chixiao-bot",
                "document_url": "https://example.feishu.cn/sheets/token",
                "default_sheet": "需求池",
                "filters": [{"column": "状态", "operator": "equals", "value": "待处理"}],
                "output_columns": ["模块", "需求描述"],
                "delivery": {
                    "chat_id": "oc_xxx",
                    "chat_name": "赤霄群",
                    "format": "interactive_card",
                    "access_token": "must-not-leak",
                },
                "app_secret": "must-not-leak",
            }
        }
    )

    profile = result["profiles_draft"]["profiles"]["chixiao"]
    assert profile["document_url"].endswith("/token")
    assert profile["filters"][0]["value"] == "待处理"
    assert profile["delivery"]["chat_id"] == "oc_xxx"
    assert "app_secret" not in profile
    assert "access_token" not in profile["delivery"]
    assert result["credential_references"] == ["chixiao-bot"]
    assert result["missing_fields"] == {
        "chixiao": ["project_name", "repositories"]
    }


def test_reuses_existing_project_and_repository_values():
    result = MODULE.generate_draft(
        {
            "known": {
                "default_project_name": "已知项目",
                "default_repository": "D:\\workspace\\known",
            }
        }
    )

    route = result["orchestrator_gateway_draft"]["profile_routes"]["known"]
    assert route["project_name"] == "已知项目"
    assert route["repositories"][0]["path"] == "D:\\workspace\\known"
    assert result["missing_fields"] == {}


def test_discovers_project_level_repository_routes(tmp_path):
    projects = tmp_path / "projects"
    chixiao = projects / "chxo"
    yqu = projects / "yqu"
    chixiao.mkdir(parents=True)
    yqu.mkdir()
    (chixiao / "orchestrator.json").write_text(
        """{
          "default_project_name": "赤霄",
          "default_repository": "D:\\\\workspace\\\\chxo"
        }""",
        encoding="utf-8",
    )
    (yqu / "orchestrator.json").write_text(
        """{
          "default_project_name": "悦趣圈",
          "repository_routing": {
            "routes": [
              {"label": "悦趣圈前端", "path": "D:\\\\workspace\\\\yqu"},
              {"label": "悦趣圈后端", "path": "D:\\\\workspace\\\\yqu-api"}
            ]
          }
        }""",
        encoding="utf-8",
    )

    routes, missing = MODULE.load_project_routes(projects)

    assert routes["chxo"]["project_name"] == "赤霄"
    assert routes["chxo"]["repositories"][0]["path"] == "D:\\workspace\\chxo"
    assert [item["display_name"] for item in routes["yqu"]["repositories"]] == [
        "悦趣圈前端",
        "悦趣圈后端",
    ]
    assert missing == {}
