# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Make CloudXR python sources importable without installing ``isaacteleop``.

* Flat ``sys.path`` entry: ``from oob_teleop_hub import …`` (no relative imports).
* Synthetic package ``cloudxr_py_test_ns``: ``from cloudxr_py_test_ns.oob_teleop_env import …``
  so modules that use sibling relative imports load correctly.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_CLOUDXR_PY = Path(__file__).resolve().parents[2] / "cloudxr" / "python"
if _CLOUDXR_PY.is_dir() and str(_CLOUDXR_PY) not in sys.path:
    sys.path.insert(0, str(_CLOUDXR_PY))

CLOUDXR_TEST_PKG = "cloudxr_py_test_ns"


def _ensure_cloudxr_package() -> None:
    if CLOUDXR_TEST_PKG in sys.modules:
        return
    pkg = types.ModuleType(CLOUDXR_TEST_PKG)
    pkg.__path__ = [str(_CLOUDXR_PY)]
    sys.modules[CLOUDXR_TEST_PKG] = pkg

    def load(mod: str) -> None:
        full = f"{CLOUDXR_TEST_PKG}.{mod}"
        path = _CLOUDXR_PY / f"{mod}.py"
        spec = importlib.util.spec_from_file_location(full, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[full] = module
        spec.loader.exec_module(module)
        setattr(sys.modules[CLOUDXR_TEST_PKG], mod, module)

    load("oob_teleop_hub")
    load("oob_teleop_env")
    load("oob_teleop_adb")


_ensure_cloudxr_package()
