from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_skill.py"
SPEC = importlib.util.spec_from_file_location("validate_skill", SCRIPT)
assert SPEC and SPEC.loader
validate_skill = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_skill)


@pytest.mark.parametrize(
    "skill",
    [
        ROOT / "skill" / "feishu-requirement-orchestrator",
        ROOT / ".agents" / "skills" / "release-query-feishu-sheets",
    ],
)
def test_repository_skills_are_valid(skill):
    validate_skill.validate(skill)


def test_rejects_unexpected_frontmatter_key(tmp_path):
    skill = tmp_path / "sample-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: sample-skill\n"
        "description: A valid description.\n"
        "version: 1\n"
        "---\n\n"
        "# Instructions\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="only name and description"):
        validate_skill.validate(skill)
