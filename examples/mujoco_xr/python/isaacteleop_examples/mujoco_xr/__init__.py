# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""MuJoCo scene rendered into an Isaac Teleop Televiz XR session."""

# LOAD ORDER IS LOAD-BEARING -- do not let an import sorter move this.
#
# `import mujoco` pulls the wheel's libmujoco.so.<version> into the process
# first (the wheel's own extensions carry RUNPATH $ORIGIN). `_mujoco_xr` is
# then linked with a NEEDED entry for that same fully-versioned SONAME and no
# RPATH of its own, so it binds to the ALREADY-LOADED library. That is what
# guarantees one libmujoco, and therefore that the mjModel*/mjData* addresses
# Python hands to the renderer point at structs with the layout it was
# compiled against.
#
# Import the other way round and the extension either fails to load (clean)
# or, with an RPATH, silently loads a second copy (not clean).
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
