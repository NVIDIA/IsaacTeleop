# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tactile / haptic retargeters.

Two groups, both vendor-neutral:

* **Composable spatial primitives** (:class:`Vector3FrameTransform`,
  :class:`WorldForceAccumulator`, :class:`MagnitudeReducer`) operate on
  sim-side :func:`~isaacteleop.retargeting_engine.tensor_types.TactileVector`
  flows. They are the building blocks every per-device mapper composes with.

* **Per-device mappers** (:class:`TactileVectorToFingerPower`,
  :class:`TactileHeatmapToFingerPower`, :class:`TactileHeatmapToWristPulse`,
  :class:`TactileVectorToControllerPulse`,
  :class:`TactileHeatmapToControllerPulse`) translate sim-side tactile data
  into one of the device-side schemas declared in
  :mod:`~isaacteleop.retargeting_engine.tensor_types.tactile_types`. They are
  named after the target schema, not the vendor -- any vendor whose device
  accepts the same schema reuses the same mapper.

When the Haply force-feedback adapter lands, ``ContactForceToEndEffectorForce``
and ``TactileHeatmapToEndEffectorForce`` slot into this file with no
restructuring; they compose the same spatial primitives above.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.interface.parameter_state import ParameterState
from isaacteleop.retargeting_engine.interface.retargeter_core_types import RetargeterIO
from isaacteleop.retargeting_engine.interface.tunable_parameter import (
    FloatParameter,
    VectorParameter,
)
from isaacteleop.retargeting_engine.tensor_types import (
    ControllerHapticPulse,
    ControllerHapticPulseField,
    FingerPowerVector,
    NUM_CONTROLLER_HAPTIC_FIELDS,
    NUM_HAPTIC_FINGERS,
    TactileHeatmap,
    TactileVector,
    TransformMatrix,
)


# ============================================================================
# Composable spatial primitives (vendor-neutral)
# ============================================================================


class Vector3FrameTransform(BaseRetargeter):
    """Rotate a sim-frame :func:`TactileVector(3)` into a new frame.

    .. note::
        **Rotation-only.** This node is force-vector oriented: ``TactileVector(3)``
        is treated as a *free vector* (e.g. a contact force or torque),
        so the translation column of the input ``TransformMatrix`` is
        intentionally ignored and only the upper-left 3x3 rotation block is
        applied. To transform a *position* (where translation matters), use a
        full 4x4 affine multiply at a layer that knows the input is a point,
        not in this node.

    Inputs:
        - ``"vec"``: :func:`TactileVector(3) <isaacteleop.retargeting_engine.tensor_types.TactileVector>`
          (a 3-vector free quantity) in the source frame.
        - ``"transform"``: :func:`TransformMatrix <isaacteleop.retargeting_engine.tensor_types.TransformMatrix>`
          ``(4, 4)`` -- the source-to-target homogeneous transform; only the
          rotation block ``M[:3, :3]`` is read.

    Outputs:
        - ``"vec"``: :func:`TactileVector(3)` in the target frame.

    Used to compose Concern A (frame mismatch) of the tactile-haptic factoring
    described in the design doc. The ``"transform"`` input is typically the
    optional ``world_T_haptic`` :class:`~isaacteleop.retargeting_engine.interface.value_input.ValueInput`
    leaf fed by IsaacTeleopDevice when ``IsaacTeleopHapticCfg.haptic_device_frame_prim_path``
    is set, but any pipeline node producing a ``TransformMatrix`` is valid.
    """

    INPUT_VEC = "vec"
    INPUT_TRANSFORM = "transform"
    OUTPUT_VEC = "vec"

    def input_spec(self) -> RetargeterIOType:
        return {
            self.INPUT_VEC: TactileVector(3),
            self.INPUT_TRANSFORM: TransformMatrix(),
        }

    def output_spec(self) -> RetargeterIOType:
        return {self.OUTPUT_VEC: TactileVector(3)}

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        vec = np.asarray(inputs[self.INPUT_VEC][0], dtype=np.float32).reshape(3)
        matrix = np.asarray(inputs[self.INPUT_TRANSFORM][0], dtype=np.float32).reshape(
            4, 4
        )
        rotated = (matrix[:3, :3] @ vec).astype(np.float32)
        outputs[self.OUTPUT_VEC][0] = rotated


