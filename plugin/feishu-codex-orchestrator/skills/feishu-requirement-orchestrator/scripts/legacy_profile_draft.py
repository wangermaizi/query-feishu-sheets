#!/usr/bin/env python3
"""Generate sanitized orchestrator drafts from saved query-feishu-sheets profiles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


PROFILE_FIELDS = (
    "display_name",
    "aliases",
    "description",
    "credential",
    "document_url",
    "default_sheet",
    "default_table",
    "default_view",
    "range",
    "header_row",
    "filters",
    "output_columns",
    "allow_unfiltered",
    "default_project_name",
    "default_repository",
    "repositories",
)
DELIVERY_FIELDS = ("chat_id", "chat_name", "format")


class DraftError(ValueError):
    pass


def load_profiles(path: Path) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DraftError(f"找不到旧 profile 配置: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DraftError(f"旧 profile 配置不是有效 JSON: {path}: {exc}") from exc
    profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles, dict):
        raise DraftError(f"旧配置缺少 profiles 对象: {path}")
    invalid = [name for name, value in profiles.items() if not isinstance(value, dict)]
    if invalid:
        raise DraftError(f"旧 profile 结构无效: {', '.join(invalid)}")
    return profiles


def load_project_routes(directory: Path) -> tuple[dict[str, Any], dict[str, list[str]]]:
    routes: dict[str, Any] = {}
    missing_fields: dict[str, list[str]] = {}
    if not directory.exists() or not directory.is_dir():
        raise DraftError(f"找不到旧项目配置目录: {directory}")
    for project_directory in sorted(item for item in directory.iterdir() if item.is_dir()):
        settings_path = project_directory / "orchestrator.json"
        if not settings_path.is_file():
            continue
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DraftError(f"旧项目配置不是有效 JSON: {settings_path}: {exc}") from exc
        project_name = settings.get("default_project_name")
        configured = settings.get("repository_routing", {}).get("routes", [])
        if not configured and settings.get("default_repository"):
            configured = [
                {
                    "label": project_name or project_directory.name,
                    "path": settings["default_repository"],
                }
            ]
        repositories = []
        for index, repository in enumerate(configured, start=1):
            if not isinstance(repository, dict) or not repository.get("path"):
                continue
            label = repository.get("display_name") or repository.get("label")
            repositories.append(
                {
                    "id": repository.get("id") or f"{project_directory.name}-{index}",
                    "display_name": label or project_name or project_directory.name,
                    "aliases": repository.get("aliases", []),
                    "description": repository.get("description", ""),
                    "project_name": repository.get("project_name") or project_name,
                    "path": repository["path"],
                }
            )
        missing = []
        if not project_name:
            missing.append("project_name")
        if not repositories:
            missing.append("repositories")
        routes[project_directory.name] = {
            "project_name": project_name,
            "repositories": repositories,
        }
        if missing:
            missing_fields[project_directory.name] = missing
    return routes, missing_fields


def sanitized_profile(profile: dict[str, Any]) -> dict[str, Any]:
    value = {field: profile[field] for field in PROFILE_FIELDS if field in profile}
    delivery = profile.get("delivery")
    if isinstance(delivery, dict):
        clean_delivery = {
            field: delivery[field] for field in DELIVERY_FIELDS if field in delivery
        }
        if clean_delivery:
            value["delivery"] = clean_delivery
    return value


def route_draft(profile: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    project_name = profile.get("default_project_name")
    repositories = profile.get("repositories")
    if not repositories and profile.get("default_repository"):
        repositories = [
            {
                "id": "default",
                "display_name": project_name or "待确认仓库",
                "aliases": [],
                "description": "",
                "project_name": project_name,
                "path": profile["default_repository"],
            }
        ]
    missing = []
    if not project_name:
        missing.append("project_name")
    if not repositories:
        missing.append("repositories")
    return {
        "project_name": project_name,
        "repositories": repositories or [],
    }, missing


def generate_draft(
    profiles: dict[str, dict[str, Any]],
    selected: list[str] | None = None,
    project_routes: dict[str, Any] | None = None,
    missing_project_fields: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    names = selected or list(profiles)
    unknown = [name for name in names if name not in profiles]
    if unknown:
        raise DraftError(f"找不到旧 profile: {', '.join(unknown)}")
    generated_profiles: dict[str, Any] = {}
    profile_routes: dict[str, Any] = {}
    missing_fields: dict[str, list[str]] = {}
    credential_references: set[str] = set()
    for name in names:
        source = profiles[name]
        generated_profiles[name] = sanitized_profile(source)
        profile_routes[name], missing = route_draft(source)
        if missing:
            missing_fields[name] = missing
        credential = source.get("credential")
        if isinstance(credential, str) and credential.strip():
            credential_references.add(credential.strip())
    return {
        "profiles_draft": {"profiles": generated_profiles},
        "orchestrator_gateway_draft": {"profile_routes": profile_routes},
        "credential_references": sorted(credential_references),
        "missing_fields": missing_fields,
        "project_routes_draft": project_routes or {},
        "missing_project_fields": missing_project_fields or {},
        "requires_confirmation_before_save": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-profiles", type=Path, required=True)
    parser.add_argument("--legacy-projects-directory", type=Path)
    parser.add_argument("--profile", action="append", default=[])
    args = parser.parse_args()
    try:
        profiles = load_profiles(args.legacy_profiles.expanduser().resolve())
        project_routes = {}
        missing_project_fields = {}
        if args.legacy_projects_directory:
            project_routes, missing_project_fields = load_project_routes(
                args.legacy_projects_directory.expanduser().resolve()
            )
        result = generate_draft(
            profiles,
            args.profile or None,
            project_routes,
            missing_project_fields,
        )
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    except DraftError as exc:
        json.dump({"error": str(exc)}, sys.stderr, ensure_ascii=False)
        sys.stderr.write("\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
