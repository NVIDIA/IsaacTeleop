#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Pre-commit hook: files marked filter=lfs in .gitattributes must be LFS pointers."""

from __future__ import annotations

import subprocess
import sys

LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"


def _paths_with_lfs_filter(filenames: list[str]) -> list[str]:
    """Return paths whose filter attribute is lfs (from .gitattributes)."""
    if not filenames:
        return []

    proc = subprocess.run(
        ["git", "check-attr", "filter", "-z", "--stdin"],
        input="\0".join(filenames).encode(),
        capture_output=True,
        check=True,
    )
    chunks = proc.stdout.split(b"\0")
    lfs_paths: list[str] = []
    for index in range(0, len(chunks) - 2, 3):
        path = chunks[index].decode()
        value = chunks[index + 2].decode()
        if value == "lfs":
            lfs_paths.append(path)
    return lfs_paths


def _staged_content(path: str) -> bytes | None:
    """Return the index (staged) blob for path, or None if unavailable."""
    proc = subprocess.run(
        ["git", "show", f":{path}"],
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _is_lfs_pointer(data: bytes) -> bool:
    if not data:
        return False
    first_line = data.split(b"\n", maxsplit=1)[0].strip()
    return first_line.startswith(LFS_POINTER_PREFIX)


def main(argv: list[str]) -> int:
    filenames = [name for name in argv if name]
    if not filenames:
        return 0

    violations: list[str] = []
    for path in _paths_with_lfs_filter(filenames):
        content = _staged_content(path)
        if content is None or not _is_lfs_pointer(content):
            violations.append(path)

    if not violations:
        return 0

    print("ERROR: Git LFS pointer check failed.\n", file=sys.stderr)
    print(
        "These files match filter=lfs in .gitattributes but are not LFS pointers:\n",
        file=sys.stderr,
    )
    for path in violations:
        print(f"  {path}", file=sys.stderr)
    print(
        "\nTo fix:\n"
        "  1. Install Git LFS:   git lfs install\n"
        "  2. Unstage the blobs: git rm --cached <file>...\n"
        "  3. Re-add via LFS:    git add <file>...\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