class WorldForceAccumulator(BaseRetargeter):
    """Sum N :func:`TactileVector(3)` inputs into one, with optional per-input weights.

    Inputs:
        - ``"in_0"``, ``"in_1"``, ... ``"in_{num_inputs - 1}"``: each a
          :func:`TactileVector(3) <isaacteleop.retargeting_engine.tensor_types.TactileVector>`
          in a common frame.

    Outputs:
        - ``"vec"``: :func:`TactileVector(3)` = sum of ``weights[i] * in_i``.

    Tunable parameters:
        - ``weights``: :class:`VectorParameter` of length ``num_inputs``
          (default: all ones). Exposed in the tuning UI so an operator can
          attenuate or zero out individual contributing bodies live.

    Useful upstream of :class:`Vector3FrameTransform` to combine forces from
    multiple sim contact sensors (e.g. left and right Franka fingers) before
    rotating into the device frame.
    """

    OUTPUT_VEC = "vec"

    def __init__(
        self,
        name: str,
        num_inputs: int,
        weights: np.ndarray | list[float] | None = None,
    ) -> None:
        if num_inputs < 1:
            raise ValueError(
                f"WorldForceAccumulator '{name}' requires num_inputs >= 1, got {num_inputs}"
            )
        self._num_inputs = num_inputs

        if weights is None:
            default_weights = np.ones(num_inputs, dtype=np.float32)
        else:
            default_weights = np.asarray(weights, dtype=np.float32).reshape(-1)
            if default_weights.shape[0] != num_inputs:
                raise ValueError(
                    f"WorldForceAccumulator '{name}': weights length "
                    f"{default_weights.shape[0]} does not match num_inputs {num_inputs}"
                )

        # synced into self._weights before each compute by BaseRetargeter
        self._weights: np.ndarray = default_weights.copy()

        param_state = ParameterState(
            name,
            [
                VectorParameter(
                    name="weights",
                    description="Per-input contribution weights (length num_inputs).",
                    element_names=[f"in_{i}" for i in range(num_inputs)],
                    default_value=default_weights,
                    sync_fn=lambda v: setattr(
                        self, "_weights", np.asarray(v, dtype=np.float32)
                    ),
                ),
            ],
        )
        super().__init__(name=name, parameter_state=param_state)

    def input_spec(self) -> RetargeterIOType:
        return {f"in_{i}": TactileVector(3) for i in range(self._num_inputs)}

    def output_spec(self) -> RetargeterIOType:
        return {self.OUTPUT_VEC: TactileVector(3)}

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        accumulated = np.zeros(3, dtype=np.float32)
        for i in range(self._num_inputs):
            arr = np.asarray(inputs[f"in_{i}"][0], dtype=np.float32).reshape(3)
            accumulated += float(self._weights[i]) * arr
        outputs[self.OUTPUT_VEC][0] = accumulated


_MagnitudeMode = Literal["norm", "axis_x", "axis_y", "axis_z"]


class MagnitudeReducer(BaseRetargeter):
    """Reduce a :func:`TactileVector(3)` to a :func:`TactileVector(1)` scalar.

    Inputs:
        - ``"vec"``: :func:`TactileVector(3) <isaacteleop.retargeting_engine.tensor_types.TactileVector>`.

    Outputs:
        - ``"scalar"``: :func:`TactileVector(1) <isaacteleop.retargeting_engine.tensor_types.TactileVector>`
          (the reduced magnitude).

    The reduction *mode* is fixed at construction time:

    * ``"norm"`` -- Euclidean length ``||vec||_2``.
    * ``"axis_x"`` / ``"axis_y"`` / ``"axis_z"`` -- absolute value of the
      corresponding component (use these after :class:`Vector3FrameTransform`
      when the device cares about pressure normal to a known axis).

    Used to bridge directional contact data (a 3-vector force) into the
    frame-invariant device schemas that only care about magnitude
    (:func:`FingerPowerVector`, :func:`ControllerHapticPulse`).

    .. note::
        The design doc lists the original mode set as
        ``{'norm', 'axis_z', 'dot_with_normal'}``. The ``axis_z`` mode is a
        special case of the per-axis modes shipped here (``axis_x`` /
        ``axis_y`` / ``axis_z``); ``dot_with_normal`` was deferred to a later
        change because it can be expressed as a pre-rotation via
        :class:`Vector3FrameTransform` plus ``axis_z``, and there is no v1
        consumer that needs it directly.
    """

    INPUT_VEC = "vec"
    OUTPUT_SCALAR = "scalar"

    def __init__(self, name: str, mode: _MagnitudeMode = "norm") -> None:
        if mode not in ("norm", "axis_x", "axis_y", "axis_z"):
            raise ValueError(
                f"MagnitudeReducer '{name}': unknown mode '{mode}'. "
                "Must be one of: 'norm', 'axis_x', 'axis_y', 'axis_z'."
            )
        self._mode = mode
        super().__init__(name=name)

    def input_spec(self) -> RetargeterIOType:
        return {self.INPUT_VEC: TactileVector(3)}

    def output_spec(self) -> RetargeterIOType:
        return {self.OUTPUT_SCALAR: TactileVector(1)}

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        vec = np.asarray(inputs[self.INPUT_VEC][0], dtype=np.float32).reshape(3)
        if self._mode == "norm":
            scalar = float(np.linalg.norm(vec))
        elif self._mode == "axis_x":
            scalar = float(abs(vec[0]))
        elif self._mode == "axis_y":
            scalar = float(abs(vec[1]))
        else:  # axis_z
            scalar = float(abs(vec[2]))
        outputs[self.OUTPUT_SCALAR][0] = np.array([scalar], dtype=np.float32)


