from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / ".agents"
    / "skills"
    / "release-query-feishu-sheets"
    / "scripts"
    / "extract_release_notes.py"
)
SPEC = importlib.util.spec_from_file_location("extract_release_notes", SCRIPT)
assert SPEC and SPEC.loader
extract_release_notes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extract_release_notes)


def changelog():
    return """# 更新日志

## [v0.3.1] - 2026-07-21

### 改进

- 精简群卡片。
- Release 带上中文更新日志。

## [v0.3.0] - 2026-07-21

### 新增

- 新增手动需求模式。
"""


def test_extracts_only_requested_version_body():
    notes = extract_release_notes.extract_release_notes(changelog(), "v0.3.1")

    assert notes.startswith("### 改进")
    assert "精简群卡片" in notes
    assert "## [v0.3.1]" not in notes
    assert "v0.3.0" not in notes


def test_rejects_missing_version():
    with pytest.raises(extract_release_notes.ReleaseNotesError, match="缺少 v0.4.0"):
        extract_release_notes.extract_release_notes(changelog(), "v0.4.0")


def test_rejects_duplicate_version_sections():
    duplicate = changelog() + "\n## [v0.3.1] - 2026-07-22\n\n- duplicate\n"

    with pytest.raises(extract_release_notes.ReleaseNotesError, match="重复"):
        extract_release_notes.extract_release_notes(duplicate, "v0.3.1")


def test_rejects_empty_version_section():
    value = "## [v0.3.1] - 2026-07-21\n\n## [v0.3.0] - 2026-07-20\n- old\n"

    with pytest.raises(extract_release_notes.ReleaseNotesError, match="内容为空"):
        extract_release_notes.extract_release_notes(value, "v0.3.1")
