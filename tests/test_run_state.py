from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugin" / "feishu-codex-orchestrator" / "skills" / "feishu-requirement-orchestrator" / "scripts" / "run_state.py"
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
            "--title",
            "手动需求",
            "--description",
            "用户直接描述的需求",
            "--acceptance-criterion",
            "满足验收标准",
            "--project-name",
            "OA",
            "--repository",
            str(tmp_path),
            "--source-type",
            "manual",
            "--source-fingerprint",
            "abc123",
            "--complexity-tier",
            "fast",
            "--complexity-reason",
            "只修改两个局部文件",
            "--batch-id",
            "batch-1",
            "--rank",
            "2",
            "--proposed-status",
            "partially_done",
            "--reason",
            "已有部分实现",
            "--plain-language-summary",
            "现状：已有基础能力。影响：异常场景仍会出错。目标：补齐异常处理。",
            "--evidence",
            "src/example.ts:42",
            "--remaining-criterion",
            "补充异常路径",
        ],
    )
    assert run_state.main() == 0
    requirements = run_state.load_state()["requirements"]
    entries = [
        value
        for value in requirements.values()
        if value.get("requirement_id") == "REQ-2"
    ]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["batch_id"] == "batch-1"
    assert entry["title"] == "手动需求"
    assert entry["description"] == "用户直接描述的需求"
    assert entry["acceptance_criteria"] == ["满足验收标准"]
    assert entry["project_name"] == "OA"
    assert entry["repository"] == str(tmp_path.resolve())
    assert entry["repository_identity"] == str(tmp_path.resolve())
    assert entry["worktree_path"] == str(tmp_path.resolve())
    assert entry["repository_is_git"] is False
    assert entry["source_type"] == "manual"
    assert entry["source_fingerprint"] == "abc123"
    assert entry["complexity_tier"] == "fast"
    assert entry["complexity_reason"] == "只修改两个局部文件"
    assert entry["rank"] == 2
    assert entry["proposed_status"] == "partially_done"
    assert entry["plain_language_summary"] == "现状：已有基础能力。影响：异常场景仍会出错。目标：补齐异常处理。"
    assert entry["remaining_criteria"] == ["补充异常路径"]


def scope(identity: Path, worktree: Path):
    return {
        "repository": str(worktree),
        "repository_identity": str(identity),
        "worktree_path": str(worktree),
        "is_git": True,
    }


def active_entry(identity: Path, worktree: Path):
    return {
        "status": "in_progress",
        "title": "Existing",
        "repository": str(worktree),
        "repository_identity": str(identity),
        "worktree_path": str(worktree),
    }


def test_different_repository_does_not_block_parallel_work(tmp_path):
    current = scope(tmp_path / "repo-a" / ".git", tmp_path / "repo-a")
    state = {
        "REQ-B": active_entry(tmp_path / "repo-b" / ".git", tmp_path / "repo-b")
    }

    result = run_state.scope_conflicts(current, state)

    assert result["decision"] == "clear"
    assert [item["id"] for item in result["other_repositories"]] == ["REQ-B"]


def test_same_worktree_blocks_parallel_work(tmp_path):
    identity = tmp_path / "repo" / ".git"
    worktree = tmp_path / "repo"
    current = scope(identity, worktree)
    state = {"REQ-OLD": active_entry(identity, worktree)}

    result = run_state.scope_conflicts(current, state)

    assert result["decision"] == "blocked_same_worktree"


def test_same_repository_other_worktree_requires_confirmation(tmp_path):
    identity = tmp_path / "repo" / ".git"
    current = scope(identity, tmp_path / "worktree-a")
    state = {"REQ-OLD": active_entry(identity, tmp_path / "worktree-b")}

    pending = run_state.scope_conflicts(current, state)
    confirmed = run_state.scope_conflicts(
        current, state, allow_parallel_worktree=True
    )

    assert pending["decision"] == "parallel_worktree_confirmation_required"
    assert confirmed["decision"] == "clear"


