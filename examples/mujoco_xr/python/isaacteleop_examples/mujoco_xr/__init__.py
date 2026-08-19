# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""MuJoCo scene rendered into an Isaac Teleop Televiz XR session."""

import os as _os

# Must precede `import mujoco`, which reads MUJOCO_GL at import time. EGL rather
# than the GLFW default because this renders offscreen, usually with no display,
# and only the EGL path honours MUJOCO_EGL_DEVICE_ID. setdefault, so an explicit
# MUJOCO_GL still wins.
_os.environ.setdefault("MUJOCO_GL", "egl")

# Load order is load-bearing -- do not let an import sorter move this. `import
# mujoco` pulls the wheel's libmujoco in first, and `_mujoco_xr` has a NEEDED
# entry for that same SONAME with no RPATH, so it binds to the already-loaded
# copy. That is what guarantees one libmujoco, and so one mjModel* layout.
import mujoco as _mujoco

from . import _mujoco_xr

if _mujoco.mj_versionString() != _mujoco_xr.mujoco_version():
    raise ImportError(
        "mujoco_xr: two different libmujoco libraries are loaded -- "
        f"the `mujoco` wheel reports {_mujoco.mj_versionString()} but the compiled "
        f"extension reports {_mujoco_xr.mujoco_version()}. The extension is what has to be "
        "rebuilt. Both `mujoco==` pins in examples/mujoco_xr/pyproject.toml (build-system.requires "
        "and project.dependencies) must name one version, and reinstalling recompiles against it: "
        "uv pip install --reinstall ./examples/mujoco_xr. (If you hit this from the in-tree ctest "
        "path instead, the extension came from the root build: install that same version into "
        "build/<preset-dir>/teleop_build_venv/bin/python and re-run cmake --preset.) "
        "mjModel* / mjData* pointers cannot cross this boundary otherwise."
    )

__all__ = ["_mujoco_xr"]