# ============================================================================
# Helpers shared across per-device mappers
# ============================================================================


def _apply_gain_curve(
    raw: np.ndarray, gain: float, deadband: float, saturation: float
) -> np.ndarray:
    """Apply the standard gain / deadband / saturation curve, in [0, 1].

    1. Below ``deadband`` -> zero (suppresses noise).
    2. Above ``deadband`` -> ``gain * (raw - deadband)``.
    3. Clipped to ``[0, saturation]``.

    Always returns a non-negative float32 array of the input shape.
    """
    raw = np.asarray(raw, dtype=np.float32)
    deadbanded = np.maximum(0.0, raw - deadband)
    scaled = gain * deadbanded
    return np.clip(scaled, 0.0, saturation).astype(np.float32)


def _smooth_ema(prev: np.ndarray | None, new: np.ndarray, alpha: float) -> np.ndarray:
    """Exponential moving average smoothing. ``alpha`` is the new-sample weight."""
    if prev is None or prev.shape != new.shape:
        return new.copy()
    return (alpha * new + (1.0 - alpha) * prev).astype(np.float32)


# ============================================================================
# Per-device mappers -- target schema: FingerPowerVector
# ============================================================================


class TactileVectorToFingerPower(BaseRetargeter):
    """Map a per-taxel :func:`TactileVector` to a :func:`FingerPowerVector`.

    Inputs:
        - ``"tactile"``: :func:`TactileVector(num_taxels) <isaacteleop.retargeting_engine.tensor_types.TactileVector>`
          -- typically each taxel is the contact-force magnitude on one finger
          pad, but the mapping is configurable via ``finger_groups``.

    Outputs:
        - ``"powers"``: :func:`FingerPowerVector(num_fingers) <isaacteleop.retargeting_engine.tensor_types.FingerPowerVector>`
          in ``[0, 1]``.

    Per-finger reduction over the configured taxel indices is the configured
    ``reduction`` mode (``"max"``, ``"mean"``, or ``"sum"``). The result is
    passed through the standard gain / deadband / saturation curve and
    optionally EMA-smoothed.

    Tunable parameters (all surface in the tuning UI):
        - ``gain``: float, scales the post-deadband signal.
        - ``deadband``: float, suppresses signals below this magnitude.
        - ``saturation``: float, upper clamp (default 1.0, the Manus max).
        - ``smoothing``: float in [0, 1], EMA new-sample weight (1.0 = no smoothing).
    """

    INPUT_TACTILE = "tactile"
    OUTPUT_POWERS = "powers"

    def __init__(
        self,
        name: str,
        num_taxels: int,
        finger_groups: list[list[int]] | None = None,
        num_fingers: int = NUM_HAPTIC_FINGERS,
        reduction: Literal["max", "mean", "sum"] = "max",
        gain: float = 1.0,
        deadband: float = 0.0,
        saturation: float = 1.0,
        smoothing: float = 1.0,
    ) -> None:
        if num_taxels < 1:
            raise ValueError(
                f"TactileVectorToFingerPower '{name}' requires num_taxels >= 1"
            )
        if reduction not in ("max", "mean", "sum"):
            raise ValueError(
                f"TactileVectorToFingerPower '{name}': unknown reduction '{reduction}'"
            )

        self._num_taxels = num_taxels
        self._num_fingers = num_fingers
        self._reduction = reduction

        if finger_groups is None:
            if num_taxels != num_fingers:
                raise ValueError(
                    f"TactileVectorToFingerPower '{name}': finger_groups is required "
                    f"unless num_taxels ({num_taxels}) equals num_fingers ({num_fingers})."
                )
            finger_groups = [[i] for i in range(num_fingers)]
        if len(finger_groups) != num_fingers:
            raise ValueError(
                f"TactileVectorToFingerPower '{name}': finger_groups has "
                f"{len(finger_groups)} entries, expected {num_fingers}."
            )
        for fi, group in enumerate(finger_groups):
            for idx in group:
                if not (0 <= idx < num_taxels):
                    raise ValueError(
                        f"TactileVectorToFingerPower '{name}': finger_groups[{fi}] "
                        f"contains taxel index {idx} outside [0, {num_taxels})."
                    )
        self._finger_groups = [list(g) for g in finger_groups]

        # Synced from ParameterState before each compute by BaseRetargeter.
        self._gain = gain
        self._deadband = deadband
        self._saturation = saturation
        self._smoothing = smoothing
        self._smoothed: np.ndarray | None = None

        param_state = ParameterState(
            name,
            [
                FloatParameter(
                    name="gain",
                    description="Scale factor applied after the deadband.",
                    default_value=gain,
                    min_value=0.0,
                    max_value=100.0,
                    sync_fn=lambda v: setattr(self, "_gain", float(v)),
                ),
                FloatParameter(
                    name="deadband",
                    description="Signal magnitude below which output is zero.",
                    default_value=deadband,
                    min_value=0.0,
                    max_value=10.0,
                    sync_fn=lambda v: setattr(self, "_deadband", float(v)),
                ),
                FloatParameter(
                    name="saturation",
                    description="Maximum per-finger power (Manus clamps at 1.0).",
                    default_value=saturation,
                    min_value=0.0,
                    max_value=1.0,
                    sync_fn=lambda v: setattr(self, "_saturation", float(v)),
                ),
                FloatParameter(
                    name="smoothing",
                    description="EMA new-sample weight in [0,1]. 1.0 = no smoothing.",
                    default_value=smoothing,
                    min_value=0.0,
                    max_value=1.0,
                    sync_fn=lambda v: setattr(self, "_smoothing", float(v)),
                ),
            ],
        )
        super().__init__(name=name, parameter_state=param_state)

    def input_spec(self) -> RetargeterIOType:
        return {self.INPUT_TACTILE: TactileVector(self._num_taxels)}

    def output_spec(self) -> RetargeterIOType:
        return {self.OUTPUT_POWERS: FingerPowerVector(self._num_fingers)}

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        if context.execution_events.reset:
            self._smoothed = None

        raw = np.asarray(inputs[self.INPUT_TACTILE][0], dtype=np.float32).reshape(
            self._num_taxels
        )

        per_finger = np.zeros(self._num_fingers, dtype=np.float32)
        for fi, group in enumerate(self._finger_groups):
            slice_ = raw[group]
            if self._reduction == "max":
                per_finger[fi] = float(np.max(slice_)) if slice_.size else 0.0
            elif self._reduction == "mean":
                per_finger[fi] = float(np.mean(slice_)) if slice_.size else 0.0
            else:  # sum
                per_finger[fi] = float(np.sum(slice_))

        shaped = _apply_gain_curve(
            per_finger, self._gain, self._deadband, self._saturation
        )
        self._smoothed = _smooth_ema(self._smoothed, shaped, self._smoothing)
        outputs[self.OUTPUT_POWERS][0] = self._smoothed.copy()


