# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Tests live in examples/mujoco_xr/tests/ but import the example's own package
# from examples/mujoco_xr/python/. Prepend that directory so
# `isaacteleop_examples.mujoco_xr` resolves against the in-tree source -- and,
# with it, the _mujoco_xr*.so that cpp/CMakeLists.txt builds in place beside
# __init__.py.
#
# STILL python/, not python/isaacteleop_examples/, even though the package moved
# a level deeper: `isaacteleop_examples` is a PEP 420 namespace, so what has to
# be on sys.path is the directory CONTAINING it. Pointing one level deeper would
# resolve a bare `mujoco_xr`, which is exactly the import that no longer exists.
# The namespace has no __init__.py by design, and adding one here to "make the
# import work" would break the installed wheel's ability to share the namespace.
#
# Same mechanism as examples/camera_viz/tests/conftest.py, two levels deeper
# because our package sits under python/<namespace>/ rather than beside the
# tests. Doing it here rather than in the ctest ENVIRONMENT is what keeps a bare
# `pytest` in this directory working too.
#
# isaacteleop is NOT resolved here: it comes from the PYTHONPATH entry the
# ctest registration sets (${CMAKE_BINARY_DIR}/python_package/<config>), or
# from the ambient environment when run by hand.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))
