# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Generic3AxisPedalOutput type in isaacteleop.schema.

Tests the following FlatBuffers types:
- Generic3AxisPedalOutput: Table with left_pedal, right_pedal, and rudder
- Generic3AxisPedalOutputRecord: Record wrapper carrying DeviceDataTimestamp

Timestamps are carried by Generic3AxisPedalOutputRecord, not Generic3AxisPedalOutput.
"""

import pytest

from isaacteleop.schema import (
    Generic3AxisPedalOutputRecord,
    Generic3AxisPedalOutput,
    DeviceDataTimestamp,
)


class TestGeneric3AxisPedalOutputConstruction:
    """Tests for Generic3AxisPedalOutput table construction."""

    def test_default_construction(self):
        """Test default construction creates Generic3AxisPedalOutput with default-initialized fields."""
        output = Generic3AxisPedalOutput()

        assert output.left_pedal == 0.0
        assert output.right_pedal == 0.0
        assert output.rudder == 0.0

    def test_repr(self):
        """Test __repr__ returns meaningful string."""
        output = Generic3AxisPedalOutput()
        repr_str = repr(output)

        assert "Generic3AxisPedalOutput" in repr_str


class TestGeneric3AxisPedalOutputPedals:
    """Tests that each pedal field round-trips through the encoding."""

    def test_left_pedal(self):
        """Test encoding left pedal value."""
        output = Generic3AxisPedalOutput(left_pedal=0.75)

        assert output.left_pedal == pytest.approx(0.75)

    def test_right_pedal(self):
        """Test encoding right pedal value."""
        output = Generic3AxisPedalOutput(right_pedal=0.5)

        assert output.right_pedal == pytest.approx(0.5)

    def test_rudder(self):
        """Test encoding rudder value."""
        output = Generic3AxisPedalOutput(rudder=-0.33)

        assert output.rudder == pytest.approx(-0.33)

    def test_all_pedal_values(self):
        """Test encoding all pedal values."""
        output = Generic3AxisPedalOutput(left_pedal=0.8, right_pedal=0.2, rudder=0.5)

        assert output.left_pedal == pytest.approx(0.8)
        assert output.right_pedal == pytest.approx(0.2)
        assert output.rudder == pytest.approx(0.5)


class TestGeneric3AxisPedalOutputCombined:
    """Tests for Generic3AxisPedalOutput with multiple fields set."""

    def test_full_output(self):
        """Test with all fields set."""
        output = Generic3AxisPedalOutput(left_pedal=1.0, right_pedal=0.0, rudder=-0.5)

        assert output.left_pedal == pytest.approx(1.0)
        assert output.right_pedal == pytest.approx(0.0)
        assert output.rudder == pytest.approx(-0.5)


class TestGeneric3AxisPedalOutputScenarios:
    """Tests for realistic foot pedal input scenarios."""

    def test_full_forward_press(self):
        """Test full forward press on both pedals."""
        output = Generic3AxisPedalOutput(left_pedal=1.0, right_pedal=1.0, rudder=0.0)

        assert output.left_pedal == pytest.approx(1.0)
        assert output.right_pedal == pytest.approx(1.0)
        assert output.rudder == pytest.approx(0.0)

    def test_left_turn_with_rudder(self):
        """Test left turn using rudder."""
        output = Generic3AxisPedalOutput(
            left_pedal=0.5, right_pedal=0.5, rudder=-1.0
        )  # Full left rudder.

        assert output.rudder == pytest.approx(-1.0)

    def test_right_turn_with_rudder(self):
        """Test right turn using rudder."""
        output = Generic3AxisPedalOutput(
            left_pedal=0.5, right_pedal=0.5, rudder=1.0
        )  # Full right rudder.

        assert output.rudder == pytest.approx(1.0)

    def test_differential_braking(self):
        """Test differential braking scenario."""
        # Left brake applied, right pedal pressed.
        output = Generic3AxisPedalOutput(left_pedal=0.0, right_pedal=0.8, rudder=0.0)

        assert output.left_pedal == pytest.approx(0.0)
        assert output.right_pedal == pytest.approx(0.8)

    def test_neutral_position(self):
        """Test neutral/idle position."""
        output = Generic3AxisPedalOutput()

        assert output.left_pedal == pytest.approx(0.0)
        assert output.right_pedal == pytest.approx(0.0)
        assert output.rudder == pytest.approx(0.0)


class TestGeneric3AxisPedalOutputEdgeCases:
    """Edge case tests for Generic3AxisPedalOutput table."""

    def test_negative_pedal_values(self):
        """Test with negative pedal values (edge case)."""
        output = Generic3AxisPedalOutput(
            left_pedal=-0.5, right_pedal=-0.25, rudder=-1.0
        )

        assert output.left_pedal == pytest.approx(-0.5)
        assert output.right_pedal == pytest.approx(-0.25)
        assert output.rudder == pytest.approx(-1.0)

    def test_values_greater_than_one(self):
        """Test with pedal values exceeding typical range."""
        output = Generic3AxisPedalOutput(left_pedal=1.5, right_pedal=2.0, rudder=1.5)

        assert output.left_pedal == pytest.approx(1.5)
        assert output.right_pedal == pytest.approx(2.0)
        assert output.rudder == pytest.approx(1.5)

    def test_encodings_are_independent(self):
        """Test each encoding carries its own values, not a shared buffer's."""
        first = Generic3AxisPedalOutput(left_pedal=0.5, right_pedal=0.3, rudder=0.2)
        second = Generic3AxisPedalOutput(left_pedal=0.9, right_pedal=0.7, rudder=-0.8)

        assert first.left_pedal == pytest.approx(0.5)
        assert first.right_pedal == pytest.approx(0.3)
        assert first.rudder == pytest.approx(0.2)
        assert second.left_pedal == pytest.approx(0.9)
        assert second.right_pedal == pytest.approx(0.7)
        assert second.rudder == pytest.approx(-0.8)


