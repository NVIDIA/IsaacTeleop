# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Prepend examples/mujoco_xr/python/ so `isaacteleop_examples.mujoco_xr`
# resolves against the in-tree source, and with it the _mujoco_xr*.so that
# cpp/CMakeLists.txt builds in place beside __init__.py. Doing it here rather
# than in the ctest ENVIRONMENT keeps a bare `pytest` working too.
#
# python/, not python/isaacteleop_examples/: `isaacteleop_examples` is a PEP 420
# namespace, so what goes on sys.path is the directory containing it. Do not add
# an __init__.py to make an import work -- that breaks the installed wheel's
# ability to share the namespace.
#
# isaacteleop is not resolved here: it comes from the PYTHONPATH the ctest
# registration sets, or from the ambient environment when run by hand.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))
