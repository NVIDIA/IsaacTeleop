# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""SO-101 clutch (relative-origin) EE-pose retargeter for the absolute-pose XR teleop pipeline.

The shared :class:`~isaacteleop.retargeters.Se3AbsRetargeter` maps the controller's absolute
position directly to the EE target, so engaging teleop teleports the arm to wherever the
controller happens to be in the (anchor-transformed) world frame. For comfortable bring-up we
want clutch-style rebasing: capture the controller position at engage and drive the EE from
the *delta* relative to that captured origin, while keeping position-control IK
(``use_relative_mode=False``).

:class:`SO101ClutchRetargeter` therefore emits an **absolute** 7D ``ee_pose`` (position
``[x, y, z]`` [m] + orientation quaternion ``[x, y, z, w]``) with the exact same output
contract as :class:`~isaacteleop.retargeters.Se3AbsRetargeter` (node ``name="ee_pose"``, output
key ``"ee_pose"``, ``NDArrayType("pose", shape=(7,))``), so the downstream reorderer and 5D
action contract are untouched. The orientation is a passthrough of the controller grip
orientation and is dropped downstream (position-only IK).

Frame contract: the controller stream reaching this retargeter is already expressed in the
robot **base** frame -- the Isaac Lab device rebases it upstream via its
``target_frame_prim_path`` (set to the robot base), composing ``base_T_world`` onto the XR
anchor before the controllers are transformed. The clutch therefore applies the controller
delta to the home directly, with no world->base rotation of its own. The emitted position is
in the same base frame as the downstream absolute-position IK command.

Clutch behavior:

- The origin is **re-armed** (``self._origin = None``) whenever teleop is not ``RUNNING``
  (i.e. on Stop, and on an explicit reset); the first ``RUNNING`` frame thereafter (the moment
  the headset "Play" engages) latches the controller origin ``p0`` in the (base-frame)
  controller stream. Connecting the client does **not** latch the origin, and every Play
  re-zeroes it to the controller's current pose.
- The clutch keeps its own **running home** internally. Because it commands the EE, it knows
  the last target it emitted; on a mid-task re-clutch (disengage to reposition the hand,
  re-engage to continue) it latches the home to that last commanded pose, so the EE stays put
  and tracks fresh delta from where it was left -- the live end-effector is *not* re-read on a
  re-clutch.
- The home is **seeded from the configured reset-origin** on reset / first engage: the
  :paramref:`home_base_T_ee` ``base_T_ee`` transform -- the gripper's pose relative to the robot
  base at the reset pose. No live end-effector is read; the owning task resets the arm to this
  pose, so the engage after a reset latches the home there and the arm sits exactly where it
  already is (no snap on Play). The clutch never needs to read the robot back: the base rebase is
  done upstream by ``target_frame_prim_path``, and the EE state going forward is the running home
  (what the clutch itself commanded).
- Each frame the emitted position is ``output_pos = home + s * (p_ctrl - p0)`` with scale
  ``s = _CLUTCH_POSITION_SCALE`` (see :func:`_rebased_position`). On the latching frame
  ``p_ctrl == p0`` so ``output_pos == home`` exactly (no teleport on engage).
- A plain Stop **freezes** the running home, so the next Play resumes from the last commanded
  pose. An explicit **reset** re-seeds the home from the configured reset-origin for a fresh
  episode.
- The reset-origin home is supplied as a ``base_T_ee`` 4x4 transform at construction; only its
  translation drives the position command (the orientation channel is a controller passthrough,
  dropped by position-only IK). It is **never** ``(0, 0, 0)`` (that would command the EE into the
  robot base / floor).
