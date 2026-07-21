#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Read and concurrency-safely update the scoped requirement-processing ledger."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


VALID_STATUSES = {
    "discovered",
    "awaiting_analysis_confirmation",
    "approved",
    "needs_confirmation",
    "awaiting_branch_choice",
    "in_progress",
    "report_failed",
    "reported",
    "completed",
    "obsolete",
    "duplicate",
    "skipped",
}
NECESSITY_STATUSES = {
    "not_started",
    "partially_done",
    "completed",
    "obsolete",
    "duplicate",
    "needs_confirmation",
}
WORKSPACE_ACTIVE_STATUSES = {
    "awaiting_branch_choice",
    "in_progress",
    "report_failed",
}


def config_dir() -> Path:
    return Path(
        os.environ.get(
            "FEISHU_ORCHESTRATOR_CONFIG_DIR",
            Path.home() / ".codex" / "feishu-requirement-orchestrator",
        )
    ).expanduser()


def state_path() -> Path:
    return config_dir() / "state.json"


@contextlib.contextmanager
def state_lock():
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".state.lock"
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def canonical_path(value: str | Path) -> str:
    return os.path.normcase(str(Path(value).expanduser().resolve()))


def resolve_scope(repository: str | Path) -> dict[str, Any]:
    path = Path(repository).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise ValueError("repository 必须是已存在的绝对目录")
    resolved = path.resolve()
    try:
        worktree_result = subprocess.run(
            ["git", "-C", str(resolved), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        worktree = Path(worktree_result.stdout.strip()).resolve()
        common_result = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "--git-common-dir"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        common = Path(common_result.stdout.strip())
        if not common.is_absolute():
            common = worktree / common
        identity = common.resolve()
        is_git = True
    except (OSError, subprocess.CalledProcessError):
        worktree = resolved
        identity = resolved
        is_git = False
    return {
        "repository": str(resolved),
        "repository_identity": str(identity),
        "worktree_path": str(worktree),
        "is_git": is_git,
    }


def entry_scope(entry: dict[str, Any]) -> dict[str, Any] | None:
    identity = entry.get("repository_identity")
    worktree = entry.get("worktree_path")
    if not isinstance(identity, str) or not identity.strip():
        return None
    if not isinstance(worktree, str) or not worktree.strip():
        return None
    return {
        "repository_identity": identity,
        "worktree_path": worktree,
    }


def entry_requirement_id(state_key: str, entry: dict[str, Any]) -> str:
    value = entry.get("requirement_id")
    return value if isinstance(value, str) and value.strip() else state_key


def scoped_state_key(requirement_id: str, repository_identity: str) -> str:
    digest = hashlib.sha256(
        canonical_path(repository_identity).encode("utf-8")
    ).hexdigest()[:12]
    return f"{digest}:{requirement_id}"


def find_state_key(
    requirements: dict[str, Any],
    requirement_id: str,
    repository_identity: str | None = None,
) -> str | None:
    if repository_identity:
        expected = scoped_state_key(requirement_id, repository_identity)
        if expected in requirements:
            return expected
    matches = [
        state_key
        for state_key, entry in requirements.items()
        if isinstance(entry, dict)
        and entry_requirement_id(state_key, entry) == requirement_id
        and (
            repository_identity is None
            or (
                entry_scope(entry) is not None
                and canonical_path(entry["repository_identity"])
                == canonical_path(repository_identity)
            )
        )
    ]
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(f"需求 ID {requirement_id} 存在于多个仓库，请提供 repository")
    return matches[0]


def scope_conflicts(
    current: dict[str, Any],
    requirements: dict[str, Any],
    *,
    exclude_id: str | None = None,
    allow_parallel_worktree: bool = False,
) -> dict[str, Any]:
    same_worktree: list[dict[str, Any]] = []
    parallel_worktrees: list[dict[str, Any]] = []
    other_repositories: list[dict[str, Any]] = []
    legacy_unscoped: list[dict[str, Any]] = []
    current_identity = canonical_path(current["repository_identity"])
    current_worktree = canonical_path(current["worktree_path"])
    for state_key, raw_entry in requirements.items():
        if not isinstance(raw_entry, dict):
            continue
        requirement_id = entry_requirement_id(state_key, raw_entry)
        if state_key == exclude_id or requirement_id == exclude_id:
            continue
        if raw_entry.get("status") not in WORKSPACE_ACTIVE_STATUSES:
            continue
        summary = {
            "id": requirement_id,
            "state_key": state_key,
            "status": raw_entry.get("status"),
            "title": raw_entry.get("title"),
            "project_name": raw_entry.get("project_name"),
            "repository": raw_entry.get("repository"),
            "worktree_path": raw_entry.get("worktree_path"),
        }
        scope = entry_scope(raw_entry)
        if scope is None:
            legacy_unscoped.append(summary)
            continue
        identity = canonical_path(scope["repository_identity"])
        worktree = canonical_path(scope["worktree_path"])
        if identity != current_identity:
            other_repositories.append(summary)
        elif worktree == current_worktree:
            same_worktree.append(summary)
        else:
            parallel_worktrees.append(summary)
    if same_worktree:
        decision = "blocked_same_worktree"
    elif legacy_unscoped:
        decision = "legacy_scope_confirmation_required"
    elif parallel_worktrees and not allow_parallel_worktree:
        decision = "parallel_worktree_confirmation_required"
    else:
        decision = "clear"
    return {
        "decision": decision,
        "current_scope": current,
        "same_worktree": same_worktree,
        "parallel_worktrees": parallel_worktrees,
        "other_repositories": other_repositories,
        "legacy_unscoped": legacy_unscoped,
    }


def load_state() -> dict[str, Any]:
    try:
        payload = json.loads(state_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"requirements": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("requirements"), dict):
        raise ValueError("state.json 必须包含 requirements 对象")
    return payload


def atomic_write(payload: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=".state.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def apply_scope(entry: dict[str, Any], scope: dict[str, Any]) -> None:
    entry.update(
        {
            "repository": scope["repository"],
            "repository_identity": scope["repository_identity"],
            "worktree_path": scope["worktree_path"],
            "repository_is_git": scope["is_git"],
        }
    )


def ensure_scope_available(
    state_key: str,
    entry: dict[str, Any],
    requirements: dict[str, Any],
    *,
    allow_parallel_worktree: bool,
) -> None:
    scope = entry_scope(entry)
    if scope is None:
        raise ValueError("活动状态必须提供有效 repository 以建立仓库与 worktree 范围")
    current = {
        "repository": entry.get("repository"),
        "repository_identity": scope["repository_identity"],
        "worktree_path": scope["worktree_path"],
        "is_git": entry.get("repository_is_git", True),
    }
    result = scope_conflicts(
        current,
        requirements,
        exclude_id=state_key,
        allow_parallel_worktree=allow_parallel_worktree,
    )
    decision = result["decision"]
    if decision == "blocked_same_worktree":
        ids = ", ".join(item["id"] for item in result["same_worktree"])
        raise ValueError(f"同一 worktree 已有活动需求: {ids}")
    if decision == "parallel_worktree_confirmation_required":
        ids = ", ".join(item["id"] for item in result["parallel_worktrees"])
        raise ValueError(
            f"同一仓库的其他 worktree 已有活动需求: {ids}；用户确认后传入 --allow-parallel-worktree"
        )
    if decision == "legacy_scope_confirmation_required":
        ids = ", ".join(item["id"] for item in result["legacy_unscoped"])
        raise ValueError(
            f"旧活动需求缺少仓库范围: {ids}；先用 attach-scope 关联仓库，不要将其标记为 skipped"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    check_scope = commands.add_parser("check-scope")
    check_scope.add_argument("--repository", required=True)
    check_scope.add_argument("--exclude-id")
    check_scope.add_argument("--allow-parallel-worktree", action="store_true")
    attach_scope = commands.add_parser("attach-scope")
    attach_scope.add_argument("--id", required=True)
    attach_scope.add_argument("--repository", required=True)
    mark = commands.add_parser("mark")
    mark.add_argument("--id", required=True)
    mark.add_argument("--status", required=True, choices=sorted(VALID_STATUSES))
    mark.add_argument("--title")
    mark.add_argument("--description")
    mark.add_argument("--acceptance-criterion", action="append", default=[])
    mark.add_argument("--project-name")
    mark.add_argument("--repository")
    mark.add_argument("--allow-parallel-worktree", action="store_true")
    mark.add_argument("--source-type", choices=("manual", "sheets", "bitable"))
    mark.add_argument("--source-fingerprint")
    mark.add_argument("--complexity-tier", choices=("fast", "standard", "strict"))
    mark.add_argument("--complexity-reason")
    mark.add_argument("--reason")
    mark.add_argument("--plain-language-summary")
    mark.add_argument("--evidence", action="append", default=[])
    mark.add_argument("--batch-id")
    mark.add_argument("--rank", type=int)
    mark.add_argument("--proposed-status", choices=sorted(NECESSITY_STATUSES))
    mark.add_argument("--remaining-criterion", action="append", default=[])
    args = parser.parse_args()
    try:
        if args.command == "list":
            result = load_state()
        elif args.command == "check-scope":
            current_scope = resolve_scope(args.repository)
            exclude_key = (
                scoped_state_key(args.exclude_id, current_scope["repository_identity"])
                if args.exclude_id
                else None
            )
            result = scope_conflicts(
                current_scope,
                load_state()["requirements"],
                exclude_id=exclude_key,
                allow_parallel_worktree=args.allow_parallel_worktree,
            )
        else:
            with state_lock():
                state = load_state()
                if args.command == "attach-scope":
                    previous_key = find_state_key(state["requirements"], args.id)
                    previous = (
                        state["requirements"].get(previous_key) if previous_key else None
                    )
                    if not isinstance(previous, dict):
                        raise ValueError(f"找不到需求: {args.id}")
                    entry = dict(previous)
                    scope = resolve_scope(args.repository)
                    apply_scope(entry, scope)
                    entry["requirement_id"] = args.id
                    entry["updated_at"] = dt.datetime.now().astimezone().isoformat(
                        timespec="seconds"
                    )
                    state_key = scoped_state_key(args.id, scope["repository_identity"])
                    if state_key != previous_key and state_key in state["requirements"]:
                        raise ValueError(f"目标仓库已存在需求状态: {args.id}")
                    if previous_key != state_key:
                        del state["requirements"][previous_key]
                    state["requirements"][state_key] = entry
                else:
                    requested_scope = (
                        resolve_scope(args.repository) if args.repository else None
                    )
                    previous_key = find_state_key(
                        state["requirements"],
                        args.id,
                        requested_scope["repository_identity"]
                        if requested_scope
                        else None,
                    )
                    if previous_key is None and requested_scope is None:
                        previous_key = find_state_key(state["requirements"], args.id)
                    previous = (
                        state["requirements"].get(previous_key, {})
                        if previous_key
                        else {}
                    )
                    entry = dict(previous) if isinstance(previous, dict) else {}
                    entry.update(
                        {
                            "requirement_id": args.id,
                            "status": args.status,
                            "updated_at": dt.datetime.now().astimezone().isoformat(
                                timespec="seconds"
                            ),
                        }
                    )
                    if args.title:
                        entry["title"] = args.title
                    if args.description:
                        entry["description"] = args.description
                    if args.acceptance_criterion:
                        entry["acceptance_criteria"] = args.acceptance_criterion
                    if args.project_name:
                        entry["project_name"] = args.project_name
                    if requested_scope:
                        apply_scope(entry, requested_scope)
                    if args.source_type:
                        entry["source_type"] = args.source_type
                    if args.source_fingerprint:
                        entry["source_fingerprint"] = args.source_fingerprint
                    if args.complexity_tier:
                        entry["complexity_tier"] = args.complexity_tier
                    if args.complexity_reason:
                        entry["complexity_reason"] = args.complexity_reason
                    if args.reason:
                        entry["reason"] = args.reason
                    if args.plain_language_summary:
                        entry["plain_language_summary"] = args.plain_language_summary
                    if args.evidence:
                        entry["evidence"] = args.evidence
                    if args.batch_id:
                        entry["batch_id"] = args.batch_id
                    if args.rank is not None:
                        if args.rank < 1:
                            raise ValueError("rank 必须大于等于 1")
                        entry["rank"] = args.rank
                    if args.proposed_status:
                        entry["proposed_status"] = args.proposed_status
                    if args.remaining_criterion:
                        entry["remaining_criteria"] = args.remaining_criterion
                    scope = entry_scope(entry)
                    state_key = (
                        scoped_state_key(args.id, scope["repository_identity"])
                        if scope
                        else args.id
                    )
                    if args.status in WORKSPACE_ACTIVE_STATUSES:
                        ensure_scope_available(
                            state_key,
                            entry,
                            state["requirements"],
                            allow_parallel_worktree=args.allow_parallel_worktree,
                        )
                    if state_key != previous_key and state_key in state["requirements"]:
                        raise ValueError(f"目标仓库已存在需求状态: {args.id}")
                    if previous_key and previous_key != state_key:
                        del state["requirements"][previous_key]
                    state["requirements"][state_key] = entry
                atomic_write(state)
                result = state
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
