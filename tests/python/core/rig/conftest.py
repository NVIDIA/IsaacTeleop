# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Make rig python sources importable without installing ``isaacteleop``.

Synthetic package ``rig_py_test_ns``: the modules use sibling
relative imports (``from .config import …``), so they are loaded as
submodules of a synthetic package whose ``__path__`` points at the source
directory. Tests therefore always exercise the SOURCE files, not a stale
build tree; wheel packaging is covered by the wheel-content check in the
build, not by these tests.
"""

from __future__ import annotations

import pytest
import importlib.util
from unittest.mock import MagicMock, patch
import sys
import types
from pathlib import Path

_tests_python = Path(__file__).resolve().parents[2]
if str(_tests_python) not in sys.path:
    sys.path.insert(0, str(_tests_python))

from repo_paths import repo_root  # noqa: E402

_RIG_PY = repo_root() / "src" / "python" / "isaacteleop" / "rig"

RIG_TEST_PKG = "rig_py_test_ns"


def _ensure_rig_package() -> None:
    if RIG_TEST_PKG in sys.modules:
        return
    pkg = types.ModuleType(RIG_TEST_PKG)
    pkg.__path__ = [str(_RIG_PY)]
    sys.modules[RIG_TEST_PKG] = pkg

    def load(mod: str) -> None:
        full = f"{RIG_TEST_PKG}.{mod}"
        path = _RIG_PY / f"{mod}.py"
        spec = importlib.util.spec_from_file_location(full, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[full] = module
        spec.loader.exec_module(module)
        setattr(sys.modules[RIG_TEST_PKG], mod, module)

    load("config")
    load("launcher")
    load("__main__")


_ensure_rig_package()


@pytest.fixture(autouse=True)
def stub_cloudxr_launcher():
    """Keep rig tests from starting a real CloudXR runtime.

    ``launch_rig`` ensures one exists before planning panes; the rig's own
    behaviour is what these tests cover, so the launcher is stubbed to a
    fixed env file the pane assertions can rely on.

    The module is injected into ``sys.modules`` rather than patched, because
    ``isaacteleop`` is not installed here (see above) and patching would
    import it.
    """
    stub = MagicMock()
    stub.return_value.env_file = Path("/stub/.cloudxr/run/cloudxr.env")

    launcher = types.ModuleType("isaacteleop.cloudxr.launcher")
    launcher.CloudXRLauncher = stub
    cloudxr = types.ModuleType("isaacteleop.cloudxr")
    cloudxr.launcher = launcher
    root = types.ModuleType("isaacteleop")
    root.cloudxr = cloudxr

    with patch.dict(
        sys.modules,
        {
            "isaacteleop": root,
            "isaacteleop.cloudxr": cloudxr,
            "isaacteleop.cloudxr.launcher": launcher,
        },
    ):
        yield stub
