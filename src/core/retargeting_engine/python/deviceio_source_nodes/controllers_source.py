# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Controllers Source Node - DeviceIO to Retargeting Engine converter.

Converts raw ControllerSnapshot flatbuffer data to standard ControllerInput tensor format.
"""

import numpy as np
from typing import Any, Optional, TYPE_CHECKING
from .interface import IDeviceIOSource
from ..interface.retargeter_core_types import (
    OutputSelector,
    RetargeterIO,
    RetargeterIOType,
)
from ..interface.retargeter_subgraph import RetargeterSubgraph
from ..interface.tensor_group import OptionalTensorGroup, TensorGroup
from ..tensor_types import ControllerInput, ControllerInputIndex
from ..interface.tensor_group_type import OptionalType
from .deviceio_tensor_types import DeviceIOControllerSnapshotTracked

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.schema import ControllerSnapshot, ControllerSnapshotTrackedT


class ControllersSource(IDeviceIOSource):
    """
    DeviceIO ControllerSnapshot → ControllerInput tensors.

    Optional exponential smoothing on grip/aim poses when ``pose_correction_coef`` is set.

    Inputs:
        - "deviceio_controller_left": Raw ControllerSnapshot flatbuffer for left controller
        - "deviceio_controller_right": Raw ControllerSnapshot flatbuffer for right controller

    Outputs (Optional — absent when tracking is inactive):
        - "controller_left": OptionalTensorGroup (check ``.is_none`` before access)
        - "controller_right": OptionalTensorGroup (check ``.is_none`` before access)

    Usage:
        # In TeleopSession, manually poll tracker and pass tracked objects
        left_tracked = controller_tracker.get_left_controller(session)
        right_tracked = controller_tracker.get_right_controller(session)
        result = controllers_source_node({
            "deviceio_controller_left": left_tracked,
            "deviceio_controller_right": right_tracked
        })
    """

    LEFT = "controller_left"
    RIGHT = "controller_right"

    def __init__(self, name: str, *, pose_correction_coef: Optional[float] = None) -> None:
        """Initialize controllers source node.

        Creates a ControllerTracker instance for TeleopSession to discover and use.

        Args:
            name: Unique name for this source node
            pose_correction_coef: If set, exponential catch-up smoothing factor in
                ``(0, 1)`` for grip and aim position/orientation (per hand). ``None``
                disables smoothing (raw DeviceIO poses).
        """
        import isaacteleop.deviceio as deviceio

        if pose_correction_coef is not None and not (0.0 < pose_correction_coef < 1.0):
            raise ValueError(
                "pose_correction_coef must be None or strictly between 0 and 1, "
                f"got {pose_correction_coef!r}"
            )
        self._pose_correction_coef = pose_correction_coef
        self._current_robot_poses: dict[str, dict[str, np.ndarray]] = {}

        self._controller_tracker = deviceio.ControllerTracker()
        super().__init__(name)

    def get_tracker(self) -> "ITracker":
        """Get the ControllerTracker instance.

        Returns:
            The ControllerTracker instance for TeleopSession to initialize
        """
        return self._controller_tracker

    def poll_tracker(self, deviceio_session: Any) -> RetargeterIO:
        """Poll controller tracker and return input data.

        Args:
            deviceio_session: The active DeviceIO session.

        Returns:
            Dict with "deviceio_controller_left" and "deviceio_controller_right"
            TensorGroups containing ControllerSnapshotTrackedT wrappers.
        """
        left_tracked = self._controller_tracker.get_left_controller(deviceio_session)
        right_tracked = self._controller_tracker.get_right_controller(deviceio_session)
        source_inputs = self.input_spec()
        result: RetargeterIO = {}
        for input_name, group_type in source_inputs.items():
            tg = TensorGroup(group_type)
            if "left" in input_name:
                tg[0] = left_tracked
            elif "right" in input_name:
                tg[0] = right_tracked
            result[input_name] = tg
        return result

    def input_spec(self) -> RetargeterIOType:
        """Declare DeviceIO controller inputs."""
        return {
            "deviceio_controller_left": DeviceIOControllerSnapshotTracked(),
            "deviceio_controller_right": DeviceIOControllerSnapshotTracked(),
        }

    def output_spec(self) -> RetargeterIOType:
        """Declare standard controller input outputs (Optional — may be absent)."""
        return {
            "controller_left": OptionalType(ControllerInput()),
            "controller_right": OptionalType(ControllerInput()),
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        """
        Convert DeviceIO ControllerSnapshotTrackedT to standard ControllerInput tensors.

        Calls ``set_none()`` on the output when the corresponding controller is inactive.

        Args:
            inputs: Dict with "deviceio_controller_left" and "deviceio_controller_right" TrackedT wrappers
            outputs: Dict with "controller_left" and "controller_right" OptionalTensorGroups
            context: ComputeContext (unused by this converter node).
        """
        left_tracked: "ControllerSnapshotTrackedT" = inputs["deviceio_controller_left"][
            0
        ]
        right_tracked: "ControllerSnapshotTrackedT" = inputs[
            "deviceio_controller_right"
        ][0]

        self._update_controller_data(outputs["controller_left"], left_tracked.data, "left")
        self._update_controller_data(outputs["controller_right"], right_tracked.data, "right")

    def _smooth_transition(
        self,
        target_position: np.ndarray,
        target_orientation: np.ndarray,
        frame_name: str,
        correction_coef: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Smooth the transition of the position and orientation (numpy; same math as torch lerp)."""

        pose = self._current_robot_poses.get(frame_name)
        if pose is None:
            pos = np.array(target_position, dtype=np.float32, copy=True)
            ori = np.array(target_orientation, dtype=np.float32, copy=True)
            on = float(np.linalg.norm(ori))
            if on > 1e-8:
                ori = ori / on
            self._current_robot_poses[frame_name] = {"position": pos, "orientation": ori}
            return pos, ori

        current_position = pose["position"]
        final_position = current_position + correction_coef * (target_position - current_position)

        current_orientation = pose["orientation"]
        tgt_ori = np.array(target_orientation, dtype=np.float32, copy=False)
        if float(np.dot(tgt_ori, current_orientation)) < 0.0:
            tgt_ori = -tgt_ori

        final_orientation = current_orientation + correction_coef * (tgt_ori - current_orientation)
        on = float(np.linalg.norm(final_orientation))
        if on > 1e-8:
            final_orientation = final_orientation / on

        self._current_robot_poses[frame_name]["position"] = np.array(
            final_position, dtype=np.float32, copy=True
        )
        self._current_robot_poses[frame_name]["orientation"] = np.array(
            final_orientation, dtype=np.float32, copy=True
        )
        return np.asarray(final_position, dtype=np.float32), np.asarray(
            final_orientation, dtype=np.float32
        )

    def _update_controller_data(
        self,
        group: OptionalTensorGroup,
        snapshot: "ControllerSnapshot | None",
        pose_prefix: str,
    ) -> None:
        """Helper to convert controller data for a single controller."""
        if snapshot is None:
            for suffix in ("_grip", "_aim"):
                self._current_robot_poses.pop(f"{pose_prefix}{suffix}", None)
            group.set_none()
            return

        # Extract grip pose
        grip_position = np.array(
            [
                snapshot.grip_pose.pose.position.x,
                snapshot.grip_pose.pose.position.y,
                snapshot.grip_pose.pose.position.z,
            ],
            dtype=np.float32,
        )

        grip_orientation = np.array(
            [
                snapshot.grip_pose.pose.orientation.x,
                snapshot.grip_pose.pose.orientation.y,
                snapshot.grip_pose.pose.orientation.z,
                snapshot.grip_pose.pose.orientation.w,
            ],
            dtype=np.float32,
        )

        # Extract aim pose
        aim_position = np.array(
            [
                snapshot.aim_pose.pose.position.x,
                snapshot.aim_pose.pose.position.y,
                snapshot.aim_pose.pose.position.z,
            ],
            dtype=np.float32,
        )

        aim_orientation = np.array(
            [
                snapshot.aim_pose.pose.orientation.x,
                snapshot.aim_pose.pose.orientation.y,
                snapshot.aim_pose.pose.orientation.z,
                snapshot.aim_pose.pose.orientation.w,
            ],
            dtype=np.float32,
        )

        coef = self._pose_correction_coef
        if coef is not None:
            if snapshot.grip_pose.is_valid:
                grip_position, grip_orientation = self._smooth_transition(
                    grip_position, grip_orientation, f"{pose_prefix}_grip", coef
                )
            else:
                self._current_robot_poses.pop(f"{pose_prefix}_grip", None)
            if snapshot.aim_pose.is_valid:
                aim_position, aim_orientation = self._smooth_transition(
                    aim_position, aim_orientation, f"{pose_prefix}_aim", coef
                )
            else:
                self._current_robot_poses.pop(f"{pose_prefix}_aim", None)

        # Update output tensor group
        group[ControllerInputIndex.GRIP_POSITION] = grip_position
        group[ControllerInputIndex.GRIP_ORIENTATION] = grip_orientation
        group[ControllerInputIndex.GRIP_IS_VALID] = snapshot.grip_pose.is_valid
        group[ControllerInputIndex.AIM_POSITION] = aim_position
        group[ControllerInputIndex.AIM_ORIENTATION] = aim_orientation
        group[ControllerInputIndex.AIM_IS_VALID] = snapshot.aim_pose.is_valid
        group[ControllerInputIndex.PRIMARY_CLICK] = float(snapshot.inputs.primary_click)
        group[ControllerInputIndex.SECONDARY_CLICK] = float(
            snapshot.inputs.secondary_click
        )
        group[ControllerInputIndex.THUMBSTICK_X] = float(snapshot.inputs.thumbstick_x)
        group[ControllerInputIndex.THUMBSTICK_Y] = float(snapshot.inputs.thumbstick_y)
        group[ControllerInputIndex.THUMBSTICK_CLICK] = float(
            snapshot.inputs.thumbstick_click
        )
        group[ControllerInputIndex.SQUEEZE_VALUE] = float(snapshot.inputs.squeeze_value)
        group[ControllerInputIndex.TRIGGER_VALUE] = float(snapshot.inputs.trigger_value)

    def transformed(self, transform_input: OutputSelector) -> RetargeterSubgraph:
        """
        Create a subgraph that applies a 4x4 transform to controller poses.

        This is a convenience method equivalent to manually creating a
        ControllerTransform node and connecting it.

        Args:
            transform_input: An OutputSelector providing a TransformMatrix
                (e.g., value_input.output("value")).

        Returns:
            A RetargeterSubgraph with outputs "controller_left" and "controller_right"
            containing the transformed ControllerInput data.

        Example:
            controller_source = ControllersSource("controllers")
            xform_input = ValueInput("xform", TransformMatrix())
            transformed = controller_source.transformed(xform_input.output("value"))
        """
        from ..utilities.controller_transform import ControllerTransform

        xform_node = ControllerTransform(f"{self.name}_transform")
        return xform_node.connect(
            {
                self.LEFT: self.output(self.LEFT),
                self.RIGHT: self.output(self.RIGHT),
                "transform": transform_input,
            }
        )
