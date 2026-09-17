# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Every staged compiled extension must be named in the wheel's package-data.

``src/core/python/pyproject.toml.in`` sets ``include-package-data = false``, so
setuptools ships a file inside a package only when a ``[tool.setuptools.package-data]``
pattern names it. A pybind11 module whose ``LIBRARY_OUTPUT_DIRECTORY`` puts its
``.so`` in the staging tree therefore reaches the wheel only if its package has an
entry in that table.

Missing one fails in the worst possible way: the package's ``__init__.py`` ships
(``packages.find`` discovers it from the staged tree) while the extension it imports
does not, so ``import isaacteleop`` raises ModuleNotFoundError for a submodule that
looks like it should be there. That is how ``isaacteleop.log_bridge`` shipped broken.

Source inspection only -- no staged package and no built extension required.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from repo_paths import repo_root

_WHEEL_MANIFEST = Path("src/core/python/pyproject.toml.in")

#: Matches a pybind11 module that stages its output into the Python package tree.
_STAGED_OUTPUT = re.compile(
    r'LIBRARY_OUTPUT_DIRECTORY\s+"\$\{CMAKE_BINARY_DIR\}/python_package/\$<CONFIG>/([^"]+)"'
)


def _staged_extension_packages() -> dict[str, Path]:
    """Map dotted package name -> the CMakeLists.txt that stages an extension there."""
    found: dict[str, Path] = {}
    for cmakelists in (repo_root() / "src").rglob("CMakeLists.txt"):
        for match in _STAGED_OUTPUT.finditer(cmakelists.read_text()):
            found[match.group(1).replace("/", ".")] = cmakelists
    return found


def _declared_packages() -> dict[str, list[str]]:
    """Package-data table of the staged wheel manifest: package name -> patterns.

    The file is a template: ``@VAR@`` placeholders are substituted by CMake. None
    of them appear inside the table this test reads, but they do appear elsewhere
    in the file, so they are blanked before parsing rather than parsed as TOML.
    """
    text = (repo_root() / _WHEEL_MANIFEST).read_text()
    manifest = tomllib.loads(re.sub(r"@[A-Za-z0-9_]+@", "", text))
    return manifest["tool"]["setuptools"]["package-data"]


def test_every_staged_extension_ships_in_the_wheel():
    staged = _staged_extension_packages()
    assert staged, "found no staged pybind11 modules -- has the pattern changed?"

    declared = _declared_packages()
    missing = {pkg: src for pkg, src in staged.items() if pkg not in declared}
    assert not missing, (
        "these packages stage a compiled extension but have no package-data entry "
        f"in {_WHEEL_MANIFEST}, so their .so will not ship in the wheel: "
        + ", ".join(f"{pkg} (from {src})" for pkg, src in sorted(missing.items()))
    )


@pytest.mark.parametrize("suffix", ["*.so", "*.pyd"])
def test_extension_entries_cover_both_platform_suffixes(suffix):
    """A Linux-only pattern silently drops the module from a Windows wheel."""
    declared = _declared_packages()
    for pkg in _staged_extension_packages():
        patterns = declared[pkg]  # absent keys are caught by the test above
        assert suffix in patterns, f"{pkg} is missing {suffix} in {_WHEEL_MANIFEST}"
