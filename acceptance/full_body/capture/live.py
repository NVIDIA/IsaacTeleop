# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Frames and trigger presses out of a running ``TeleopSession``.

Its own pipeline builder rather than the one in
``examples/mcap_record_replay/python/common.py``: that returns only the
``OutputCombiner``, and the panel needs the ``FullBodySource`` itself to reach the
tracker. The frames are the checker's ``Frame``, built from ``get_body_pose()`` rather
than from the retargeting tensor, so the panel's ``Sample`` and skeleton are the same
code the offline panel draws.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from isaacteleop.deviceio import TrackerVendor
from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    ControllersSource,
    FullBodySource,
)
from isaacteleop.retargeting_engine.interface import OutputCombiner
from isaacteleop.retargeting_engine.tensor_types.indices import ControllerInputIndex

from full_body_acceptance.frames import Frame, JointPose

# Two thresholds rather than one, so an analogue trigger resting near the boundary
# cannot chatter out a stream of edges.
TRIGGER_DOWN = 0.6
TRIGGER_UP = 0.3


@dataclass(frozen=True, slots=True)
class LiveStep:
    """One ``session.step()``: the record it wrote, if it wrote one, and the press."""

    frame: Frame | None
    pressed: bool


def build_pipeline(
    vendor: TrackerVendor | None = None,
) -> tuple[OutputCombiner, FullBodySource]:
    """The body channel the take is about, and the controllers channel beside it.

    The controllers are not decoration: the trigger is one of the two inputs that open
    a window, and recording the channel is the only thing that makes a trigger-opened
    boundary checkable against the take itself afterwards. A mocap suit has none, and
    the take then runs on the key press alone.

    ``FullBodyTracker`` is vendor-agnostic; ``None`` selects its default ``body.pico-xr``
    backend, which reads the PICO ``XR_BD_body_tracking`` extension. Any other vendor
    arrives from a plugin and needs that plugin running -- see ``--plugin``.
    """
    controllers = ControllersSource(name="controllers")
    body = FullBodySource(name="full_body", vendor=vendor)
    pipeline = OutputCombiner(
        {
            "controller_left": controllers.output(ControllersSource.LEFT),
            "controller_right": controllers.output(ControllersSource.RIGHT),
            "full_body": body.output(FullBodySource.FULL_BODY),
        }
    )
    return pipeline, body


class LiveFrameSource:
    """Steps the session and reports what came back."""

    def __init__(self, session: Any, body: FullBodySource) -> None:
        self._session = session
        self._tracker = body.get_tracker()
        self._records = 0
        self._down = False

    @property
    def records(self) -> int:
        """Records written so far, which is the index the next one will carry."""
        return self._records

    def step(self) -> LiveStep:
        result = self._session.step()
        # A const accessor over what this step's update() published, not a second
        # locate. The tracker empties the handle on entry and publishes at the bottom,
        # so an empty one means no record was written -- which is why this counts
        # records rather than trusting step() and record count to stay equal. They
        # come apart whenever body tracking is unavailable.
        pose = self._tracker.get_body_pose(self._session.deviceio_session)
        frame = None
        if pose is not None:
            frame = _frame(self._records, pose)
            self._records += 1
        return LiveStep(frame=frame, pressed=self._edge(result))

    def _edge(self, result: Any) -> bool:
        pulled = max(
            _trigger(result["controller_left"]),
            _trigger(result["controller_right"]),
        )
        if self._down:
            self._down = pulled > TRIGGER_UP
            return False
        self._down = pulled >= TRIGGER_DOWN
        return self._down


def _trigger(controller: Any) -> float:
    if controller.is_none:
        return 0.0
    return float(controller[ControllerInputIndex.TRIGGER_VALUE])


def _frame(sequence: int, pose: Any) -> Frame:
    """One live pose as a checker ``Frame``.

    Every time field is absent or zero. The three device timestamps live on the
    ``FullBodyPoseRecord`` wrapper the recorder serialises, not on the ``FullBodyPose``
    a tracker publishes, and the two container times are the recorder's too. Reaching
    for a local clock would measure the CloudXR round trip and the GIL rather than the
    device, so nothing here does; the labels are record numbers for the same reason.
    """
    joints = pose.joints
    decoded = None
    if joints is not None:
        # Strided views aliasing the serialised buffer, copied out here so nothing
        # downstream holds a pointer into a frame the tracker has moved past.
        decoded = tuple(
            JointPose(
                position=(float(p[0]), float(p[1]), float(p[2])),
                orientation=(float(q[0]), float(q[1]), float(q[2]), float(q[3])),
                is_valid=bool(valid),
            )
            for p, q, valid in zip(
                joints.positions, joints.orientations, joints.is_valid
            )
        )
    return Frame(
        sequence=sequence,
        log_time_ns=0,
        publish_time_ns=0,
        has_payload=True,
        all_joint_poses_tracked=bool(pose.all_joint_poses_tracked),
        joints=decoded,
    )
