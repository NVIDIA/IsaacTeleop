# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Resolve `isaacteleop_examples.mujoco_xr` against the in-tree source, and with
# it the _mujoco_xr*.so built in place beside __init__.py. Here rather than in
# the ctest ENVIRONMENT so a bare `pytest` works too.
#
# python/, not python/isaacteleop_examples/: that is a PEP 420 namespace. Do not
# add an __init__.py to make an import work -- it breaks the installed wheel's
# ability to share the namespace.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))
