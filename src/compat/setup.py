# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import os

from setuptools import setup

# Classic builds supply their release version; standalone builds use the local one.
setup(version="1!" + os.environ.get("ISAAC_TELEOP_PYPROJECT_VERSION", "1.6+local"))
