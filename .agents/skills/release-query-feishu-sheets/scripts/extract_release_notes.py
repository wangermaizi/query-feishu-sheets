#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Extract one version section from CHANGELOG.md for GitHub Release notes."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


HEADING_RE = re.compile(r"^## \[(v\d+\.\d+\.\d+)\](?:\s+-\s+.+)?\s*$")


class ReleaseNotesError(ValueError):
    pass


def extract_release_notes(changelog: str, tag: str) -> str:
    lines = changelog.splitlines()
    matches = [
        index
        for index, line in enumerate(lines)
        if (match := HEADING_RE.fullmatch(line)) and match.group(1) == tag
    ]
    if not matches:
        raise ReleaseNotesError(f"CHANGELOG.md 缺少 {tag} 章节")
    if len(matches) > 1:
        raise ReleaseNotesError(f"CHANGELOG.md 包含重复的 {tag} 章节")
    start = matches[0] + 1
    end = next(
        (
            index
            for index in range(start, len(lines))
            if HEADING_RE.fullmatch(lines[index])
        ),
        len(lines),
    )
    notes = "\n".join(lines[start:end]).strip()
    if not notes:
        raise ReleaseNotesError(f"CHANGELOG.md 的 {tag} 章节内容为空")
    return notes + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--changelog", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        source = args.changelog.read_text(encoding="utf-8")
        notes = extract_release_notes(source, args.tag)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(notes, encoding="utf-8", newline="\n")
        print(f"Release notes: {args.output}")
        return 0
    except (OSError, ReleaseNotesError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
