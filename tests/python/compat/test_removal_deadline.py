# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The alias is removed at 1.9 by not publishing it -- a plan no build step runs."""

from __future__ import annotations

import re

from repo_paths import repo_root


def test_the_compatibility_distribution_is_gone_by_1_9():
    """Otherwise removal is four TODO comments, two of them in shipped runtime code
    -- the /proc cmdline match and the legacy cache-override warning -- so a VERSION
    bump past the deadline keeps publishing them with nothing going red."""
    base = (repo_root() / "VERSION").read_text(encoding="utf-8").strip()
    series = re.match(r"^(\d+)\.(\d+)\.", base)
    assert series, f"unexpected VERSION format: {base!r}"

    assert (int(series[1]), int(series[2])) < (1, 9), (
        f"VERSION is {base}, at or past the advertised removal. Delete rather than "
        "publish: src/compat/, tests/python/compat/, the _LEGACY_MODULES match in "
        "src/python/isaaccapture/cloudxr/background.py, the legacy cache-override "
        "warning in src/python/isaaccapture/viz/robot/assets.py, and the compat "
        "entries in pyproject.toml and REUSE.toml."
    )