class TactileHeatmapToFingerPower(BaseRetargeter):
    """Reduce a :func:`TactileHeatmap` to a :func:`FingerPowerVector`, one finger per pad.

    Inputs:
        - ``"heatmap"``: :func:`TactileHeatmap(rows, cols, num_pads) <isaacteleop.retargeting_engine.tensor_types.TactileHeatmap>`
          with ``num_pads == num_fingers``.

    Outputs:
        - ``"powers"``: :func:`FingerPowerVector(num_fingers) <isaacteleop.retargeting_engine.tensor_types.FingerPowerVector>`.

    Each ``(rows, cols)`` pad is reduced to one scalar via the configured
    ``reduction`` (``"max"``, ``"mean"``, or ``"sum"``), then run through the
    standard gain / deadband / saturation curve and optionally EMA-smoothed.

    Tunable parameters: ``gain``, ``deadband``, ``saturation``, ``smoothing``.
    """

    INPUT_HEATMAP = "heatmap"
    OUTPUT_POWERS = "powers"

    def __init__(
        self,
        name: str,
        rows: int,
        cols: int,
        num_pads: int = NUM_HAPTIC_FINGERS,
        reduction: Literal["max", "mean", "sum"] = "max",
        gain: float = 1.0,
        deadband: float = 0.0,
        saturation: float = 1.0,
        smoothing: float = 1.0,
    ) -> None:
        if reduction not in ("max", "mean", "sum"):
            raise ValueError(
                f"TactileHeatmapToFingerPower '{name}': unknown reduction '{reduction}'"
            )
        self._rows = rows
        self._cols = cols
        self._num_pads = num_pads
        self._reduction = reduction

        self._gain = gain
        self._deadband = deadband
        self._saturation = saturation
        self._smoothing = smoothing
        self._smoothed: np.ndarray | None = None

        param_state = ParameterState(
            name,
            [
                FloatParameter(
                    name="gain",
                    description="Scale factor applied after the deadband.",
                    default_value=gain,
                    min_value=0.0,
                    max_value=100.0,
                    sync_fn=lambda v: setattr(self, "_gain", float(v)),
                ),
                FloatParameter(
                    name="deadband",
                    description="Pad-reduced magnitude below which output is zero.",
                    default_value=deadband,
                    min_value=0.0,
                    max_value=10.0,
                    sync_fn=lambda v: setattr(self, "_deadband", float(v)),
                ),
                FloatParameter(
                    name="saturation",
                    description="Maximum per-finger power.",
                    default_value=saturation,
                    min_value=0.0,
                    max_value=1.0,
                    sync_fn=lambda v: setattr(self, "_saturation", float(v)),
                ),
                FloatParameter(
                    name="smoothing",
                    description="EMA new-sample weight in [0,1]. 1.0 = no smoothing.",
                    default_value=smoothing,
                    min_value=0.0,
                    max_value=1.0,
                    sync_fn=lambda v: setattr(self, "_smoothing", float(v)),
                ),
            ],
        )
        super().__init__(name=name, parameter_state=param_state)

    def input_spec(self) -> RetargeterIOType:
        return {
            self.INPUT_HEATMAP: TactileHeatmap(self._rows, self._cols, self._num_pads)
        }

    def output_spec(self) -> RetargeterIOType:
        return {self.OUTPUT_POWERS: FingerPowerVector(self._num_pads)}

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        if context.execution_events.reset:
            self._smoothed = None

        heatmap = np.asarray(inputs[self.INPUT_HEATMAP][0], dtype=np.float32).reshape(
            self._num_pads, self._rows, self._cols
        )

        if self._reduction == "max":
            per_pad = heatmap.max(axis=(1, 2))
        elif self._reduction == "mean":
            per_pad = heatmap.mean(axis=(1, 2))
        else:  # sum
            per_pad = heatmap.sum(axis=(1, 2))

        shaped = _apply_gain_curve(
            per_pad.astype(np.float32),
            self._gain,
            self._deadband,
            self._saturation,
        )
        self._smoothed = _smooth_ema(self._smoothed, shaped, self._smoothing)
        outputs[self.OUTPUT_POWERS][0] = self._smoothed.copy()


