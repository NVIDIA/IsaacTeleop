#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Pre-commit hook: :code-file:/:code-dir: targets in docs must exist in the tree."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# The roles build a github.com blob/tree URL out of whatever string they are given
# (docs/source/conf.py). Nothing validates the path, so a moved or mistyped target
# ships a live link to a 404 and the Sphinx build still passes. This hook is that
# missing validation.
ROLE_RE = re.compile(r":code-(file|dir):`([^`]*)`", re.S)

# Targets that are known to be wrong and are not fixed yet. Keep the reason, and
# delete the entry rather than let it settle in: every line here is a 404 on the
# published docs. See docs/AGENTS.md for the audit that found them.
KNOWN_BROKEN = {
    "src/core/deviceio_trackers/cpp/inc/deviceio_trackers/oglo_tactile_tracker.hpp": (
        "generated at configure time into ${CMAKE_BINARY_DIR}/generated/trackers/; "
        "never in the repo. Needs an author decision on what to link instead."
    ),
    "src/core/deviceio_trackers/cpp/inc/deviceio_trackers/generic_3axis_pedal_tracker.hpp": (
        "generated at configure time; see the oglo_tactile_tracker.hpp entry."
    ),
    "src/core/deviceio_trackers/cpp/inc/deviceio_trackers/joint_state_tracker.hpp": (
        "generated at configure time; see the oglo_tactile_tracker.hpp entry."
    ),
    "src/core/deviceio_trackers/cpp/inc/deviceio_trackers/se3_tracker.hpp": (
        "generated at configure time; see the oglo_tactile_tracker.hpp entry."
    ),
    "src/core/live_trackers/cpp/live_oglo_tactile_tracker_impl.cpp": (
        "generated at configure time; see the oglo_tactile_tracker.hpp entry. "
        "The generator emits both .hpp and .cpp (generate_trackers.py:59,62), "
        "so the extension is right and only the location is wrong."
    ),
}


def _repo_root() -> Path:
    """Return the work tree root, so the hook can run from any subdirectory."""
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(proc.stdout.strip())


def _parse_role(text: str) -> str:
    """Return the target of a role body, which is 'path' or 'label <path>'.

    Mirrors _parse_code_role in docs/source/conf.py, including the whitespace
    collapse: a role may wrap across source lines, and the label half may itself
    look like a path, so only the part inside <> counts when both are present.
    """
    text = " ".join(text.split())
    if " <" in text and text.endswith(">"):
        _, path = text.rsplit(" <", 1)
        return path[:-1].strip()
    return text


def _targets(path: Path) -> list[tuple[int, str, str]]:
    """Return (line, kind, target) for every code-file/code-dir role in path."""
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    found: list[tuple[int, str, str]] = []
    for match in ROLE_RE.finditer(source):
        kind = match.group(1)
        target = _parse_role(match.group(2))
        if not target:
            continue
        line = source.count("\n", 0, match.start()) + 1
        found.append((line, kind, target))
    return found


def _resolve(root: Path, kind: str, target: str) -> bool:
    """Return whether target exists in the tree with the shape its role implies."""
    resolved = root / target.rstrip("/")
    if kind == "dir":
        return resolved.is_dir()
    return resolved.is_file()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("filenames", nargs="*", help="files to check (from pre-commit)")
    parser.add_argument(
        "--all",
        action="store_true",
        help="check every .rst under docs/source instead of the passed filenames",
    )
    args = parser.parse_args(argv)

    root = _repo_root()
    if args.all:
        paths = sorted(root.glob("docs/source/**/*.rst"))
    else:
        paths = [Path(name) for name in args.filenames if name.endswith(".rst")]
    if not paths:
        return 0

    violations: list[str] = []
    stale_allowlist = set(KNOWN_BROKEN)
    for path in paths:
        for line, kind, target in _targets(path):
            if _resolve(root, kind, target):
                continue
            stale_allowlist.discard(target)
            if target in KNOWN_BROKEN:
                continue
            rel = path.relative_to(root) if path.is_absolute() else path
            violations.append(
                f"{rel}:{line}: :code-{kind}: target does not exist: {target}"
            )

    if violations:
        print("Docs reference paths that are not in the tree.", file=sys.stderr)
        print(
            "These roles render as github.com links, so each one ships a 404.",
            file=sys.stderr,
        )
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1

    # Only meaningful for a full sweep: a partial run simply did not visit them.
    if args.all and stale_allowlist:
        print("KNOWN_BROKEN entries that now resolve — delete them from the hook:")
        for target in sorted(stale_allowlist):
            print(f"  {target}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
