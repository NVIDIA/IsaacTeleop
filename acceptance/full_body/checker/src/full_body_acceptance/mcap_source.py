# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Reads full-body records out of an MCAP file.

Two things here are load-bearing.

``mcap.reader.make_reader()`` re-sorts messages by log time, which silently repairs a
recording with non-monotonic timestamps. ``StreamReader`` walks raw records in file
order, the way the C++ ``LinearMessageView`` does, so a reordered file stays reordered.

Channels are located by declared schema name. The topic is ``<source name>/<sub-channel>``
where the prefix is whatever ``name=`` the recording script passed, so it is not intrinsic
to the format.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from mcap.records import Channel, Header, Message, Schema
from mcap.stream_reader import StreamReader

from ._schema import FullBodyPoseRecord, Point, Pose, Quaternion
from .frames import NUM_JOINTS, SCHEMA_NAME, Frame, JointPose, SourceMetadata


def decode_record(
    data: bytes, sequence: int, log_time: int, publish_time: int
) -> Frame:
    record = FullBodyPoseRecord.GetRootAs(data, 0)

    timestamp = record.Timestamp()
    available = sample = device = None
    if timestamp is not None:
        available = timestamp.AvailableTimeLocalCommonClock()
        sample = timestamp.SampleTimeLocalCommonClock()
        device = timestamp.SampleTimeRawDeviceClock()

    pose = record.Data()
    joints = None
    all_tracked = None
    if pose is not None:
        all_tracked = bool(pose.AllJointPosesTracked())
        body = pose.Joints()
        if body is not None:
            # Nested-struct accessors fill a caller-supplied view rather than returning
            # one, so these three are reused across the loop.
            pose_view, point_view, quat_view = Pose(), Point(), Quaternion()
            decoded = []
            for i in range(NUM_JOINTS):
                joint = body.Joints(i)
                joint_pose = joint.Pose(pose_view)
                p = joint_pose.Position(point_view)
                q = joint_pose.Orientation(quat_view)
                decoded.append(
                    JointPose(
                        position=(p.X(), p.Y(), p.Z()),
                        orientation=(q.X(), q.Y(), q.Z(), q.W()),
                        is_valid=bool(joint.IsValid()),
                    )
                )
            joints = tuple(decoded)

    return Frame(
        sequence=sequence,
        log_time_ns=log_time,
        publish_time_ns=publish_time,
        has_payload=pose is not None,
        available_time_ns=available,
        sample_time_ns=sample,
        device_time_ns=device,
        all_joint_poses_tracked=all_tracked,
        joints=joints,
    )


class McapFrameSource:
    def __init__(self, path: str | Path, schema_name: str = SCHEMA_NAME) -> None:
        self._path = Path(path)
        self._schema_name = schema_name
        self._metadata = self._scan()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def metadata(self) -> SourceMetadata:
        return self._metadata

    def _scan(self) -> SourceMetadata:
        """Finds the channel without decoding any payload.

        A channel that is registered but carries no messages is a real case: the Pico
        tracker registers its channels at construction, then returns early from
        ``update()`` in limp mode and never publishes. That must read as insufficient
        data, not as a pass.
        """
        profile = None
        schemas: dict[int, Schema] = {}
        with self._path.open("rb") as handle:
            for record in StreamReader(handle).records:
                if isinstance(record, Header):
                    profile = record.profile
                elif isinstance(record, Schema):
                    schemas[record.id] = record
                elif isinstance(record, Channel):
                    schema = schemas.get(record.schema_id)
                    if schema is not None and schema.name == self._schema_name:
                        return SourceMetadata(
                            schema_name=schema.name,
                            schema_encoding=schema.encoding,
                            schema_data=schema.data,
                            message_encoding=record.message_encoding,
                            topic=record.topic,
                            profile=profile,
                            channel_found=True,
                        )
        return SourceMetadata(
            schema_name=None,
            schema_encoding=None,
            schema_data=None,
            message_encoding=None,
            topic=None,
            profile=profile,
            channel_found=False,
        )

    def __iter__(self) -> Iterator[Frame]:
        if not self._metadata.channel_found:
            return

        schemas: dict[int, Schema] = {}
        channel_ids: set[int] = set()
        with self._path.open("rb") as handle:
            for record in StreamReader(handle).records:
                if isinstance(record, Schema):
                    schemas[record.id] = record
                elif isinstance(record, Channel):
                    schema = schemas.get(record.schema_id)
                    if schema is not None and schema.name == self._schema_name:
                        channel_ids.add(record.id)
                elif isinstance(record, Message) and record.channel_id in channel_ids:
                    yield decode_record(
                        record.data,
                        record.sequence,
                        record.log_time,
                        record.publish_time,
                    )
