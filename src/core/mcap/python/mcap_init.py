# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Isaac Teleop MCAP module.

MCAP recording is handled by DeviceIOSession. Pass a McapRecordingConfig
to DeviceIOSession.run() to enable automatic recording; omit it (or pass
None) to disable recording:

    from isaacteleop.deviceio_session import DeviceIOSession, McapRecordingConfig

    config = McapRecordingConfig("output.mcap", [
        (hand_tracker, "hands"),
        (head_tracker, "head"),
    ])
    with DeviceIOSession.run(trackers, handles, config) as session:
        while running:
            session.update()  # writes to MCAP automatically
"""

__all__ = []
