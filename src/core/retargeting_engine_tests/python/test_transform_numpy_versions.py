# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Run pose-transform smoke under isolated NumPy versions (1.23.x and 2.x).

NumPy 1.23 adds the public ``numpy.from_dlpack`` API used by the transform path.
CTest sets ``PYTHONPATH`` to the built ``python_package`` tree; each test spawns
``uv run --no-project`` with a pinned NumPy.

Python version comes from the **same interpreter as pytest** (CI matrix /
``ISAAC_TELEOP_PYTHON_VERSION``), not a hard-coded list. That keeps ``uv run``
aligned with the wheel ABI under ``PYTHONPATH`` (native extensions match).

The NumPy **1.23.5** pin is **skipped** on Python 3.12+ (no viable wheels / install
for that interpreter). NumPy **2.x** runs on every matrix Python.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_SMOKE = Path(__file__).resolve().parent / "transform_numpy_version_smoke.py"


@pytest.mark.parametrize(
    ("numpy_pin", "version_key"),
    [
        ("numpy==1.23.5", "1.23"),
        ("numpy>=2.0.0,<3", "2"),
    ],
)
def test_head_transform_smoke_isolated_numpy(numpy_pin: str, version_key: str) -> None:
    if shutil.which("uv") is None:
        pytest.skip("uv not on PATH")
    if "PYTHONPATH" not in os.environ:
        pytest.skip(
            "PYTHONPATH unset (run under CTest or point at build python_package/<CONFIG>)"
        )
    if not _SMOKE.is_file():
        pytest.fail(f"missing smoke script: {_SMOKE}")

    if version_key == "1.23" and sys.version_info >= (3, 12):
        pytest.skip(
            "numpy==1.23.5 is not supported on Python 3.12+ (no wheels; matrix uses 3.12/3.13)"
        )

    py = f"{sys.version_info.major}.{sys.version_info.minor}"
    cmd = [
        "uv",
        "run",
        "--no-project",
        "--python",
        py,
        "--with",
        numpy_pin,
        "python",
        str(_SMOKE),
        version_key,
    ]
    subprocess.run(cmd, check=True, env=os.environ.copy())
