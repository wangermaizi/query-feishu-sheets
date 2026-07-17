from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skill" / "feishu-requirement-orchestrator" / "scripts" / "rank_requirements.py"
SPEC = importlib.util.spec_from_file_location("rank_requirements", SCRIPT)
assert SPEC and SPEC.loader
rank_requirements = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rank_requirements)


def requirement(requirement_id: str, priority: str, ease: int, *, eligible: bool = True):
    return {
        "id": requirement_id,
        "title": requirement_id,
        "priority": priority,
        "impact": 3,
        "urgency": 3,
        "ease": ease,
        "risk": 2,
        "eligible": eligible,
        "blocked_reasons": [] if eligible else ["缺少验收标准"],
    }


def test_priority_precedes_ease():
    result = rank_requirements.rank_requirements(
        [requirement("easy-p2", "P2", 5), requirement("hard-p1", "P1", 1)]
    )
    assert result["selected"]["id"] == "hard-p1"


def test_ease_breaks_same_priority_tie_and_blocked_is_excluded():
    result = rank_requirements.rank_requirements(
        [
            requirement("hard", "P1", 2),
            requirement("blocked", "P0", 5, eligible=False),
            requirement("easy", "P1", 5),
        ]
    )
    assert result["selected"]["id"] == "easy"
    assert [item["id"] for item in result["blocked"]] == ["blocked"]
