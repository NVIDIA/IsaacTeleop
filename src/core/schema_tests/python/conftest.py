# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Pytest configuration and fixtures for teleopcore.schema tests."""

import pytest
import numpy as np


@pytest.fixture
def float32_array():
    """Create a simple float32 numpy array."""
    return np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32)


@pytest.fixture
def float64_array():
    """Create a simple float64 numpy array."""
    return np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64)


@pytest.fixture
def int32_array():
    """Create a simple int32 numpy array."""
    return np.array([1, 2, 3, 4, 5], dtype=np.int32)


@pytest.fixture
def int64_array():
    """Create a simple int64 numpy array."""
    return np.array([[1, 2], [3, 4]], dtype=np.int64)


@pytest.fixture
def uint8_array():
    """Create a simple uint8 numpy array."""
    return np.array([0, 127, 255], dtype=np.uint8)


@pytest.fixture
def uint32_array():
    """Create a simple uint32 numpy array."""
    return np.array([0, 100, 1000, 10000], dtype=np.uint32)


@pytest.fixture
def position_array():
    """Create a 3D position array (x, y, z)."""
    return np.array([1.5, 2.5, 3.5], dtype=np.float32)


@pytest.fixture
def orientation_array():
    """Create a quaternion orientation array (x, y, z, w)."""
    # Unit quaternion (identity rotation)
    return np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)

