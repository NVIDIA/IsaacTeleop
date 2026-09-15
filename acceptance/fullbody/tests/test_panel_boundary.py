# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The renderer is optional. Asserted mechanically, because good intentions erode.

The checker runs today from a fresh clone with mcap and flatbuffers and nothing else,
and one convenience import is all it would take to lose that.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "fullbody_acceptance"

# The single module allowed to import viser.
RENDERER = PACKAGE / "panel" / "app.py"

IMPORTS_VISER = re.compile(r"^\s*(?:import viser|from viser)", re.MULTILINE)


def test_only_the_renderer_imports_viser():
    assert RENDERER.is_file(), "the allowed module moved; update this rule"
    offenders = sorted(
        path.relative_to(PACKAGE).as_posix()
        for path in PACKAGE.rglob("*.py")
        if path != RENDERER and IMPORTS_VISER.search(path.read_text())
    )
    assert offenders == [], f"viser belongs in panel/app.py alone: {offenders}"


def test_the_checker_and_the_panel_arithmetic_import_without_viser():
    """Blocking the module is the only honest test: it may well be installed here."""
    probe = (
        "import sys; sys.modules['viser'] = None;"
        "import fullbody_acceptance.cli;"
        "import fullbody_acceptance.panel.track;"
        "import fullbody_acceptance.panel.status;"
        "import fullbody_acceptance.panel.render"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=PACKAGE.parent,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
