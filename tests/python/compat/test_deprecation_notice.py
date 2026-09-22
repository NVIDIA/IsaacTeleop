# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The notice names the importing line and is emitted once per process."""

import sys
import warnings
from pathlib import Path


def test_the_notice_names_the_importing_line_and_the_removal():
    # This file is the only importer of isaacteleop in its ctest process; once
    # that stops being true the notice is spent and the assertions are vacuous.
    assert "isaacteleop" not in sys.modules

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import isaacteleop  # noqa: F401

    notices = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(notices) == 1, [str(w.message) for w in caught]

    assert notices[0].filename == __file__
    source = Path(__file__).read_text().splitlines()[notices[0].lineno - 1]
    assert source.strip().startswith("import isaacteleop")

    message = str(notices[0].message)
    assert "isaaccapture" in message
    assert "1.9" in message


def test_reimporting_does_not_announce_again():
    """The finder, not the shim module, serves every import after the first."""
    sys.modules.pop("isaacteleop", None)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import isaaccapture
        import isaacteleop

    assert isaacteleop is isaaccapture
    assert [w for w in caught if issubclass(w.category, DeprecationWarning)] == []
