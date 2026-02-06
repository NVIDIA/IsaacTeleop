# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Isaac Teleop MCAP - MCAP Recording Module

This module provides MCAP file recording functionality for tracker data.

Usage:
    from isaacteleop.mcap import McapRecorder
    from isaacteleop.deviceio import DeviceIOSession, HandTracker, HeadTracker

    hand_tracker = HandTracker()
    head_tracker = HeadTracker()

    # Create recorder with context manager (similar to DeviceIOSession.run)
    with McapRecorder.create("output.mcap", [
        (hand_tracker, "hands"),
        (head_tracker, "head"),
    ]) as recorder:
        while running:
            session.update()
            recorder.record(session)
"""

from ._mcap import McapRecorder

__all__ = [
    "McapRecorder",
]
