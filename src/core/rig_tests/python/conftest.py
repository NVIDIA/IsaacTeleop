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

import importlib.util
import sys
import types
from pathlib import Path

_RIG_PY = Path(__file__).resolve().parents[2] / "rig" / "python"

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
