# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Check that SPDX-FileCopyrightText year includes the last-modified year (from git).
Use --fix to update. Falls back to current year if not in a git repo."""

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HEADER_LINES = 25


def current_year():
    return datetime.now().year


def git_last_modified_year(path: Path) -> int | None:
    """Year of the last commit that touched this file, or None if not in git."""
    path = path.resolve()
    if not path.exists():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=path.parent,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        root = Path(result.stdout.strip())
        rel = os.path.relpath(path, root)
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ad", "--date=format:%Y", "--", rel],
            capture_output=True,
            text=True,
            cwd=root,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return int(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None


def find_copyright_line(lines):
    for line in lines:
        if "SPDX-FileCopyrightText:" in line:
            return line
    return None


def year_needs_update(line, year):
    # Match "Copyright (c) 2024" or "2024-2025" etc.
    m = re.search(r"Copyright\s+\(c\)\s+(\d{4})(?:-(\d{4}))?", line, re.IGNORECASE)
    if not m:
        return False
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else start
    return year > end


def update_line(line, year):
    m = re.search(
        r"(.*Copyright\s+\(c\)\s+)(\d{4})(?:-(\d{4}))?(.*)", line, re.IGNORECASE
    )
    if not m:
        return line
    prefix, start_str, end_str, suffix = m.groups()
    start = int(start_str)
    end = int(end_str) if end_str else start
    new_end = max(end, year)
    year_part = str(new_end) if start == new_end else f"{start}-{new_end}"
    return f"{prefix}{year_part}{suffix}"


def process(path: Path, fix: bool):
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"{path}: {e}", file=sys.stderr)
        return True
    lines = content.splitlines(keepends=True)[:HEADER_LINES]
    copyright_line = find_copyright_line(lines)
    if not copyright_line:
        return True
    # Use last-modified year from git so CI (--all-files) only updates when needed
    year = git_last_modified_year(path) or current_year()
    if not year_needs_update(copyright_line, year):
        return True
    if fix:
        new_line = update_line(copyright_line, year)
        if not new_line.endswith("\n") and copyright_line.endswith("\n"):
            new_line += "\n"
        content = content.replace(copyright_line, new_line, 1)
        path.write_text(content, encoding="utf-8")
        print(f"{path}: updated copyright year to include {year}")
        return True
    print(f"{path}: copyright year should include {year}", file=sys.stderr)
    return False


def main():
    fix = "--fix" in sys.argv
    paths = [p for p in sys.argv[1:] if p != "--fix"]
    ok = all(process(Path(p).resolve(), fix) for p in paths if Path(p).exists())
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
