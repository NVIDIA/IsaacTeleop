# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Test data built here rather than added to the shared fixture set.

``generate_fixtures.py`` rewrites ``fixtures_index.json`` as a side effect of adding a
fixture, and that index is the oracle, so cases belonging to this checker are built
locally instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from pathlib import Path

import flatbuffers
from mcap.writer import CompressionType, Writer

import fullbody_acceptance._schema  # noqa: F401  puts generated/ on sys.path
from core import BodyJoints, DeviceDataTimestamp, FullBodyPose, FullBodyPoseRecord
from fullbody_acceptance.frames import NUM_JOINTS, Frame, JointPose

SCHEMA_NAME = "core.FullBodyPoseRecord"
TOPIC = "full_body/full_body"
PROFILE = "teleop"
PERIOD_NS = 16_666_667
CLOCK_BASE_NS = 1_000_000_000_000
DEVICE_EPOCH_NS = 55_000_000_000_000

IDENTITY = (0.0, 0.0, 0.0, 1.0)


def joint(
    position: tuple[float, float, float] = (0.1, 1.0, 0.2),
    orientation: tuple[float, float, float, float] = IDENTITY,
    is_valid: bool = True,
) -> JointPose:
    return JointPose(position=position, orientation=orientation, is_valid=is_valid)


def frame(
    sequence: int = 0,
    *,
    joints: tuple[JointPose, ...] | None = None,
    has_payload: bool = True,
    sample_ns: int | None = None,
    available_ns: int | None = None,
    device_ns: int | None = None,
    all_tracked: bool | None = True,
) -> Frame:
    """A plausible frame; every argument exists so a test can spoil exactly one thing."""
    sample = CLOCK_BASE_NS + sequence * PERIOD_NS if sample_ns is None else sample_ns
    available = sample + 2_000_000 if available_ns is None else available_ns
    device = DEVICE_EPOCH_NS + sequence * PERIOD_NS if device_ns is None else device_ns
    if joints is None and has_payload:
        joints = tuple(
            joint(position=(0.05 * i, 0.5 + 0.03 * i, 0.01 * i))
            for i in range(NUM_JOINTS)
        )
    return Frame(
        sequence=sequence,
        log_time_ns=available,
        publish_time_ns=available,
        has_payload=has_payload,
        available_time_ns=available,
        sample_time_ns=sample,
        device_time_ns=device,
        all_joint_poses_tracked=all_tracked if has_payload else None,
        joints=joints if has_payload else None,
    )


def frames(count: int, **kwargs) -> list[Frame]:
    return [frame(i, **kwargs) for i in range(count)]


def with_joint(base: Frame, index: int, replacement: JointPose) -> Frame:
    assert base.joints is not None
    joints = list(base.joints)
    joints[index] = replacement
    return replace(base, joints=tuple(joints))


@dataclass
class StubSource:
    """A FrameSource over frames held in memory."""

    frame_list: list[Frame] = field(default_factory=list)
    channel_found: bool = True

    @property
    def metadata(self):
        from fullbody_acceptance.frames import SourceMetadata

        return SourceMetadata(
            schema_name=SCHEMA_NAME if self.channel_found else None,
            schema_encoding="flatbuffer" if self.channel_found else None,
            schema_data=b"\x00" if self.channel_found else None,
            message_encoding="flatbuffer" if self.channel_found else None,
            topic=TOPIC if self.channel_found else None,
            profile=PROFILE,
            channel_found=self.channel_found,
        )

    def __iter__(self):
        return iter(self.frame_list)


def encode(frame_: Frame) -> bytes:
    """Encodes a Frame back to wire bytes, matching pack_record()'s field layout."""
    builder = flatbuffers.Builder(1400)

    data_offset = None
    if frame_.has_payload:
        FullBodyPose.Start(builder)
        if frame_.joints is not None:
            joints = frame_.joints
            offset = BodyJoints.CreateBodyJoints(
                builder,
                [j.position[0] for j in joints],
                [j.position[1] for j in joints],
                [j.position[2] for j in joints],
                [j.orientation[0] for j in joints],
                [j.orientation[1] for j in joints],
                [j.orientation[2] for j in joints],
                [j.orientation[3] for j in joints],
                [bool(j.is_valid) for j in joints],
            )
            FullBodyPose.AddJoints(builder, offset)
        FullBodyPose.AddAllJointPosesTracked(
            builder, bool(frame_.all_joint_poses_tracked)
        )
        data_offset = FullBodyPose.End(builder)

    FullBodyPoseRecord.Start(builder)
    timestamp = DeviceDataTimestamp.CreateDeviceDataTimestamp(
        builder,
        frame_.available_time_ns or 0,
        frame_.sample_time_ns or 0,
        frame_.device_time_ns or 0,
    )
    FullBodyPoseRecord.AddTimestamp(builder, timestamp)
    if data_offset is not None:
        FullBodyPoseRecord.AddData(builder, data_offset)
    builder.Finish(FullBodyPoseRecord.End(builder))
    return bytes(builder.Output())


def bfbs_bytes() -> bytes:
    path = Path(__file__).resolve().parents[1] / "build" / "bfbs" / "full_body.bfbs"
    return path.read_bytes()


def write_recording(
    path: Path,
    frame_list: list[Frame],
    *,
    schema_name: str = SCHEMA_NAME,
    topic: str = TOPIC,
) -> Path:
    """Writes an MCAP the checker cannot tell from a real one by envelope.

    An empty ``frame_list`` still registers the schema and channel, which is what a
    tracker in limp mode leaves behind.
    """
    with path.open("wb") as handle:
        writer = Writer(handle, compression=CompressionType.NONE)
        writer.start(profile=PROFILE, library="fullbody-acceptance-tests")
        schema_id = writer.register_schema(
            name=schema_name, encoding="flatbuffer", data=bfbs_bytes()
        )
        channel_id = writer.register_channel(
            topic=topic, message_encoding="flatbuffer", schema_id=schema_id
        )
        for sequence, item in enumerate(frame_list):
            writer.add_message(
                channel_id=channel_id,
                log_time=item.log_time_ns,
                publish_time=item.publish_time_ns,
                sequence=sequence,
                data=encode(item),
            )
        writer.finish()
    return path


def unit_quaternion(angle_rad: float, axis: tuple[float, float, float]) -> tuple:
    half = angle_rad / 2.0
    scale = math.sin(half)
    return (axis[0] * scale, axis[1] * scale, axis[2] * scale, math.cos(half))