class TestGeneric3AxisPedalOutputEncoding:
    """Tests that an encoded payload reads back.

    A tracker with no pedal data returns None rather than an empty payload, so
    absence needs no case here; the source-node tests cover feeding None through.
    """

    def test_encoded_payload_reads_back(self):
        """An encoded payload gates as True and its fields read directly."""
        output = Generic3AxisPedalOutput(left_pedal=0.8, right_pedal=0.2, rudder=-0.5)

        assert output
        assert output.left_pedal == pytest.approx(0.8)
        assert output.right_pedal == pytest.approx(0.2)
        assert output.rudder == pytest.approx(-0.5)

    def test_repr_present(self):
        """Repr of a present payload names the type."""
        assert "Generic3AxisPedalOutput" in repr(Generic3AxisPedalOutput())


class TestGeneric3AxisPedalOutputRecordTimestamp:
    """Tests for Generic3AxisPedalOutputRecord with DeviceDataTimestamp."""

    def test_construction_with_timestamp(self):
        """Test Generic3AxisPedalOutputRecord carries DeviceDataTimestamp."""
        data = Generic3AxisPedalOutput(left_pedal=0.8, right_pedal=0.2, rudder=0.5)
        ts = DeviceDataTimestamp(1000000000, 2000000000, 3000000000)
        record = Generic3AxisPedalOutputRecord(data, ts)

        assert record.timestamp.available_time_local_common_clock == 1000000000
        assert record.timestamp.sample_time_local_common_clock == 2000000000
        assert record.timestamp.sample_time_raw_device_clock == 3000000000
        assert record.data.left_pedal == pytest.approx(0.8)
        assert record.data.right_pedal == pytest.approx(0.2)
        assert record.data.rudder == pytest.approx(0.5)

    def test_payload_less_record(self):
        """A record may carry a timestamp and no payload: MCAP's frame sentinel."""
        record = Generic3AxisPedalOutputRecord(None, DeviceDataTimestamp(1, 2, 3))
        assert record.data is None
        assert record.timestamp.available_time_local_common_clock == 1

    def test_timestamp_fields(self):
        """Test all three DeviceDataTimestamp fields are accessible."""
        data = Generic3AxisPedalOutput()
        ts = DeviceDataTimestamp(111, 222, 333)
        record = Generic3AxisPedalOutputRecord(data, ts)

        assert record.timestamp.available_time_local_common_clock == 111
        assert record.timestamp.sample_time_local_common_clock == 222
        assert record.timestamp.sample_time_raw_device_clock == 333
