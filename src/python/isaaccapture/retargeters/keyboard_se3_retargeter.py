# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Keyboard SE3 Retargeter Module.

Maps raw keyboard press state to end-effector delta commands and a gripper toggle.
"""

import numpy as np
from dataclasses import dataclass

from isaaccapture.retargeting_engine.deviceio_source_nodes import (
    EvdevKeyCode,
    KeyboardAllKeysType,
    KeyboardPressedType,
)
from isaaccapture.retargeting_engine.interface import (
    BaseRetargeter,
    RetargeterIOType,
)
from isaaccapture.retargeting_engine.interface.retargeter_core_types import RetargeterIO
from isaaccapture.retargeting_engine.interface.tensor_group_type import (
    TensorGroupType,
    OptionalType,
)
from isaaccapture.retargeting_engine.tensor_types import (
    NDArrayType,
    DLDataType,
    FloatType,
)

from scipy.spatial.transform import Rotation


@dataclass
class KeyboardToSe3RelRetargeterConfig:
    """Configuration for the keyboard-to-SE3-relative retargeter."""

    pos_sensitivity: float = 0.4
    rot_sensitivity: float = 0.8


class KeyboardToSe3RelRetargeter(BaseRetargeter):
    """
    Maps keyboard press state to a 6D end-effector delta command.

    Key bindings:
        W/S: +/-X, A/D: +/-Y, Q/E: +/-Z (position)
        Z/X: +/-roll, T/G: +/-pitch, C/V: +/-yaw (rotation)

    Output is the instantaneous command implied by the currently held keys (scaled by
    sensitivity), not an integrated delta -- matching a continuous-axis input device.
    """

    def __init__(self, config: KeyboardToSe3RelRetargeterConfig, name: str) -> None:
        self._config = config
        super().__init__(name=name)

    def input_spec(self) -> RetargeterIOType:
        return {"keyboard_all_keys": OptionalType(KeyboardAllKeysType())}

    def output_spec(self) -> RetargeterIOType:
        return {
            "ee_delta": TensorGroupType(
                "ee_delta",
                [
                    NDArrayType(
                        "delta", shape=(6,), dtype=DLDataType.FLOAT, dtype_bits=32
                    )
                ],
            )
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        ee_delta = outputs["ee_delta"]
        all_keys = inputs["keyboard_all_keys"]
        if all_keys.is_none:
            ee_delta[0] = np.zeros(6, dtype=np.float32)
            return

        bitmap = np.asarray(all_keys[0])
        pos_sens = self._config.pos_sensitivity
        rot_sens = self._config.rot_sensitivity

        delta_pos = np.zeros(3)
        delta_pos[0] += pos_sens if bitmap[EvdevKeyCode.KEY_W] else 0.0
        delta_pos[0] -= pos_sens if bitmap[EvdevKeyCode.KEY_S] else 0.0
        delta_pos[1] += pos_sens if bitmap[EvdevKeyCode.KEY_A] else 0.0
        delta_pos[1] -= pos_sens if bitmap[EvdevKeyCode.KEY_D] else 0.0
        delta_pos[2] += pos_sens if bitmap[EvdevKeyCode.KEY_Q] else 0.0
        delta_pos[2] -= pos_sens if bitmap[EvdevKeyCode.KEY_E] else 0.0

        delta_euler = np.zeros(3)
        delta_euler[0] += rot_sens if bitmap[EvdevKeyCode.KEY_Z] else 0.0
        delta_euler[0] -= rot_sens if bitmap[EvdevKeyCode.KEY_X] else 0.0
        delta_euler[1] += rot_sens if bitmap[EvdevKeyCode.KEY_T] else 0.0
        delta_euler[1] -= rot_sens if bitmap[EvdevKeyCode.KEY_G] else 0.0
        delta_euler[2] += rot_sens if bitmap[EvdevKeyCode.KEY_C] else 0.0
        delta_euler[2] -= rot_sens if bitmap[EvdevKeyCode.KEY_V] else 0.0

        delta_rot = Rotation.from_euler("XYZ", delta_euler).as_rotvec()

        ee_delta[0] = np.concatenate([delta_pos, delta_rot]).astype(np.float32)


class KeyboardGripperRetargeter(BaseRetargeter):
    """
    Toggles a gripper open/closed state on each press of the K key.

    Consumes ``keyboard_pressed`` (keys with a press event this frame), so a tap shorter
    than a frame still toggles and a key held across frames or across a reset never
    re-toggles -- no edge state to keep.

    Output matches GripperRetargeter's convention: -1.0 when closed, 1.0 when open.
    """

    def __init__(self, name: str) -> None:
        super().__init__(name=name)
        self._closed = False

    def input_spec(self) -> RetargeterIOType:
        return {"keyboard_pressed": OptionalType(KeyboardPressedType())}

    def output_spec(self) -> RetargeterIOType:
        return {
            "gripper_command": TensorGroupType(
                "gripper_command", [FloatType("command")]
            )
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        gripper_out = outputs["gripper_command"]
        pressed = inputs["keyboard_pressed"]

        if context.execution_events.reset:
            # A press landing on the reset frame is consumed by the reset.
            self._closed = False
        elif not pressed.is_none and np.asarray(pressed[0])[EvdevKeyCode.KEY_K]:
            self._closed = not self._closed

        gripper_out[0] = -1.0 if self._closed else 1.0
