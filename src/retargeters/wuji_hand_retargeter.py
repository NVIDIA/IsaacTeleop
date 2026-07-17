# SPDX-FileCopyrightText: Copyright (c) 2026 Wuji Technology. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Wuji Hand Retargeter Module.

Thin wrapper around ``wuji_sdk.retargeting.RetargetSession`` that adapts Teleop's
OpenXR hand-tracking input format (26-joint ``HandInput``) to the MediaPipe
21-joint layout the Wuji retarget session expects, runs the session, and writes
the resulting 20 finger DOFs into Teleop's ``TensorGroup`` output.

``RetargetSession.for_hand(...)`` selects the builtin tuning config internally, so
there is no config path or URDF to manage. The session keeps warm-start +
smoothing state across frames, so it is built once (a heavy, multi-second call)
and reused; ``reset()`` is called after a tracking gap.

Requires ``isaacteleop[wuji]`` → ``wuji-sdk[retarget]``.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
from wuji_sdk import Handedness, retargeting

from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    OptionalType,
    RetargeterIOType,
    TensorGroupType,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import RetargeterIO
from isaacteleop.retargeting_engine.tensor_types import (
    FloatType,
    HandInput,
    HandInputIndex,
    HandJointIndex,
)

logger = logging.getLogger(__name__)

# OpenXR (26 joints) -> MediaPipe (21 joints) index mapping.
# Skips OpenXR palm(0) and the non-thumb metacarpal joints. The MediaPipe
# 21-landmark order (wrist, thumb 1-4, index 1-4, middle 1-4, ring 1-4,
# pinky 1-4) is identical to the MANO 21-joint order, so this is the same
# table the Sharpa retargeter uses.
OPENXR_TO_MEDIAPIPE_INDICES: list[int] = [
    HandJointIndex.WRIST,
    HandJointIndex.THUMB_METACARPAL,
    HandJointIndex.THUMB_PROXIMAL,
    HandJointIndex.THUMB_DISTAL,
    HandJointIndex.THUMB_TIP,
    HandJointIndex.INDEX_PROXIMAL,
    HandJointIndex.INDEX_INTERMEDIATE,
    HandJointIndex.INDEX_DISTAL,
    HandJointIndex.INDEX_TIP,
    HandJointIndex.MIDDLE_PROXIMAL,
    HandJointIndex.MIDDLE_INTERMEDIATE,
    HandJointIndex.MIDDLE_DISTAL,
    HandJointIndex.MIDDLE_TIP,
    HandJointIndex.RING_PROXIMAL,
    HandJointIndex.RING_INTERMEDIATE,
    HandJointIndex.RING_DISTAL,
    HandJointIndex.RING_TIP,
    HandJointIndex.LITTLE_PROXIMAL,
    HandJointIndex.LITTLE_INTERMEDIATE,
    HandJointIndex.LITTLE_DISTAL,
    HandJointIndex.LITTLE_TIP,
]

# RetargetSession.step() returns 20 values in firmware joint order: finger-major
# (thumb, index, middle, ring, pinky), 4 joints each. These default names label
# that order; override via WujiHandRetargeterConfig.hand_joint_names if a
# downstream consumer expects different names (same order, length 20).
_FINGERS = ("thumb", "index", "middle", "ring", "pinky")


def _default_joint_names() -> list[str]:
    return [f"{finger}_j{k}" for finger in _FINGERS for k in range(4)]


# wuji-sdk's for_hand is enum-only by design: a bare string raises TypeError
# (guards against silently parsing string args). Map the config's string fields
# to the SDK enums at the call site.
_HAND_MODELS = {
    "wuji_hand": retargeting.HandModel.WujiHand,
    "wuji_hand_2": retargeting.HandModel.WujiHand2,
}
_HANDEDNESS = {
    "left": Handedness.Left,
    "right": Handedness.Right,
}


