# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""A --no-deps install of isaacteleop installs the redirect and nothing else.

Isaac Sim does exactly that (`install_dependencies = false` in its pip_teleop.toml),
and its extension loader interpolates `{e}` straight into one operator-facing line:

    except ImportError as e:
        print(f"[Teleop][Session] Failed to import isaacteleop modules: {e}")

So the guard must raise ImportError -- a RuntimeError propagates uncaught -- and
must be one line.
"""

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

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


def _run_without_isaaccapture(code, python=None):
    return subprocess.run(
        [python or sys.executable, "-c", code],
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


def test_the_message_names_the_interpreter_to_install_into():
    """This audience runs a bundled interpreter. Bare `pip` plausibly installs into
    a different Python, leaving the operator to conclude the fix did not work."""
    result = _run_without_isaaccapture(DOWNSTREAM_HANDLER)
    assert result.returncode == 0, result.stderr
    expected = f"{shlex.quote(sys.executable)} -m pip install isaaccapture"
    assert expected in result.stdout


def test_the_command_survives_a_space_in_the_interpreter_path(tmp_path):
    """A bundled interpreter sits wherever its installer put it. Unquoted, the
    command we print runs the prefix before the first space instead."""
    bundled = tmp_path / "Isaac Sim" / "python"
    bundled.parent.mkdir()
    bundled.symlink_to(Path(sys.executable).resolve())

    result = _run_without_isaaccapture(DOWNSTREAM_HANDLER, python=str(bundled))
    assert result.returncode == 0, result.stderr
    printed = re.search(r"`([^`]+)`", result.stdout)
    assert printed, result.stdout
    # Split as a shell would: what the operator pastes has to be this argv.
    assert shlex.split(printed.group(1)) == [
        str(bundled),
        "-m",
        "pip",
        "install",
        "isaaccapture",
    ]


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
