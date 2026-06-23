# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Joint-State Source Node - DeviceIO to Retargeting Engine converter.

Converts raw ``JointStateOutput`` flatbuffer data (from a generic joint-space device such as a
leader arm or exoskeleton) into a name-keyed tensor group with one ``FloatType`` per joint
position, ready for consumption by ``JointStateRetargeter`` (or a ``TensorReorderer``) downstream.

The set of joints is fixed at construction (``joint_names``) so the retargeting graph has a static
input spec; the per-frame schema names are looked up against it, so wiring is order-independent.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from .interface import IDeviceIOSource
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group import TensorGroup
from ..interface.tensor_group_type import OptionalType, TensorGroupType
from ..tensor_types import FloatType
from .deviceio_tensor_types import DeviceIOJointStateOutputTracked

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.schema import JointStateOutputTrackedT


class JointStateSource(IDeviceIOSource):
    """Stateless converter: DeviceIO ``JointStateOutput`` -> name-keyed joint-position group.

    Inputs:
        - "deviceio_joint_state": Raw ``JointStateOutput`` flatbuffer from ``JointStateTracker``.

    Outputs (Optional -- absent when the device is inactive):
        - :data:`JOINTS`: one ``FloatType`` per ``joint_names`` entry (joint position [rad or m]).

    Usage::

        source = JointStateSource(name="leader", collection_id="so101_leader",
                                  joint_names=["shoulder_pan", ..., "gripper"])
        # In a TeleopSession the tracker is discovered from the pipeline and polled each frame.

    Note:
        ``joint_names`` defines the output group layout and must match the downstream consumer's
        expected order (e.g. ``JointStateRetargeterConfig.device_joints``). Only joint *positions*
        are surfaced; the schema's ``velocity`` / ``effort`` / ``valid`` / ``ee_pose`` fields are
        not exposed yet (reserved for future use).
    """

    JOINTS = "joints"

    def __init__(self, name: str, collection_id: str, joint_names: list[str]) -> None:
        """Initialize the joint-state source node.

        Args:
            name: Unique name for this source node.
            collection_id: Tensor collection ID for the device (must match the plugin / pusher).
            joint_names: Ordered device DOF names; defines the static output spec and the order
                the downstream pipeline consumes.
        """
        import isaacteleop.deviceio as deviceio

        self._tracker = deviceio.JointStateTracker(collection_id)
        self._collection_id = collection_id
        self._joint_names = list(joint_names)
        super().__init__(name)

    def get_tracker(self) -> "ITracker":
        """Return the ``JointStateTracker`` instance for ``TeleopSession`` to initialize."""
        return self._tracker

    def poll_tracker(self, deviceio_session: Any) -> RetargeterIO:
        """Poll the tracker and wrap the raw tracked data for the compute step."""
        tracked = self._tracker.get_data(deviceio_session)
        tg = TensorGroup(DeviceIOJointStateOutputTracked())
        tg[0] = tracked
        return {"deviceio_joint_state": tg}

    def input_spec(self) -> RetargeterIOType:
        """Declare the raw DeviceIO joint-state input."""
        return {"deviceio_joint_state": DeviceIOJointStateOutputTracked()}

    def output_spec(self) -> RetargeterIOType:
        """Declare the name-keyed joint-position output (Optional -- may be absent)."""
        return {
            self.JOINTS: OptionalType(
                TensorGroupType(self.JOINTS, [FloatType(n) for n in self._joint_names])
            )
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        """Convert ``JointStateOutputTrackedT`` to a name-keyed joint-position group.

        Calls ``set_none()`` on the output when the device is inactive.
        """
        tracked: "JointStateOutputTrackedT" = inputs["deviceio_joint_state"][0]
        data = tracked.data

        out = outputs[self.JOINTS]
        if data is None:
            out.set_none()
            return

        by_name: dict[str, float] = {}
        for joint in data.joints:
            name = joint.name.decode() if isinstance(joint.name, bytes) else joint.name
            by_name[name] = float(joint.position)

        for i, name in enumerate(self._joint_names):
            out[i] = by_name.get(name, 0.0)
