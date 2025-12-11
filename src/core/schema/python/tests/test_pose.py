# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for PoseT in teleopcore.schema."""

import pytest
import numpy as np

from teleopcore.schema import PoseT, TensorT


class TestPoseTConstruction:
    """Tests for PoseT construction."""

    def test_default_constructor(self):
        """Test default construction creates pose with None properties."""
        pose = PoseT()
        assert pose is not None
        assert pose.position is None
        assert pose.orientation is None


class TestPoseTPositionProperty:
    """Tests for PoseT position property."""

    def test_set_position_from_numpy(self, position_array):
        """Test setting position from numpy array."""
        pose = PoseT()
        pose.position = position_array

        assert pose.position is not None
        # Position should be a TensorT now
        result = pose.position.to_numpy()
        np.testing.assert_array_almost_equal(result, position_array)

    def test_set_position_from_tensor(self, position_array):
        """Test setting position from TensorT."""
        pose = PoseT()
        tensor = TensorT.from_numpy(position_array)
        pose.position = tensor

        assert pose.position is not None
        result = pose.position.to_numpy()
        np.testing.assert_array_almost_equal(result, position_array)

    def test_set_position_to_none(self, position_array):
        """Test setting position to None clears it."""
        pose = PoseT()
        pose.position = position_array
        assert pose.position is not None

        pose.position = None
        assert pose.position is None

    def test_position_is_copied(self, position_array):
        """Test that position data is copied, not referenced."""
        pose = PoseT()
        pose.position = position_array

        # Modify original array
        position_array[0] = 999.0

        # Pose position should be unchanged
        result = pose.position.to_numpy()
        assert result[0] != 999.0


class TestPoseTOrientationProperty:
    """Tests for PoseT orientation property."""

    def test_set_orientation_from_numpy(self, orientation_array):
        """Test setting orientation from numpy array."""
        pose = PoseT()
        pose.orientation = orientation_array

        assert pose.orientation is not None
        result = pose.orientation.to_numpy()
        np.testing.assert_array_almost_equal(result, orientation_array)

    def test_set_orientation_from_tensor(self, orientation_array):
        """Test setting orientation from TensorT."""
        pose = PoseT()
        tensor = TensorT.from_numpy(orientation_array)
        pose.orientation = tensor

        assert pose.orientation is not None
        result = pose.orientation.to_numpy()
        np.testing.assert_array_almost_equal(result, orientation_array)

    def test_set_orientation_to_none(self, orientation_array):
        """Test setting orientation to None clears it."""
        pose = PoseT()
        pose.orientation = orientation_array
        assert pose.orientation is not None

        pose.orientation = None
        assert pose.orientation is None

    def test_orientation_is_copied(self, orientation_array):
        """Test that orientation data is copied, not referenced."""
        pose = PoseT()
        pose.orientation = orientation_array

        # Modify original array
        orientation_array[3] = 0.0  # Change w component

        # Pose orientation should be unchanged
        result = pose.orientation.to_numpy()
        assert result[3] == 1.0  # Original w value


class TestPoseTFullPose:
    """Tests for PoseT with both position and orientation set."""

    def test_set_both_properties(self, position_array, orientation_array):
        """Test setting both position and orientation."""
        pose = PoseT()
        pose.position = position_array
        pose.orientation = orientation_array

        assert pose.position is not None
        assert pose.orientation is not None

        pos_result = pose.position.to_numpy()
        ori_result = pose.orientation.to_numpy()

        np.testing.assert_array_almost_equal(pos_result, position_array)
        np.testing.assert_array_almost_equal(ori_result, orientation_array)

    def test_independent_properties(self, position_array, orientation_array):
        """Test that position and orientation are independent."""
        pose = PoseT()
        pose.position = position_array
        pose.orientation = orientation_array

        # Clear position, orientation should remain
        pose.position = None
        assert pose.position is None
        assert pose.orientation is not None

        ori_result = pose.orientation.to_numpy()
        np.testing.assert_array_almost_equal(ori_result, orientation_array)


class TestPoseTErrorHandling:
    """Tests for PoseT error handling."""

    def test_invalid_position_type(self):
        """Test that invalid position type raises error."""
        pose = PoseT()
        with pytest.raises(RuntimeError, match="position must be"):
            pose.position = "invalid"

    def test_invalid_orientation_type(self):
        """Test that invalid orientation type raises error."""
        pose = PoseT()
        with pytest.raises(RuntimeError, match="orientation must be"):
            pose.orientation = [1, 2, 3, 4]  # List instead of numpy array


class TestPoseTDataTypes:
    """Tests for PoseT with various numpy data types."""

    def test_float64_position(self):
        """Test position with float64 data."""
        pose = PoseT()
        position = np.array([1.0, 2.0, 3.0], dtype=np.float64)
        pose.position = position

        result = pose.position.to_numpy()
        np.testing.assert_array_almost_equal(result, position)
        assert result.dtype == np.float64

    def test_float32_orientation(self):
        """Test orientation with float32 data."""
        pose = PoseT()
        orientation = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
        pose.orientation = orientation

        result = pose.orientation.to_numpy()
        np.testing.assert_array_almost_equal(result, orientation)
        assert result.dtype == np.float32

    def test_mixed_dtypes(self):
        """Test pose with different dtypes for position and orientation."""
        pose = PoseT()
        position = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        orientation = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)

        pose.position = position
        pose.orientation = orientation

        pos_result = pose.position.to_numpy()
        ori_result = pose.orientation.to_numpy()

        assert pos_result.dtype == np.float32
        assert ori_result.dtype == np.float64


class TestPoseTMultidimensional:
    """Tests for PoseT with multidimensional arrays (batch poses)."""

    def test_batch_positions(self):
        """Test batch of positions as 2D array."""
        pose = PoseT()
        # 5 positions, each with x, y, z
        positions = np.random.randn(5, 3).astype(np.float32)
        pose.position = positions

        result = pose.position.to_numpy()
        np.testing.assert_array_almost_equal(result, positions)
        assert result.shape == (5, 3)

    def test_batch_orientations(self):
        """Test batch of orientations as 2D array."""
        pose = PoseT()
        # 5 quaternions, each with x, y, z, w
        orientations = np.random.randn(5, 4).astype(np.float32)
        pose.orientation = orientations

        result = pose.orientation.to_numpy()
        np.testing.assert_array_almost_equal(result, orientations)
        assert result.shape == (5, 4)

