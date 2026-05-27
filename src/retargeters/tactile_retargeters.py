# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tactile / haptic retargeters (vendor-neutral).

Two groups:

* **Composable spatial primitives** -- :class:`Vector3FrameTransform`,
  :class:`WorldForceAccumulator`, :class:`MagnitudeReducer` -- operating on
  sim-side ``TactileVector`` flows.
* **Per-device mappers** -- ``Tactile{Vector,Heatmap}ToControllerPulse`` --
  named after the target device-side schema, not the vendor.
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
    NUM_CONTROLLER_HAPTIC_FIELDS,
    TactileHeatmap,
    TactileVector,
    TransformMatrix,
)


# ============================================================================
# Composable spatial primitives (vendor-neutral)
# ============================================================================


class Vector3FrameTransform(BaseRetargeter):
    """Rotate a sim-frame ``TactileVector(3)`` into a new frame (rotation only).

    Treats the input as a free vector (e.g. a contact force / torque) and
    applies only the upper-left 3x3 of the input ``TransformMatrix``; the
    translation column is intentionally ignored. Use a full 4x4 affine
    multiply elsewhere if the value is a position.

    Inputs:
        - ``"vec"``: ``TactileVector(3)`` in the source frame.
        - ``"transform"``: ``TransformMatrix`` (4x4); only ``M[:3, :3]`` is read.

    Outputs:
        - ``"vec"``: ``TactileVector(3)`` in the target frame.
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
    """Weighted sum of N ``TactileVector(3)`` inputs in a common frame.

    Tunable ``weights`` (``VectorParameter`` of length ``num_inputs``, default
    all ones) lets an operator attenuate or zero out individual contributing
    bodies from the tuning UI.

    Inputs: ``"in_0"`` ... ``"in_{num_inputs - 1}"`` -- each ``TactileVector(3)``.
    Outputs: ``"vec"`` -- sum of ``weights[i] * in_i``.
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
    """Reduce a ``TactileVector(3)`` to a ``TactileVector(1)`` scalar.

    Bridges directional contact data into frame-invariant device schemas
    such as ``ControllerHapticPulse``. Mode is fixed at construction:

    * ``"norm"`` -- Euclidean length ``||vec||_2``.
    * ``"axis_x"`` / ``"axis_y"`` / ``"axis_z"`` -- absolute value of the
      corresponding component (typically chained after a
      ``Vector3FrameTransform`` when the device cares about pressure normal
      to a known axis).
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
    paired with constant ``frequency_hz`` / ``duration_s`` parameters
    (defaults ``0.0`` map to ``XR_FREQUENCY_UNSPECIFIED`` /
    ``XR_MIN_HAPTIC_DURATION`` on the runtime).

    Tunable parameters: ``gain``, ``deadband``, ``saturation``,
    ``frequency_hz``, ``duration_s``. No ``smoothing`` parameter:
    ``xrApplyHapticFeedback`` supersedes any in-flight pulse every frame, so
    EMA-smoothing in Python only shifts latency. Add an upstream low-pass
    retargeter on the ``TactileVector`` input if you need temporal shaping.
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