- The last pose is held on a dropped frame.
"""

import numpy as np
from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.interface.execution_events import ExecutionState
from isaacteleop.retargeting_engine.interface.retargeter_core_types import RetargeterIO
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    OptionalType,
    TensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerInput,
    ControllerInputIndex,
    DLDataType,
    NDArrayType,
)

# Default home EE position [m] in the IK command (base) frame, used to build the fallback
# ``base_T_ee`` home when no ``home_base_T_ee`` transform is supplied (e.g. sim-free tests). A
# generic, non-degenerate bring-up value (approximately where a small tabletop arm's gripper
# sits at a neutral pose); it is intentionally arm-scale geometry, not a task-specific
# placement. Must never be the base origin (that would command the EE into the robot base /
# floor). TODO(verify-in-sim)
_CLUTCH_HOME_EE_POS: tuple[float, float, float] = (0.22, 0.0, 0.12)
# Controller-to-EE translation gain (1.0 = 1:1 motion). TODO(verify-in-sim)
_CLUTCH_POSITION_SCALE = 1.0
# Identity orientation quaternion [x, y, z, w], emitted before any valid frame / on reset.
_IDENTITY_QUAT = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)


def _rebased_position(
    p_ctrl: np.ndarray,
    origin: np.ndarray,
    home: np.ndarray,
    scale: float,
) -> np.ndarray:
    """Rebase a controller position onto the EE home via the clutch origin and scale.

    Returns ``home + scale * (p_ctrl - origin)`` [m]. With ``p_ctrl == origin`` (the latching
    frame) this is exactly ``home``; subsequent controller motion ``delta = p_ctrl - origin``
    is scaled by ``scale`` and applied to the home.

    The controller stream is already in the robot base frame (the Lab device rebases it
    upstream), so ``home`` and the downstream absolute-position IK command share that frame and
    the delta is applied without any further rotation.

    Args:
        p_ctrl: Current controller position [m], shape ``(3,)``, in the (base-frame) controller
            stream.
        origin: Latched controller origin ``p0`` [m], shape ``(3,)``, same frame.
        home: EE home position [m], shape ``(3,)``, in the IK command (base) frame.
        scale: Dimensionless translation gain applied to the controller delta.

    Returns:
        The rebased EE target position [m], shape ``(3,)``.
    """
    return home + scale * (p_ctrl - origin)


class SO101ClutchRetargeter(BaseRetargeter):
    """Retargets an XR controller to an absolute SO-101 EE pose with clutch-style rebasing.

    Emits an absolute 7D ``ee_pose`` (position [m] + grip orientation quaternion ``[x,y,z,w]``)
    identical in contract to :class:`~isaacteleop.retargeters.Se3AbsRetargeter`, but rebases the
    controller motion around a captured origin: the EE position is
    ``home + scale * (p_ctrl - p0)`` where ``p0`` is latched on the first valid frame after each
    engage. The controller stream is already in the robot base frame (rebased upstream by the
    Lab device's ``target_frame_prim_path``), so no world->base rotation is applied here. This
    keeps position-control IK (``use_relative_mode=False``) while avoiding an engage-time
    teleport (see the module docstring). The orientation is a passthrough and dropped
    downstream.

    The clutch keeps its own running home: on a mid-task re-clutch it latches the home to the
    last EE pose it commanded, so it resumes from where the arm was left (no jump). On reset /
    first engage it seeds the home from the configured :paramref:`home_base_T_ee` reset-origin
    (the gripper's pose relative to the base at the reset pose), so the arm sits where it already
    is without reading the robot back each frame.
    """

    def __init__(
        self,
        name: str,
        input_device: str = ControllersSource.RIGHT,
        home_base_T_ee: np.ndarray | None = None,
    ) -> None:
        """Initialize the clutch EE-pose retargeter.

        Args:
            name: Name identifier for this retargeter node.
            input_device: Controller source key to read the grip pose from.
            home_base_T_ee: Optional ``base_T_ee`` 4x4 reset-origin home transform [m] giving the
                EE pose in the robot base frame at the reset pose. The clutch seeds its home from
                this on reset / first engage, so the owning task must reset the arm to this pose to
                avoid a jump on engage. Only its translation block drives the position command
                (orientation is a controller passthrough, dropped by position-only IK). When
                ``None``, falls back to :data:`_CLUTCH_HOME_EE_POS`.
        """
        self._input_device = input_device
        super().__init__(name=name)
        # Reset-origin home [m] in the base frame: the translation of the ``base_T_ee`` transform,
        # or the constant. Seeds the home on reset / first engage.
        if home_base_T_ee is None:
            self._home_config = np.array(_CLUTCH_HOME_EE_POS, dtype=np.float64)
        else:
            self._home_config = np.asarray(home_base_T_ee, dtype=np.float64)[
                :3, 3
            ].copy()
        # Running home [m] in the base frame. ``None`` means "re-seed from the reset-origin on the
        # next engage"; set at construction and on reset. Otherwise it holds the last commanded
        # pose so a mid-task re-clutch resumes there.
        self._home: np.ndarray | None = None
        self._origin: np.ndarray | None = None
        # Pose held while not running and on dropped frames: the reset-origin home at identity
        # orientation until the first command refreshes it.
        self._last_pose = np.concatenate([self._home_config, _IDENTITY_QUAT]).astype(
            np.float32
        )

    def input_spec(self) -> RetargeterIOType:
        """Requires only the controller grip pose; the stream is already in the base frame."""
        return {
            self._input_device: OptionalType(ControllerInput()),
        }

    def output_spec(self) -> RetargeterIOType:
        """Outputs an absolute 7D ee pose (position [m] + quaternion [x, y, z, w])."""
        return {
            "ee_pose": TensorGroupType(
                "ee_pose",
                [
                    NDArrayType(
                        "pose", shape=(7,), dtype=DLDataType.FLOAT, dtype_bits=32
                    )
                ],
            )
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        """Computes the clutch-rebased absolute EE pose; holds last on a dropped frame."""
        # Teleop is only "engaged" when the session is RUNNING (the headset "Play").
        running = context.execution_events.execution_state == ExecutionState.RUNNING

        if context.execution_events.reset:
            # A reset starts a fresh episode: re-arm the origin and mark the home for re-seeding
            # from the configured reset-origin (the arm is reset to that pose) on the next engage.
            self._origin = None
            self._home = None
            self._last_pose = np.concatenate(
                [self._home_config, _IDENTITY_QUAT]
            ).astype(np.float32)
        elif not running:
            # A plain Stop re-arms the origin but FREEZES the running home and last pose, so the
            # next Play resumes from the last commanded pose instead of snapping to home.
            self._origin = None

        ee_pose = outputs["ee_pose"]
        inp = inputs[self._input_device]
        if inp.is_none:
            # Dropped frame: hold the last commanded pose.
            ee_pose[0] = self._last_pose
            return

        grip_pos = np.from_dlpack(inp[ControllerInputIndex.GRIP_POSITION]).astype(
            np.float64
        )
        grip_ori = np.from_dlpack(inp[ControllerInputIndex.GRIP_ORIENTATION]).astype(
            np.float32
        )  # XYZW

        if self._origin is None:
            if not running:
                # Connected but not playing yet: hold the last pose and do not latch. The origin
                # latches on the first RUNNING frame (the moment Play starts).
                ee_pose[0] = self._last_pose
                return
            # First RUNNING frame (Play just started): latch the controller origin. Seed the home
            # from the configured reset-origin on a reset / first engage, else resume the running
            # home (the last commanded pose) so a mid-task re-clutch stays put.
            self._origin = grip_pos.copy()
            if self._home is None:
                self._home = self._home_config.copy()
            else:
                self._home = self._last_pose[:3].astype(np.float64)

        pos = _rebased_position(
            grip_pos, self._origin, self._home, _CLUTCH_POSITION_SCALE
        )
        self._last_pose = np.concatenate([pos, grip_ori]).astype(np.float32)
        ee_pose[0] = self._last_pose