@dataclass
class WujiHandRetargeterConfig:
    """Configuration for the Wuji hand retargeter.

    Attributes:
        model: Hand model passed to ``RetargetSession.for_hand`` —
            ``"wuji_hand"`` or ``"wuji_hand_2"``. Selects the builtin tuning
            config internally.
        hand_side: ``"left"`` or ``"right"`` (the retargeter's handedness basis).
        hand_joint_names: Optional output joint-name override (length 20, same
            firmware order). If ``None``, uses ``_default_joint_names()``.
    """

    model: str = "wuji_hand_2"
    hand_side: str = "right"
    hand_joint_names: Optional[list[str]] = None


class WujiHandRetargeter(BaseRetargeter):
    """Retargets OpenXR hand tracking to Wuji hand joint angles.

    Inputs:
        - ``hand_{side}``: OpenXR hand tracking data (26 joints), optional.

    Outputs:
        - ``hand_joints``: Wuji finger joint angles (20 DOFs, firmware order).
    """

    def __init__(self, config: WujiHandRetargeterConfig, name: str) -> None:
        self._config = config
        self._hand_side = config.hand_side.lower()
        if self._hand_side not in ("left", "right"):
            raise ValueError(
                f"hand_side must be 'left' or 'right', got: {self._hand_side}"
            )
        self._input_key = f"hand_{self._hand_side}"

        model = _HAND_MODELS.get(config.model)
        if model is None:
            raise ValueError(
                f"model must be one of {sorted(_HAND_MODELS)}, got: {config.model!r}"
            )

        # Heavy, multi-second build; done once and reused across frames.
        # for_hand is enum-only; hand_side is already validated to left/right above.
        self._session = retargeting.RetargetSession.for_hand(
            model, side=_HANDEDNESS[self._hand_side]
        )

        if config.hand_joint_names is None:
            self._hand_joint_names = _default_joint_names()
        else:
            if len(config.hand_joint_names) != 20:
                raise ValueError(
                    f"hand_joint_names must have length 20, got "
                    f"{len(config.hand_joint_names)}"
                )
            self._hand_joint_names = list(config.hand_joint_names)
        self._num_joints = len(self._hand_joint_names)

        super().__init__(name=name)

    def input_spec(self) -> RetargeterIOType:
        """Define input: optional hand tracking for the configured side."""
        return {self._input_key: OptionalType(HandInput())}

    def output_spec(self) -> RetargeterIOType:
        """Define output: Wuji finger joint angles (20 DOFs, firmware order)."""
        return {
            "hand_joints": TensorGroupType(
                f"hand_joints_{self._hand_side}",
                [FloatType(name) for name in self._hand_joint_names],
            )
        }

    def _emit_zeros(self, output_group) -> None:
        for i in range(self._num_joints):
            output_group[i] = 0.0
        # Drop warm-start / smoothing state so we restart cleanly next valid frame.
        self._session.reset()

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        output_group = outputs["hand_joints"]
        hand_group = inputs[self._input_key]

        # Honor an explicit reset event (e.g. session restart): drop session state.
        events = getattr(context, "execution_events", None)
        if events is not None and getattr(events, "reset", False):
            self._session.reset()

        if hand_group.is_none:
            self._emit_zeros(output_group)
            return

        joint_positions = np.from_dlpack(
            hand_group[HandInputIndex.JOINT_POSITIONS]
        )  # (26, 3)
        joint_valid = np.from_dlpack(hand_group[HandInputIndex.JOINT_VALID])  # (26,)

        if not all(bool(joint_valid[xr_idx]) for xr_idx in OPENXR_TO_MEDIAPIPE_INDICES):
            self._emit_zeros(output_group)
            return

        # OpenXR (26 joints) -> MediaPipe (21 joints, meters), positions only.
        mediapipe_kp = np.ascontiguousarray(
            joint_positions[OPENXR_TO_MEDIAPIPE_INDICES], dtype=np.float32
        )  # (21, 3)

        qpos = self._session.step(mediapipe_kp)  # (20,) firmware order

        for i in range(self._num_joints):
            output_group[i] = float(qpos[i])