class TactileHeatmapToWristPulse(BaseRetargeter):
    """Collapse a full :func:`TactileHeatmap` to a single scalar.

    Inputs:
        - ``"heatmap"``: :func:`TactileHeatmap(rows, cols, num_pads) <isaacteleop.retargeting_engine.tensor_types.TactileHeatmap>`.

    Outputs:
        - ``"power"``: :func:`FingerPowerVector(1) <isaacteleop.retargeting_engine.tensor_types.FingerPowerVector>`
          (single-channel power; reused here for wrist-only devices to avoid
          introducing a v1 schema with no concrete consumer).

    Reduction is over the entire ``(num_pads, rows, cols)`` array via
    ``"max"``, ``"mean"``, or ``"sum"``. Standard gain / deadband / saturation
    curve and EMA smoothing follow.
    """

    INPUT_HEATMAP = "heatmap"
    OUTPUT_POWER = "power"

    def __init__(
        self,
        name: str,
        rows: int,
        cols: int,
        num_pads: int = 1,
        reduction: Literal["max", "mean", "sum"] = "max",
        gain: float = 1.0,
        deadband: float = 0.0,
        saturation: float = 1.0,
        smoothing: float = 1.0,
    ) -> None:
        if reduction not in ("max", "mean", "sum"):
            raise ValueError(
                f"TactileHeatmapToWristPulse '{name}': unknown reduction '{reduction}'"
            )
        self._rows = rows
        self._cols = cols
        self._num_pads = num_pads
        self._reduction = reduction

        self._gain = gain
        self._deadband = deadband
        self._saturation = saturation
        self._smoothing = smoothing
        self._smoothed: np.ndarray | None = None

        param_state = ParameterState(
            name,
            [
                FloatParameter(
                    name="gain",
                    description="Scale factor applied after the deadband.",
                    default_value=gain,
                    min_value=0.0,
                    max_value=100.0,
                    sync_fn=lambda v: setattr(self, "_gain", float(v)),
                ),
                FloatParameter(
                    name="deadband",
                    description="Pulse magnitude below which output is zero.",
                    default_value=deadband,
                    min_value=0.0,
                    max_value=10.0,
                    sync_fn=lambda v: setattr(self, "_deadband", float(v)),
                ),
                FloatParameter(
                    name="saturation",
                    description="Maximum pulse magnitude.",
                    default_value=saturation,
                    min_value=0.0,
                    max_value=1.0,
                    sync_fn=lambda v: setattr(self, "_saturation", float(v)),
                ),
                FloatParameter(
                    name="smoothing",
                    description="EMA new-sample weight in [0,1]. 1.0 = no smoothing.",
                    default_value=smoothing,
                    min_value=0.0,
                    max_value=1.0,
                    sync_fn=lambda v: setattr(self, "_smoothing", float(v)),
                ),
            ],
        )
        super().__init__(name=name, parameter_state=param_state)

    def input_spec(self) -> RetargeterIOType:
        return {
            self.INPUT_HEATMAP: TactileHeatmap(self._rows, self._cols, self._num_pads)
        }

    def output_spec(self) -> RetargeterIOType:
        return {self.OUTPUT_POWER: FingerPowerVector(1)}

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        if context.execution_events.reset:
            self._smoothed = None

        heatmap = np.asarray(inputs[self.INPUT_HEATMAP][0], dtype=np.float32)

        if self._reduction == "max":
            scalar = float(heatmap.max()) if heatmap.size else 0.0
        elif self._reduction == "mean":
            scalar = float(heatmap.mean()) if heatmap.size else 0.0
        else:  # sum
            scalar = float(heatmap.sum())

        shaped = _apply_gain_curve(
            np.array([scalar], dtype=np.float32),
            self._gain,
            self._deadband,
            self._saturation,
        )
        self._smoothed = _smooth_ema(self._smoothed, shaped, self._smoothing)
        outputs[self.OUTPUT_POWER][0] = self._smoothed.copy()


