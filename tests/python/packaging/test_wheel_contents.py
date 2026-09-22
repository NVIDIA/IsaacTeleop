# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The wheel ships one first-party package tree, spelled isaaccapture.

Both halves of the rename fail green without this. A staging root holding both
an isaacteleop/ and an isaaccapture/ tree builds and tests fine locally; a
package-data or `include` key that stopped matching drops files -- or the whole
tree -- from the wheel with no error at all, because setuptools treats a key
that matches nothing as contributing nothing.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

DIST = "isaaccapture"

# The compatibility alias, built by src/compat as its own distribution.
ALIAS = "isaacteleop"

# The curated V2D retargeting package, staged into the same wheel by
# src/core/python/CMakeLists.txt. Vendored, not ours, and not renamed.
VENDORED = "robotic_grounding"


def _wheel(dist: str = DIST) -> Path:
    wheels_dir = os.environ.get("ISAAC_TELEOP_WHEELS_DIR")
    if not wheels_dir:
        pytest.skip("ISAAC_TELEOP_WHEELS_DIR is unset; run this through ctest")
    found = list(Path(wheels_dir).glob(f"{dist}-*.whl"))
    assert found, f"no {dist} wheel in {wheels_dir}"
    # Newest, not "exactly one": nothing cleans wheels/, so in CI's dev shape --
    # where the version carries the commit count -- every commit leaves another
    # wheel in an incremental build dir.
    return max(found, key=lambda wheel: wheel.stat().st_mtime)


def _top_level_packages(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    return {
        name.split("/", 1)[0]
        for name in names
        if "/" in name and not name.split("/", 1)[0].endswith((".dist-info", ".data"))
    }


def test_wheel_ships_exactly_one_first_party_package() -> None:
    wheel = _wheel()
    assert _top_level_packages(wheel) == {DIST, VENDORED}


def test_package_tree_is_not_empty() -> None:
    wheel = _wheel()
    with zipfile.ZipFile(wheel) as archive:
        owned = [n for n in archive.namelist() if n.startswith(f"{DIST}/")]
    assert f"{DIST}/__init__.py" in owned
    assert any(n.endswith((".so", ".pyd")) for n in owned), (
        "no extension module in the wheel: the staged tree or a package-data key "
        "stopped matching"
    )


def test_alias_wheel_ships_only_the_old_name() -> None:
    """The alias ships as a second wheel beside the first, owning only isaacteleop/.

    The documented from-source install names both distributions out of one
    `--find-links=./install/wheels/`, so the wheel has to be there; and the two
    top-level sets have to stay disjoint, or a later `pip uninstall isaacteleop`
    takes isaaccapture's files with it.
    """
    assert _top_level_packages(_wheel(ALIAS)) == {ALIAS}
