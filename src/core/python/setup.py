# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Setup script that forces platform-specific wheel generation.

Since we include pre-compiled .so/.pyd files (pybind11 extensions built by CMake),
we need to override setuptools to recognize this as a platform wheel, not pure Python.
"""

from setuptools import setup
from setuptools.dist import Distribution


class BinaryDistribution(Distribution):
    """Distribution that always forces a platform-specific wheel."""

    def has_ext_modules(self):
        return True


setup(distclass=BinaryDistribution)
