# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Tests live in examples/mujoco_xr/tests/ but import the example's own package
# from examples/mujoco_xr/python/. Prepend that directory so `mujoco_xr`
# resolves against the in-tree source -- and, with it, the
# _mujoco_xr*.so that cpp/CMakeLists.txt builds in place beside __init__.py.
#
# Same mechanism as examples/camera_viz/tests/conftest.py, one level deeper
# because our package sits under python/ rather than beside the tests. Doing it
# here rather than in the ctest ENVIRONMENT is what keeps a bare `pytest` in
# this directory working too.
#
# isaacteleop is NOT resolved here: it comes from the PYTHONPATH entry the
# ctest registration sets (${CMAKE_BINARY_DIR}/python_package/<config>), or
# from the ambient environment when run by hand.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))
