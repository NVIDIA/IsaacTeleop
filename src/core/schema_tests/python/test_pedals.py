# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Generic3AxisPedalOutput type in isaacteleop.schema.

Tests the following FlatBuffers types:
- Generic3AxisPedalOutput: Table with is_valid, left_pedal, right_pedal, and rudder
"""

import pytest

from isaacteleop.schema import Generic3AxisPedalOutput


class TestGeneric3AxisPedalOutputConstruction:
    """Tests for Generic3AxisPedalOutput table construction."""

    def test_default_construction(self):
        """Test default construction creates Generic3AxisPedalOutput with None/zero fields."""
        output = Generic3AxisPedalOutput()

        assert output.is_valid is False
        assert output.left_pedal == 0.0
        assert output.right_pedal == 0.0
        assert output.rudder == 0.0

    def test_repr(self):
        """Test __repr__ returns meaningful string."""
        output = Generic3AxisPedalOutput()
        repr_str = repr(output)

        assert "Generic3AxisPedalOutput" in repr_str


class TestGeneric3AxisPedalOutputIsValid:
    """Tests for Generic3AxisPedalOutput is_valid property."""

    def test_default_is_valid_is_false(self):
        """Test is_valid defaults to False."""
        output = Generic3AxisPedalOutput()
        assert output.is_valid is False

    def test_set_is_valid_to_true(self):
        """Test setting is_valid to True."""
        output = Generic3AxisPedalOutput()
        output.is_valid = True
        assert output.is_valid is True

    def test_set_is_valid_to_false(self):
        """Test setting is_valid back to False."""
        output = Generic3AxisPedalOutput()
        output.is_valid = True
        output.is_valid = False
        assert output.is_valid is False


class TestGeneric3AxisPedalOutputPedals:
    """Tests for Generic3AxisPedalOutput pedal properties."""

    def test_set_left_pedal(self):
        """Test setting left pedal value."""
        output = Generic3AxisPedalOutput()
        output.left_pedal = 0.75

        assert output.left_pedal == pytest.approx(0.75)

    def test_set_right_pedal(self):
        """Test setting right pedal value."""
        output = Generic3AxisPedalOutput()
        output.right_pedal = 0.5

        assert output.right_pedal == pytest.approx(0.5)

    def test_set_rudder(self):
        """Test setting rudder value."""
        output = Generic3AxisPedalOutput()
        output.rudder = -0.33

        assert output.rudder == pytest.approx(-0.33)

    def test_set_all_pedal_values(self):
        """Test setting all pedal values."""
        output = Generic3AxisPedalOutput()
        output.left_pedal = 0.8
        output.right_pedal = 0.2
        output.rudder = 0.5

        assert output.left_pedal == pytest.approx(0.8)
        assert output.right_pedal == pytest.approx(0.2)
        assert output.rudder == pytest.approx(0.5)


class TestGeneric3AxisPedalOutputCombined:
    """Tests for Generic3AxisPedalOutput with multiple fields set."""

    def test_full_output(self):
        """Test with all fields set."""
        output = Generic3AxisPedalOutput()
        output.is_valid = True
        output.left_pedal = 1.0
        output.right_pedal = 0.0
        output.rudder = -0.5

        assert output.is_valid is True
        assert output.left_pedal == pytest.approx(1.0)
        assert output.right_pedal == pytest.approx(0.0)
        assert output.rudder == pytest.approx(-0.5)


class TestGeneric3AxisPedalOutputScenarios:
    """Tests for realistic foot pedal input scenarios."""

    def test_full_forward_press(self):
        """Test full forward press on both pedals."""
        output = Generic3AxisPedalOutput()
        output.is_valid = True
        output.left_pedal = 1.0
        output.right_pedal = 1.0
        output.rudder = 0.0

        assert output.is_valid is True
        assert output.left_pedal == pytest.approx(1.0)
        assert output.right_pedal == pytest.approx(1.0)
        assert output.rudder == pytest.approx(0.0)

    def test_left_turn_with_rudder(self):
        """Test left turn using rudder."""
        output = Generic3AxisPedalOutput()
        output.is_valid = True
        output.left_pedal = 0.5
        output.right_pedal = 0.5
        output.rudder = -1.0  # Full left rudder.

        assert output.rudder == pytest.approx(-1.0)

    def test_right_turn_with_rudder(self):
        """Test right turn using rudder."""
        output = Generic3AxisPedalOutput()
        output.is_valid = True
        output.left_pedal = 0.5
        output.right_pedal = 0.5
        output.rudder = 1.0  # Full right rudder.

        assert output.rudder == pytest.approx(1.0)

    def test_differential_braking(self):
        """Test differential braking scenario."""
        output = Generic3AxisPedalOutput()
        output.is_valid = True
        output.left_pedal = 0.0  # Left brake applied.
        output.right_pedal = 0.8  # Right pedal pressed.
        output.rudder = 0.0

        assert output.left_pedal == pytest.approx(0.0)
        assert output.right_pedal == pytest.approx(0.8)

    def test_neutral_position(self):
        """Test neutral/idle position."""
        output = Generic3AxisPedalOutput()
        output.is_valid = True
        output.left_pedal = 0.0
        output.right_pedal = 0.0
        output.rudder = 0.0

        assert output.left_pedal == pytest.approx(0.0)
        assert output.right_pedal == pytest.approx(0.0)
        assert output.rudder == pytest.approx(0.0)


class TestGeneric3AxisPedalOutputEdgeCases:
    """Edge case tests for Generic3AxisPedalOutput table."""

    def test_negative_pedal_values(self):
        """Test with negative pedal values (edge case)."""
        output = Generic3AxisPedalOutput()
        output.left_pedal = -0.5
        output.right_pedal = -0.25
        output.rudder = -1.0

        assert output.left_pedal == pytest.approx(-0.5)
        assert output.right_pedal == pytest.approx(-0.25)
        assert output.rudder == pytest.approx(-1.0)

    def test_values_greater_than_one(self):
        """Test with pedal values exceeding typical range."""
        output = Generic3AxisPedalOutput()
        output.left_pedal = 1.5
        output.right_pedal = 2.0
        output.rudder = 1.5

        assert output.left_pedal == pytest.approx(1.5)
        assert output.right_pedal == pytest.approx(2.0)
        assert output.rudder == pytest.approx(1.5)

    def test_overwrite_left_pedal(self):
        """Test overwriting left pedal value."""
        output = Generic3AxisPedalOutput()
        output.left_pedal = 0.5
        output.left_pedal = 0.9

        assert output.left_pedal == pytest.approx(0.9)

    def test_overwrite_right_pedal(self):
        """Test overwriting right pedal value."""
        output = Generic3AxisPedalOutput()
        output.right_pedal = 0.3
        output.right_pedal = 0.7

        assert output.right_pedal == pytest.approx(0.7)

    def test_overwrite_rudder(self):
        """Test overwriting rudder value."""
        output = Generic3AxisPedalOutput()
        output.rudder = 0.2
        output.rudder = -0.8

        assert output.rudder == pytest.approx(-0.8)

    def test_is_valid_false_with_data(self):
        """Test is_valid=False doesn't prevent storing data."""
        output = Generic3AxisPedalOutput()
        output.is_valid = False
        output.left_pedal = 0.5
        output.right_pedal = 0.5
        output.rudder = 0.0

        # Data is present even when is_valid is False.
        assert output.is_valid is False
        assert output.left_pedal == pytest.approx(0.5)
        assert output.right_pedal == pytest.approx(0.5)
        assert output.rudder == pytest.approx(0.0)
