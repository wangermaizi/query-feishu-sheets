from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skill" / "feishu-requirement-orchestrator" / "scripts" / "query_sheet.py"
SPEC = importlib.util.spec_from_file_location("query_sheet_filter_policy", SCRIPT)
assert SPEC and SPEC.loader
query_sheet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(query_sheet)


def profile(**overrides):
    value = {
        "credential": "test-app",
        "document_url": "https://example.feishu.cn/base/token",
        "filters": [],
        "output_columns": [],
    }
    value.update(overrides)
    return query_sheet.validate_profile(value)


def test_unfiltered_query_requires_explicit_authorization():
    with pytest.raises(query_sheet.FeishuSheetError, match="请先询问用户如何过滤"):
        query_sheet.validate_filter_policy(profile())


def test_explicit_unfiltered_authorization_is_accepted():
    query_sheet.validate_filter_policy(profile(allow_unfiltered=True))


def test_configured_filter_is_accepted_without_unfiltered_authorization():
    query_sheet.validate_filter_policy(
        profile(filters=[{"column": "状态", "operator": "equals", "value": "待处理"}])
    )


def test_allow_unfiltered_must_be_boolean():
    with pytest.raises(query_sheet.FeishuSheetError, match="必须为布尔值"):
        profile(allow_unfiltered="yes")
