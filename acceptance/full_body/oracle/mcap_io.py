# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""FlatBuffer encoding + MCAP writing that mirrors the C++ recorder exactly.

Everything here is pinned to what ``src/core/mcap/cpp/inc/mcap/tracker_channels.hpp``
does, so a checker cannot tell these files apart from a real recording by envelope:

  * MCAP schema name  = ``RecordT::GetFullyQualifiedName()`` -> ``core.FullBodyPoseRecord``
  * schema encoding   = ``flatbuffer``; schema data = the .bfbs bytes
  * channel topic     = ``<base_name>/<sub_channel>`` -> ``full_body/full_body``
    (base name from the pipeline source, sub-channel from FullBodyRecordingTraits)
  * message encoding  = ``flatbuffer``
  * logTime = publishTime = ``available_time_local_common_clock``; sequence increments
  * profile ``teleop``, no compression (deviceio_session.cpp)
"""

from __future__ import annotations

from typing import Optional

import flatbuffers
import toolchain
from mcap.writer import CompressionType, Writer

toolchain.ensure()

from core import BodyJoints, DeviceDataTimestamp, FullBodyPose, FullBodyPoseRecord  # noqa: E402

from skeleton import Frame, Recording  # noqa: E402

SCHEMA_NAME = "core.FullBodyPoseRecord"
SCHEMA_ENCODING = "flatbuffer"
MESSAGE_ENCODING = "flatbuffer"
BASE_NAME = "full_body"  # pipeline source name
SUB_CHANNEL = "full_body"  # FullBodyRecordingTraits::recording_channels
TOPIC = f"{BASE_NAME}/{SUB_CHANNEL}"
PROFILE = "teleop"
BFBS_PATH = toolchain.BFBS_PATH


def load_bfbs() -> bytes:
    with open(BFBS_PATH, "rb") as fh:
        return fh.read()


def encode_record(frame: Frame) -> bytes:
    """Encode one FullBodyPoseRecord, matching pack_record()'s field layout."""
    b = flatbuffers.Builder(1400)

    data_off: Optional[int] = None
    if frame.has_data:
        FullBodyPose.Start(b)
        if frame.joints is not None:
            px = [j.pos[0] for j in frame.joints]
            py = [j.pos[1] for j in frame.joints]
            pz = [j.pos[2] for j in frame.joints]
            qx = [j.quat[0] for j in frame.joints]
            qy = [j.quat[1] for j in frame.joints]
            qz = [j.quat[2] for j in frame.joints]
            qw = [j.quat[3] for j in frame.joints]
            vv = [bool(j.valid) for j in frame.joints]
            joints_off = BodyJoints.CreateBodyJoints(b, px, py, pz, qx, qy, qz, qw, vv)
            FullBodyPose.AddJoints(b, joints_off)
        FullBodyPose.AddAllJointPosesTracked(b, frame.all_tracked)
        data_off = FullBodyPose.End(b)

    FullBodyPoseRecord.Start(b)
    ts = DeviceDataTimestamp.CreateDeviceDataTimestamp(
        b, frame.available_ns, frame.sample_ns, frame.device_ns
    )
    FullBodyPoseRecord.AddTimestamp(b, ts)
    if data_off is not None:
        FullBodyPoseRecord.AddData(b, data_off)
    b.Finish(FullBodyPoseRecord.End(b))
    return bytes(b.Output())


def write_mcap(path: str, rec: Recording, bfbs: bytes) -> None:
    with open(path, "wb") as fh:
        writer = Writer(fh, compression=CompressionType.NONE)
        writer.start(profile=PROFILE, library="isaacteleop-synthetic-fixtures")
        schema_id = writer.register_schema(
            name=SCHEMA_NAME, encoding=SCHEMA_ENCODING, data=bfbs
        )
        channel_id = writer.register_channel(
            topic=TOPIC, message_encoding=MESSAGE_ENCODING, schema_id=schema_id
        )
        for seq, frame in enumerate(rec.frames):
            writer.add_message(
                channel_id=channel_id,
                log_time=frame.available_ns,
                publish_time=frame.available_ns,
                sequence=seq,
                data=encode_record(frame),
            )
        writer.finish()