# ============================================================================
# Per-device mappers -- target schema: ControllerHapticPulse
# ============================================================================


class TactileVectorToControllerPulse(BaseRetargeter):
    """Reduce a per-taxel :func:`TactileVector` to one :func:`ControllerHapticPulse`.

    Covers the canonical "G1 grip-pressure -> Quest controller rumble" case:
    each taxel is the contact-force magnitude on one fingertip; one pulse per
    hand summarises the contact state.

    Inputs:
        - ``"tactile"``: :func:`TactileVector(num_taxels) <isaacteleop.retargeting_engine.tensor_types.TactileVector>`.

    Outputs:
        - ``"pulse"``: :func:`ControllerHapticPulse <isaacteleop.retargeting_engine.tensor_types.ControllerHapticPulse>`
          = ``[amplitude, frequency_hz, duration_s]``.

    The taxels are reduced to a single magnitude via ``reduction``
    (``"max"``, ``"mean"``, ``"sum"``), passed through the gain / deadband /
    saturation curve to become ``amplitude`` in ``[0, saturation]``, then
    paired with constant ``frequency_hz`` / ``duration_s`` parameters. Both
    default to ``0.0`` so every conformant OpenXR runtime is free to pick
    ``XR_FREQUENCY_UNSPECIFIED`` and ``XR_MIN_HAPTIC_DURATION``.

    Tunable parameters: ``gain``, ``deadband``, ``saturation``,
    ``frequency_hz``, ``duration_s``.

    .. note::
        Unlike :class:`TactileVectorToFingerPower`, this mapper has no
        ``smoothing`` parameter. ``xrApplyHapticFeedback`` already supersedes
        any in-flight pulse on the same action every frame, so the runtime
        sees a fresh amplitude each step. EMA-smoothing the amplitude in
        Python before that overwrite would just shift the latency without
        meaningfully shaping the felt vibration, so the parameter is
        intentionally omitted. Add an upstream low-pass retargeter on the
        :class:`TactileVector` input if you need temporal shaping.
    """

    INPUT_TACTILE = "tactile"
    OUTPUT_PULSE = "pulse"

    def __init__(
        self,
        name: str,
        num_taxels: int,
        reduction: Literal["max", "mean", "sum"] = "max",
        gain: float = 1.0,
        deadband: float = 0.0,
        saturation: float = 1.0,
        frequency_hz: float = 0.0,
        duration_s: float = 0.0,
    ) -> None:
        if reduction not in ("max", "mean", "sum"):
            raise ValueError(
                f"TactileVectorToControllerPulse '{name}': unknown reduction '{reduction}'"
            )
        self._num_taxels = num_taxels
        self._reduction = reduction

        self._gain = gain
        self._deadband = deadband
        self._saturation = saturation
        self._frequency_hz = frequency_hz
        self._duration_s = duration_s

        param_state = ParameterState(
            name,
            [
                FloatParameter(
                    name="gain",
                    description="Scale factor applied after the deadband.",
                    default_value=gain,
                    min_value=0.0,
                    max_value=100.0,
                    sync_fn=lambda v: setattr(self, "_gain", float(v)),
                ),
                FloatParameter(
                    name="deadband",
                    description="Amplitude below which the pulse is suppressed.",
                    default_value=deadband,
                    min_value=0.0,
                    max_value=10.0,
                    sync_fn=lambda v: setattr(self, "_deadband", float(v)),
                ),
                FloatParameter(
                    name="saturation",
                    description="Maximum pulse amplitude in [0, 1].",
                    default_value=saturation,
                    min_value=0.0,
                    max_value=1.0,
                    sync_fn=lambda v: setattr(self, "_saturation", float(v)),
                ),
                FloatParameter(
                    name="frequency_hz",
                    description="OpenXR pulse frequency [Hz]. 0 = XR_FREQUENCY_UNSPECIFIED.",
                    default_value=frequency_hz,
                    min_value=0.0,
                    max_value=1000.0,
                    sync_fn=lambda v: setattr(self, "_frequency_hz", float(v)),
                ),
                FloatParameter(
                    name="duration_s",
                    description="OpenXR pulse duration [s]. 0 = XR_MIN_HAPTIC_DURATION.",
                    default_value=duration_s,
                    min_value=0.0,
                    max_value=10.0,
                    sync_fn=lambda v: setattr(self, "_duration_s", float(v)),
                ),
            ],
        )
        super().__init__(name=name, parameter_state=param_state)

    def input_spec(self) -> RetargeterIOType:
        return {self.INPUT_TACTILE: TactileVector(self._num_taxels)}

    def output_spec(self) -> RetargeterIOType:
        return {self.OUTPUT_PULSE: ControllerHapticPulse()}

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        raw = np.asarray(inputs[self.INPUT_TACTILE][0], dtype=np.float32).reshape(
            self._num_taxels
        )

        if self._reduction == "max":
            scalar = float(raw.max()) if raw.size else 0.0
        elif self._reduction == "mean":
            scalar = float(raw.mean()) if raw.size else 0.0
        else:  # sum
            scalar = float(raw.sum())

        amplitude = float(
            _apply_gain_curve(
                np.array([scalar], dtype=np.float32),
                self._gain,
                self._deadband,
                self._saturation,
            )[0]
        )

        pulse = np.zeros(NUM_CONTROLLER_HAPTIC_FIELDS, dtype=np.float32)
        pulse[ControllerHapticPulseField.AMPLITUDE] = amplitude
        pulse[ControllerHapticPulseField.FREQUENCY_HZ] = self._frequency_hz
        pulse[ControllerHapticPulseField.DURATION_S] = self._duration_s
        outputs[self.OUTPUT_PULSE][0] = pulse


