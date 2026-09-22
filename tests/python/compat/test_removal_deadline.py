# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The alias will be removed at 1.9 by deleting it -- a plan no build step runs."""

import re

from repo_paths import repo_root


def test_the_compatibility_alias_is_gone_by_1_9():
    base = (repo_root() / "VERSION").read_text(encoding="utf-8").strip()
    series = re.match(r"^(\d+)\.(\d+)\.", base)
    assert series, f"unexpected VERSION format: {base!r}"

    assert (int(series[1]), int(series[2])) < (1, 9), (
        f"VERSION is {base}, at or past the advertised removal; delete src/compat/, "
        "tests/python/compat/ and every TODO(1.9) marker rather than ship them."
    )
