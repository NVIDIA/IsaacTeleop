# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The lines this work must not cross. Asserted mechanically, not by good intentions.

Two of them run between the halves of ``acceptance/`` rather than around the whole
directory: ``fullbody/`` is the checker and must stay runnable on ``mcap`` and
``flatbuffers`` alone, while ``capture/`` drives a real session and therefore has to
import the built package.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FULLBODY_SOURCES = (
    REPO_ROOT / "acceptance" / "fullbody" / "src",
    REPO_ROOT / "acceptance" / "fullbody" / "tests",
)
UPSTREAM = "origin/main"

# `from g4_session import ...` rather than the bare name: the checker names
# `record_g4.sh` in prose, which is not a dependency on it.
CAPTURE_IMPORT = re.compile(r"^\s*(?:from|import)\s+(?:g4_\w+|capture)\b", re.MULTILINE)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _base_commit() -> str | None:
    """The commit this branch grew from, not wherever ``main`` has since moved to.

    Diffing against the upstream tip reports every file that landed on ``main``
    afterwards as changed here, which is the opposite of what these two tests ask.
    """
    try:
        return _git("merge-base", UPSTREAM, "HEAD").strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


BASE = _base_commit()

requires_git = pytest.mark.skipif(
    not (REPO_ROOT / ".git").exists() or BASE is None,
    reason=f"needs a git checkout with {UPSTREAM}",
)


def _python_files() -> list[Path]:
    """Every hand-written module under ``fullbody/``, less this file.

    The two scans below look for a name, so the file that spells the name out in order
    to ban it would report itself.
    """
    this_file = Path(__file__).resolve()
    return [
        path
        for root in FULLBODY_SOURCES
        for path in sorted(root.rglob("*.py"))
        if path.resolve() != this_file
    ]


@requires_git
def test_no_tracked_file_outside_acceptance_is_modified():
    changed = [
        line
        for line in _git("diff", "--name-only", BASE).splitlines()
        if line and not line.startswith("acceptance/")
    ]
    assert changed == [], f"modified files outside acceptance/: {changed}"


@requires_git
def test_src_is_untouched():
    changed = _git("diff", "--name-only", BASE, "--", "src/").splitlines()
    assert changed == [], f"src/ must not change: {changed}"


def test_the_checker_does_not_import_isaacteleop():
    """The checker takes only the .fbs text from the repo; flatc does the rest.

    Keeping this true is what lets acceptance work proceed without building the project
    and without competing for a schema review. It is asserted over ``fullbody/`` only:
    ``capture/`` records through ``TeleopSession`` and needs the built wheel.
    """
    offenders = [
        path.relative_to(REPO_ROOT)
        for path in _python_files()
        if "isaacteleop" in path.read_text()
    ]
    assert offenders == [], f"must not depend on isaacteleop: {offenders}"


def test_the_checker_does_not_import_the_capture_scripts():
    """Capture reads the checker's ``Frame`` and profile. Never the reverse."""
    offenders = [
        path.relative_to(REPO_ROOT)
        for path in _python_files()
        if CAPTURE_IMPORT.search(path.read_text())
    ]
    assert offenders == [], f"the checker must not import capture: {offenders}"
