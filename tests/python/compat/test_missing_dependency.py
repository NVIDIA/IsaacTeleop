# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""A --no-deps install of isaacteleop installs the redirect and nothing else.

Isaac Sim does exactly that (`install_dependencies = false` in its pip_teleop.toml)
and interpolates `{e}` straight into the operator-facing line below, so the guard
must raise ImportError -- a RuntimeError propagates uncaught -- and must be one line.
"""

import os
import subprocess
import sys

import pytest

COMPAT_ROOT = os.environ.get("ISAAC_TELEOP_COMPAT_STAGE_DIR")

pytestmark = pytest.mark.skipif(
    not COMPAT_ROOT, reason="ISAAC_TELEOP_COMPAT_STAGE_DIR is unset; run through ctest"
)

DOWNSTREAM_HANDLER = """
try:
    import isaacteleop.deviceio as deviceio
    import isaacteleop.oxr as oxr
except ImportError as e:
    print(f"[Teleop][Session] Failed to import isaacteleop modules: {e}")
"""


def _run_without_isaaccapture(code):
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={**os.environ, "PYTHONPATH": COMPAT_ROOT},
    )


def test_the_message_is_one_line_inside_the_downstream_handler():
    result = _run_without_isaaccapture(DOWNSTREAM_HANDLER)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 1, lines
    assert lines[0].startswith(
        "[Teleop][Session] Failed to import isaacteleop modules: "
    )
    assert "pip install isaaccapture" in lines[0]


def test_the_guard_runs_before_the_finder_is_installed():
    """Otherwise a caught ImportError leaves a finder behind that serves nothing."""
    result = _run_without_isaaccapture(
        "import sys\n"
        "try:\n"
        "    import isaacteleop\n"
        "except ImportError:\n"
        "    pass\n"
        "print(sum(1 for f in sys.meta_path if type(f).__name__ == '_AliasFinder'))\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0"
