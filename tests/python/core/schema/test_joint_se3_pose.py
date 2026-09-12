# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for JointSe3PoseOutput in isaacteleop.schema.

JointSe3PoseOutput is a FlatBuffers table for a sparse set of tracked joint poses:
- joints: JointSe3Pose entries keyed by JointName, sorted ascending on the wire
- device_id: stable identity of the producing device

A joint absent from joints is not tracked; there is no per-joint validity flag.
Timestamps are carried by JointSe3PoseOutputRecord, not JointSe3PoseOutput.

Note: Python code should only READ this data (created by C++ trackers), not modify it.
"""

import pytest

from isaacteleop.schema import (
    DeviceDataTimestamp,
    JointName,
    JointSe3Pose,
    JointSe3PoseOutput,
    JointSe3PoseOutputRecord,
    Point,
    Pose,
    Quaternion,
)

# Every tip Manus produces, thumb→pinky.
TIPS = [
    JointName.HAND_RAW_THUMB_TIP,
    JointName.HAND_RAW_INDEX_TIP,
    JointName.HAND_RAW_MIDDLE_TIP,
    JointName.HAND_RAW_RING_TIP,
    JointName.HAND_RAW_LITTLE_TIP,
]


def tip(joint: JointName, x: float) -> JointSe3Pose:
    """One tip at (x, 0, 0), so a position identifies which entry it came from."""
    return JointSe3Pose(joint, Pose(Point(x, 0.0, 0.0), Quaternion(0.0, 0.0, 0.0, 1.0)))


class TestJointSe3Pose:
    """Tests for the JointSe3Pose struct."""

    def test_default_construction(self):
        """Default construction yields the UNKNOWN key and a zero pose."""
        joint = JointSe3Pose()

        assert joint.joint == JointName.UNKNOWN
        assert joint.pose.position.x == pytest.approx(0.0)

    def test_parameterized_construction(self):
        """Construction carries the key and the pose through unchanged."""
        joint = JointSe3Pose(
            JointName.HAND_RAW_THUMB_TIP,
            Pose(Point(1.0, 2.0, 3.0), Quaternion(0.0, 0.0, 0.0, 1.0)),
        )

        assert joint.joint == JointName.HAND_RAW_THUMB_TIP
        assert joint.pose.position.x == pytest.approx(1.0)
        assert joint.pose.position.y == pytest.approx(2.0)
        assert joint.pose.position.z == pytest.approx(3.0)
        assert joint.pose.orientation.w == pytest.approx(1.0)

    def test_repr(self):
        """__repr__ names the joint rather than printing its ordinal."""
        joint = tip(JointName.HAND_RAW_THUMB_TIP, 1.0)

        assert "HAND_RAW_THUMB_TIP" in repr(joint)

    def test_joint_names_are_in_their_allocated_block(self):
        """Raw hand tips occupy 1100-1199, the block joint_se3_pose.fbs allocates them."""
        assert int(JointName.UNKNOWN) == 0
        for joint in TIPS:
            assert 1100 <= int(joint) <= 1199


class TestJointSe3PoseOutput:
    """Tests for the per-frame output table."""

    def test_joints_are_sorted_on_the_wire(self):
        """Joints given out of order come back sorted ascending.

        LookupByKey binary-searches, so an unsorted vector would return the wrong joint
        rather than fail. The binding sorts on the way in to make that unreachable.
        """
        out = JointSe3PoseOutput(
            joints=[
                tip(JointName.HAND_RAW_LITTLE_TIP, 4.0),
                tip(JointName.HAND_RAW_THUMB_TIP, 0.0),
                tip(JointName.HAND_RAW_MIDDLE_TIP, 2.0),
            ],
            device_id="manus_sensors_left",
        )

        keys = [int(j.joint) for j in out.joints]
        assert keys == sorted(keys)

    def test_lookup_returns_the_matching_joint(self):
        """Each written joint is found by name, carrying its own pose."""
        out = JointSe3PoseOutput(
            joints=[tip(joint, float(i)) for i, joint in enumerate(TIPS)],
            device_id="manus_sensors_left",
        )

        assert out.device_id == "manus_sensors_left"
        assert len(out.joints) == len(TIPS)
        for i, joint in enumerate(TIPS):
            found = out.lookup(joint)
            assert found is not None
            assert found.joint == joint
            # Checking the position, not just non-None, is what proves the lookup
            # landed on the right entry rather than a neighbour.
            assert found.pose.position.x == pytest.approx(float(i))

    def test_lookup_of_an_untracked_joint_returns_none(self):
        """A joint absent from the frame misses instead of returning a neighbour."""
        out = JointSe3PoseOutput(
            joints=[
                tip(JointName.HAND_RAW_MIDDLE_TIP, 2.0),
                tip(JointName.HAND_RAW_LITTLE_TIP, 4.0),
            ],
            device_id="manus_sensors_left",
        )

        # RING sits between the two written keys, so a lookup that fell through to the
        # nearest entry would answer with one of them.
        assert out.lookup(JointName.HAND_RAW_RING_TIP) is None
        assert out.lookup(JointName.UNKNOWN) is None

    def test_empty_output(self):
        """A device reporting nothing yields no joints and no lookups."""
        out = JointSe3PoseOutput()

        assert len(out.joints) == 0
        assert out.lookup(JointName.HAND_RAW_THUMB_TIP) is None

    def test_repr(self):
        """__repr__ includes the device id and the joint count."""
        out = JointSe3PoseOutput(
            joints=[tip(JointName.HAND_RAW_THUMB_TIP, 0.0)],
            device_id="manus_sensors_right",
        )

        repr_str = repr(out)
        assert "manus_sensors_right" in repr_str
        assert "joints=1" in repr_str


class TestJointSe3PoseOutputRecord:
    """Tests for the MCAP recording wrapper."""

    def test_construction_with_timestamp(self):
        """The record carries DeviceDataTimestamp alongside the payload."""
        out = JointSe3PoseOutput(
            joints=[tip(JointName.HAND_RAW_THUMB_TIP, 1.0)],
            device_id="manus_sensors_left",
        )
        record = JointSe3PoseOutputRecord(
            out, DeviceDataTimestamp(1000000000, 2000000000, 3000000000)
        )

        assert record.timestamp.available_time_local_common_clock == 1000000000
        assert record.timestamp.sample_time_local_common_clock == 2000000000
        assert record.timestamp.sample_time_raw_device_clock == 3000000000
        assert record.data.device_id == "manus_sensors_left"

    def test_payload_less_record(self):
        """A record may carry a timestamp and no payload: MCAP's frame sentinel."""
        record = JointSe3PoseOutputRecord(None, DeviceDataTimestamp(1, 2, 3))

        assert record.data is None
        assert record.timestamp.available_time_local_common_clock == 1