def test_legacy_active_entry_requires_scope_attachment(tmp_path):
    current = scope(tmp_path / "repo" / ".git", tmp_path / "repo")
    state = {"31": {"status": "in_progress", "title": "Legacy"}}

    result = run_state.scope_conflicts(current, state)

    assert result["decision"] == "legacy_scope_confirmation_required"
    assert [item["id"] for item in result["legacy_unscoped"]] == ["31"]


def test_same_requirement_id_is_namespaced_by_repository(tmp_path):
    first = run_state.scoped_state_key("31", str(tmp_path / "repo-a" / ".git"))
    second = run_state.scoped_state_key("31", str(tmp_path / "repo-b" / ".git"))

    assert first != second
    assert first.endswith(":31")
    assert second.endswith(":31")


def test_attach_scope_migrates_legacy_state_key(tmp_path, monkeypatch):
    monkeypatch.setenv("FEISHU_ORCHESTRATOR_CONFIG_DIR", str(tmp_path / "config"))
    repository = tmp_path / "repository"
    repository.mkdir()
    run_state.atomic_write(
        {"requirements": {"31": {"status": "in_progress", "title": "Legacy"}}}
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_state.py",
            "attach-scope",
            "--id",
            "31",
            "--repository",
            str(repository),
        ],
    )

    assert run_state.main() == 0
    requirements = run_state.load_state()["requirements"]
    assert "31" not in requirements
    entry = next(iter(requirements.values()))
    assert entry["requirement_id"] == "31"
    assert entry["worktree_path"] == str(repository.resolve())


def test_mark_rejects_another_active_requirement_in_same_worktree(
    tmp_path, monkeypatch
):
    config = tmp_path / "config"
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setenv("FEISHU_ORCHESTRATOR_CONFIG_DIR", str(config))
    scope_value = run_state.resolve_scope(repository)
    old_key = run_state.scoped_state_key("OLD", scope_value["repository_identity"])
    run_state.atomic_write(
        {
            "requirements": {
                old_key: {
                    "requirement_id": "OLD",
                    "status": "in_progress",
                    "title": "Existing",
                    "repository": scope_value["repository"],
                    "repository_identity": scope_value["repository_identity"],
                    "worktree_path": scope_value["worktree_path"],
                    "repository_is_git": scope_value["is_git"],
                }
            }
        }
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_state.py",
            "mark",
            "--id",
            "NEW",
            "--status",
            "awaiting_branch_choice",
            "--repository",
            str(repository),
        ],
    )

    assert run_state.main() == 1
    assert len(run_state.load_state()["requirements"]) == 1


def test_mark_allows_active_requirements_in_different_repositories(
    tmp_path, monkeypatch
):
    config = tmp_path / "config"
    first_repository = tmp_path / "repository-a"
    second_repository = tmp_path / "repository-b"
    first_repository.mkdir()
    second_repository.mkdir()
    monkeypatch.setenv("FEISHU_ORCHESTRATOR_CONFIG_DIR", str(config))

    for requirement_id, repository in (
        ("REQ-A", first_repository),
        ("REQ-B", second_repository),
    ):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "run_state.py",
                "mark",
                "--id",
                requirement_id,
                "--status",
                "in_progress",
                "--repository",
                str(repository),
            ],
        )
        assert run_state.main() == 0

    entries = run_state.load_state()["requirements"].values()
    assert {entry["requirement_id"] for entry in entries} == {"REQ-A", "REQ-B"}


def test_same_requirement_id_does_not_overwrite_different_repository(
    tmp_path, monkeypatch
):
    config = tmp_path / "config"
    first_repository = tmp_path / "repository-a"
    second_repository = tmp_path / "repository-b"
    first_repository.mkdir()
    second_repository.mkdir()
    monkeypatch.setenv("FEISHU_ORCHESTRATOR_CONFIG_DIR", str(config))

    for repository in (first_repository, second_repository):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "run_state.py",
                "mark",
                "--id",
                "31",
                "--status",
                "approved",
                "--repository",
                str(repository),
            ],
        )
        assert run_state.main() == 0

    requirements = run_state.load_state()["requirements"]
    assert len(requirements) == 2
    assert all(entry["requirement_id"] == "31" for entry in requirements.values())
