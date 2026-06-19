# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for OgloGloveSample types in isaacteleop.schema.

Tests the following FlatBuffers types:
- OgloGloveSample: tactile glove sample (seq, device_time_us, 80 taxels, 6-axis IMU)
- OgloGloveSampleRecord: record wrapper carrying DeviceDataTimestamp
- OgloGloveSampleTrackedT: tracked wrapper (data is None when inactive)
"""

from isaacteleop.schema import (
    OgloGloveSample,
    OgloGloveSampleRecord,
    OgloGloveSampleTrackedT,
)

NUM_TAXELS = 80


class TestOgloGloveSample:
    """Tests for the OgloGloveSample table."""

    def test_default_construction(self):
        s = OgloGloveSample()
        assert s.seq == 0
        assert s.device_time_us == 0
        assert list(s.taxels) == []

    def test_field_round_trip(self):
        s = OgloGloveSample()
        s.seq = 12345
        s.device_time_us = 6_000_000
        s.taxels = list(range(NUM_TAXELS))
        s.accel_x, s.accel_y, s.accel_z = 100, -200, 4000
        s.gyro_x, s.gyro_y, s.gyro_z = 1, -2, 3

        assert s.seq == 12345
        assert s.device_time_us == 6_000_000
        assert len(s.taxels) == NUM_TAXELS
        assert s.taxels[0] == 0 and s.taxels[-1] == NUM_TAXELS - 1
        assert (s.accel_x, s.accel_y, s.accel_z) == (100, -200, 4000)
        assert (s.gyro_x, s.gyro_y, s.gyro_z) == (1, -2, 3)

    def test_repr(self):
        assert "OgloGloveSample" in repr(OgloGloveSample())


class TestOgloGloveSampleTrackedT:
    """Tests for the tracked wrapper."""

    def test_default_construction_inactive(self):
        assert OgloGloveSampleTrackedT().data is None

    def test_repr_inactive(self):
        assert "None" in repr(OgloGloveSampleTrackedT())


class TestOgloGloveSampleRecord:
    """Tests for the MCAP record wrapper."""

    def test_default_construction(self):
        assert OgloGloveSampleRecord().data is None

    def test_repr(self):
        assert "OgloGloveSampleRecord" in repr(OgloGloveSampleRecord())
