# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Generic3AxisPedalOutput type in isaacteleop.schema.

Tests the following FlatBuffers types:
- Generic3AxisPedalOutput: Struct (read-only) with is_active, timestamp, left_pedal, right_pedal, and rudder
"""

from isaacteleop.schema import (
    Generic3AxisPedalOutput,
)


class TestGeneric3AxisPedalOutputConstruction:
    """Tests for Generic3AxisPedalOutput struct construction."""

    def test_default_construction(self):
        """Test default construction creates Generic3AxisPedalOutput with zero-initialized fields."""
        output = Generic3AxisPedalOutput()

        assert output.is_active is False
        assert output.timestamp.device_time == 0
        assert output.left_pedal == 0.0
        assert output.right_pedal == 0.0
        assert output.rudder == 0.0

    def test_repr(self):
        """Test __repr__ returns meaningful string."""
        output = Generic3AxisPedalOutput()
        repr_str = repr(output)

        assert "Generic3AxisPedalOutput" in repr_str
