# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""SO-101 analog gripper retargeter for the absolute-pose XR teleop pipeline.

The shared :class:`~isaacteleop.retargeters.GripperRetargeter` thresholds the controller
trigger into a binary open/close command (and carries hand-pinch fallback logic that the
SO-101 stacking setup does not use). For proportional grasping we instead want the jaw to
track the trigger continuously: a half-pressed trigger should leave the jaw half-closed.

:class:`SO101GripperRetargeter` reads one controller's analog trigger value
(:attr:`~isaacteleop.retargeting_engine.tensor_types.ControllerInputIndex.TRIGGER_VALUE`,
nominally ``[0, 1]``) and emits a single *closedness* scalar ``c`` in ``[0, 1]`` under
:data:`GRIPPER_COMMAND_KEY` / :data:`GRIPPER_ELEMENT_LABEL`.

Polarity / mapping (this module owns its convention):

- ``c = 0`` means the jaw is fully **OPEN**; ``c = 1`` means fully **CLOSED**.
- Pressing the trigger increases ``c`` (squeeze to grasp): ``trigger -> 1`` drives ``c -> 1``.
- A small released-end deadzone (:data:`_TRIGGER_DEADZONE`) keeps a resting trigger fully
  open; values are then rescaled and clamped to ``[0, 1]`` (see :func:`_trigger_to_closedness`).
- Downstream, the order-locked ``JointPositionActionCfg`` applies the affine
  ``joint = offset + scale * c`` with ``offset = open angle`` and
  ``scale = close angle - open angle``, so ``c = 0`` maps to the open joint angle and ``c = 1``
  to the closed joint angle; the endpoints are exactly the configured open / close angles.

This convention is deliberately independent of the shared retargeter's ``+1 = open`` /
``-1 = closed`` sign: the affine that maps ``c`` to a joint target lives in the action term,
so this node only has to produce a clean ``[0, 1]`` closedness.
"""

from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import RetargeterIO
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    OptionalType,
    TensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerInput,
    ControllerInputIndex,
    FloatType,
)

# Single source of truth for the stringly-typed pipeline wiring. These *name* the
# already-pinned ``gripper_command`` / ``gripper_value`` strings (the reorderer/output_order
# contract); they do not rename them.
GRIPPER_COMMAND_KEY = "gripper_command"
"""Group / ``connect`` / ``input_config`` key for the gripper channel."""
GRIPPER_ELEMENT_LABEL = "gripper_value"
"""Flattened element label, used in the reorderer ``input_config`` value and ``output_order``."""

# Released-end deadzone on the raw trigger value. A resting trigger reads slightly above 0 on
# some controllers; this keeps the jaw fully open until the operator deliberately squeezes.
_TRIGGER_DEADZONE = 0.05
# Closedness emitted on a pipeline reset (jaw fully open).
_OPEN_CLOSEDNESS = 0.0


def _trigger_to_closedness(trigger: float) -> float:
    """Map a raw controller trigger value to a jaw *closedness* ``c`` in ``[0, 1]``.

    Applies a released-end deadzone then rescales so the usable trigger travel spans the full
    closedness range: ``c = clamp((trigger - dz) / (1 - dz), 0, 1)`` with
    ``dz = _TRIGGER_DEADZONE``. A resting trigger (``trigger <= dz``) yields ``c = 0`` (open);
    a fully pressed trigger (``trigger >= 1``) yields ``c = 1`` (closed).

    Args:
        trigger: Raw controller trigger value, nominally in ``[0, 1]`` (clamped if outside).

    Returns:
        The jaw closedness ``c`` in ``[0, 1]``; ``0`` = fully open, ``1`` = fully closed.
    """
    span = 1.0 - _TRIGGER_DEADZONE
    c = (trigger - _TRIGGER_DEADZONE) / span
    if c < 0.0:
        return 0.0
    if c > 1.0:
        return 1.0
    return c


class SO101GripperRetargeter(BaseRetargeter):
    """Retargets an XR controller's analog trigger to a proportional SO-101 jaw closedness.

    Reads one controller's trigger value and emits a single closedness scalar ``c`` in
    ``[0, 1]`` (``0`` = open, ``1`` = closed) under :data:`GRIPPER_COMMAND_KEY` /
    :data:`GRIPPER_ELEMENT_LABEL`. The mapping is :func:`_trigger_to_closedness` (released-end
    deadzone then clamp). The last value is held on a dropped frame, and reset back to open
    (``c = 0``) on a pipeline reset.

    See the module docstring for the full polarity/mapping convention and the downstream affine
    that converts ``c`` to a ``gripper`` joint target [rad].
    """

    def __init__(self, name: str, input_device: str = ControllersSource.RIGHT) -> None:
        """Initialize the analog gripper retargeter.

        Args:
            name: Name identifier for this retargeter node.
            input_device: Controller source key to read the trigger value from.
        """
        self._input_device = input_device
        super().__init__(name=name)
        self._last_closedness = _OPEN_CLOSEDNESS

    def input_spec(self) -> RetargeterIOType:
        """Requires the analog trigger of the configured controller (Optional)."""
        return {self._input_device: OptionalType(ControllerInput())}

    def output_spec(self) -> RetargeterIOType:
        """Outputs a single float jaw closedness ``c`` in ``[0, 1]``."""
        return {
            GRIPPER_COMMAND_KEY: TensorGroupType(
                GRIPPER_COMMAND_KEY, [FloatType(GRIPPER_ELEMENT_LABEL)]
            )
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        """Computes the analog jaw closedness from the trigger; holds last on a dropped frame."""
        if context.execution_events.reset:
            self._last_closedness = _OPEN_CLOSEDNESS

        gripper_out = outputs[GRIPPER_COMMAND_KEY]
        inp = inputs[self._input_device]
        if inp.is_none:
            # Dropped frame: hold the last commanded closedness.
            gripper_out[0] = self._last_closedness
            return

        trigger_value = float(inp[ControllerInputIndex.TRIGGER_VALUE])
        self._last_closedness = _trigger_to_closedness(trigger_value)
        gripper_out[0] = self._last_closedness
