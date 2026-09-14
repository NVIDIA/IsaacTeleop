# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The whole system is pure addition. Asserted mechanically, not by good intentions."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_REF = "origin/main"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _has_base_ref() -> bool:
    try:
        _git("rev-parse", "--verify", BASE_REF)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return True


requires_git = pytest.mark.skipif(
    not (REPO_ROOT / ".git").exists() or not _has_base_ref(),
    reason=f"needs a git checkout with {BASE_REF}",
)


@requires_git
def test_no_tracked_file_outside_this_directory_is_modified():
    changed = [
        line
        for line in _git("diff", "--name-only", BASE_REF).splitlines()
        if line and not line.startswith("device_acceptance/")
    ]
    assert changed == [], f"modified files outside device_acceptance/: {changed}"


@requires_git
def test_src_core_is_untouched():
    changed = _git("diff", "--name-only", BASE_REF, "--", "src/").splitlines()
    assert changed == [], f"src/ must not change: {changed}"


def test_the_package_does_not_import_isaacteleop():
    """The checker takes only the .fbs text from the repo; flatc does the rest.

    Keeping this true is what lets acceptance work proceed without building the project
    and without competing for a schema review.
    """
    package = REPO_ROOT / "device_acceptance" / "src"
    offenders = [
        path.relative_to(REPO_ROOT)
        for path in package.rglob("*.py")
        if "isaacteleop" in path.read_text()
    ]
    assert offenders == [], f"must not depend on isaacteleop: {offenders}"
