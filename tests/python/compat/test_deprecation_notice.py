# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The notice must name the importing line, not the shim.

Must use the `import` statement: `importlib.import_module` adds a frame in
importlib/__init__.py, which `_warnings.is_internal_frame` does not skip (it only
skips _bootstrap*.py), and stacklevel=3 would then name importlib.
"""

import os
import re
import sys
import warnings
from pathlib import Path

import pytest


def test_the_notice_names_the_importing_line_and_the_removal():
    # This file is the only importer of isaacteleop in its ctest process; once
    # that stops being true the notice is spent and the assertions are vacuous.
    assert "isaacteleop" not in sys.modules

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import isaacteleop  # noqa: F401

    notices = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(notices) == 1, [str(w.message) for w in caught]

    # stacklevel=3 names the caller, not the shim.
    assert notices[0].filename == __file__
    source = Path(__file__).read_text().splitlines()[notices[0].lineno - 1]
    assert source.strip().startswith("import isaacteleop")

    message = str(notices[0].message)
    assert "isaaccapture" in message
    # Removal is inside the 1.x series, so a `<2` cap does not protect anyone.
    # Saying so is the whole reason the version is stated in words.
    assert "1.9" in message
    assert "isaacteleop<2" in message


def test_reimporting_does_not_announce_again():
    """The finder, not the shim module, serves every import after the first."""
    sys.modules.pop("isaacteleop", None)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import isaaccapture
        import isaacteleop

    assert isaacteleop is isaaccapture
    assert [w for w in caught if issubclass(w.category, DeprecationWarning)] == []


def test_the_notice_url_names_a_page_in_this_tree():
    """The URL ships inside a published wheel with nothing gating that it resolves.

    Version-pinning it instead would 404 for every source build: three of the five
    PEP 440 shapes IsaacTeleopVersion.cmake emits have no published docs slug.
    ``/main/`` always resolves while the page exists, so what needs gating is that
    it exists -- and this goes red at 1.9, when the page and this distribution are
    deleted together.
    """
    compat_root = os.environ.get("ISAAC_TELEOP_COMPAT_STAGE_DIR")
    if not compat_root:
        pytest.skip("ISAAC_TELEOP_COMPAT_STAGE_DIR is unset; run through ctest")

    shipped = (Path(compat_root) / "isaacteleop" / "__init__.py").read_text()
    pages = re.findall(
        r"https://nvidia\.github\.io/IsaacTeleop/main/(\S+?)\.html", shipped
    )
    assert pages == ["references/migration"]

    page = Path(__file__).parents[3] / "docs" / "source" / f"{pages[0]}.rst"
    assert page.is_file(), f"{page} is gone; the shipped wheel still links to it"