class TactileHeatmapToControllerPulse(BaseRetargeter):
    """Collapse a :func:`TactileHeatmap` to one :func:`ControllerHapticPulse`.

    Same tunables and semantics as :class:`TactileVectorToControllerPulse`;
    the only difference is the input schema. The full
    ``(num_pads, rows, cols)`` heatmap is reduced to one scalar via the
    chosen ``reduction``.

    Like :class:`TactileVectorToControllerPulse`, this mapper has no
    ``smoothing`` parameter on purpose -- see that class's note.
    """

    INPUT_HEATMAP = "heatmap"
    OUTPUT_PULSE = "pulse"

    def __init__(
        self,
        name: str,
        rows: int,
        cols: int,
        num_pads: int = 1,
        reduction: Literal["max", "mean", "sum"] = "max",
        gain: float = 1.0,
        deadband: float = 0.0,
        saturation: float = 1.0,
        frequency_hz: float = 0.0,
        duration_s: float = 0.0,
    ) -> None:
        if reduction not in ("max", "mean", "sum"):
            raise ValueError(
                f"TactileHeatmapToControllerPulse '{name}': unknown reduction '{reduction}'"
            )
        self._rows = rows
        self._cols = cols
        self._num_pads = num_pads
        self._reduction = reduction

        self._gain = gain
        self._deadband = deadband
        self._saturation = saturation
        self._frequency_hz = frequency_hz
        self._duration_s = duration_s

        param_state = ParameterState(
            name,
            [
                FloatParameter(
                    name="gain",
                    description="Scale factor applied after the deadband.",
                    default_value=gain,
                    min_value=0.0,
                    max_value=100.0,
                    sync_fn=lambda v: setattr(self, "_gain", float(v)),
                ),
                FloatParameter(
                    name="deadband",
                    description="Amplitude below which the pulse is suppressed.",
                    default_value=deadband,
                    min_value=0.0,
                    max_value=10.0,
                    sync_fn=lambda v: setattr(self, "_deadband", float(v)),
                ),
                FloatParameter(
                    name="saturation",
                    description="Maximum pulse amplitude in [0, 1].",
                    default_value=saturation,
                    min_value=0.0,
                    max_value=1.0,
                    sync_fn=lambda v: setattr(self, "_saturation", float(v)),
                ),
                FloatParameter(
                    name="frequency_hz",
                    description="OpenXR pulse frequency [Hz]. 0 = XR_FREQUENCY_UNSPECIFIED.",
                    default_value=frequency_hz,
                    min_value=0.0,
                    max_value=1000.0,
                    sync_fn=lambda v: setattr(self, "_frequency_hz", float(v)),
                ),
                FloatParameter(
                    name="duration_s",
                    description="OpenXR pulse duration [s]. 0 = XR_MIN_HAPTIC_DURATION.",
                    default_value=duration_s,
                    min_value=0.0,
                    max_value=10.0,
                    sync_fn=lambda v: setattr(self, "_duration_s", float(v)),
                ),
            ],
        )
        super().__init__(name=name, parameter_state=param_state)

    def input_spec(self) -> RetargeterIOType:
        return {
            self.INPUT_HEATMAP: TactileHeatmap(self._rows, self._cols, self._num_pads)
        }

    def output_spec(self) -> RetargeterIOType:
        return {self.OUTPUT_PULSE: ControllerHapticPulse()}

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        heatmap = np.asarray(inputs[self.INPUT_HEATMAP][0], dtype=np.float32)
        if self._reduction == "max":
            scalar = float(heatmap.max()) if heatmap.size else 0.0
        elif self._reduction == "mean":
            scalar = float(heatmap.mean()) if heatmap.size else 0.0
        else:  # sum
            scalar = float(heatmap.sum())

        amplitude = float(
            _apply_gain_curve(
                np.array([scalar], dtype=np.float32),
                self._gain,
                self._deadband,
                self._saturation,
            )[0]
        )

        pulse = np.zeros(NUM_CONTROLLER_HAPTIC_FIELDS, dtype=np.float32)
        pulse[ControllerHapticPulseField.AMPLITUDE] = amplitude
        pulse[ControllerHapticPulseField.FREQUENCY_HZ] = self._frequency_hz
        pulse[ControllerHapticPulseField.DURATION_S] = self._duration_s
        outputs[self.OUTPUT_PULSE][0] = pulse
