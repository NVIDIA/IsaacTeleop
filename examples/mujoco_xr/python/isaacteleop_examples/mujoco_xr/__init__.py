# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""MuJoCo scene rendered into an Isaac Teleop Televiz XR session."""

# Load order is load-bearing -- do not let an import sorter move this.
# `import mujoco` pulls the wheel's libmujoco into the process first, and
# `_mujoco_xr` carries a NEEDED entry for that same versioned SONAME with no
# RPATH, so it binds to the already-loaded library. That is what guarantees one
# libmujoco, and so that the mjModel*/mjData* addresses Python hands the
# renderer match the layout it was compiled against.
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
