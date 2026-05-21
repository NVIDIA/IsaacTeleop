# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
TensorGroupType definitions for tactile feedback and haptic output.

Sim-side schemas (TactileVector, TactileHeatmap) carry contact / pressure data
from simulators (e.g. Isaac Lab's ContactSensor) into the retargeting pipeline.
Device-side schemas (FingerPowerVector, ControllerHapticPulse, EndEffectorForce)
describe what a haptic device adapter will accept.

Retargeters map sim-side -> device-side schemas; vendor adapters implementing
``isaacteleop.haptic_devices.IHapticDevice`` declare which device-side schema
they accept via ``accepted_type()`` and the ``HapticSink`` retargeter uses that
for connect-time type checking.

The existing :func:`TransformMatrix` factory in ``standard_types`` is reused
unchanged for the optional ``world_T_haptic`` frame leaf -- no new transform
schema is introduced here.
"""

from ..interface.tensor_group_type import TensorGroupType
from .ndarray_types import NDArrayType, DLDataType


# Constants
NUM_HAPTIC_FINGERS = 5
"""Number of fingers in a :func:`FingerPowerVector`.

Manus / OpenXR-glove convention: Thumb, Index, Middle, Ring, Pinky.
"""

NUM_CONTROLLER_HAPTIC_FIELDS = 3
"""Fields in a :func:`ControllerHapticPulse`: ``[amplitude, frequency_hz, duration_s]``."""

NUM_END_EFFECTOR_FORCE_AXES = 3
"""Components in an :func:`EndEffectorForce`: ``[fx, fy, fz]``."""


# ============================================================================
# Sim-side types
# ============================================================================


def TactileVector(num_taxels: int) -> TensorGroupType:
    """Per-taxel scalar magnitudes (or N-element vector) [N, depending on use].

    Generic sim-side schema for tactile / contact data. The same type covers:

    * a single contact force magnitude (``num_taxels == 1``),
    * a row of taxels on a finger pad (``num_taxels == N``),
    * a 3-vector force or 3-vector position (``num_taxels == 3``) used by the
      composable spatial primitives (e.g. :class:`Vector3FrameTransform`).

    The semantic meaning of each entry is set by the retargeter consuming
    this group; this schema only fixes shape and dtype.

    Args:
        num_taxels: Number of scalar entries.

    Returns:
        TensorGroupType with one ``(num_taxels,) float32`` tensor.
    """
    return TensorGroupType(
        f"tactile_vector_{num_taxels}",
        [
            NDArrayType(
                "tactile_values",
                shape=(num_taxels,),
                dtype=DLDataType.FLOAT,
                dtype_bits=32,
            ),
        ],
    )


def TactileHeatmap(rows: int, cols: int, num_pads: int = 1) -> TensorGroupType:
    """2D pressure grid per pad [Pa or unitless, depending on consumer].

    Sim-side schema for heatmap-style tactile sensors (e.g. Sharpa TacMap).
    Shape is ``(num_pads, rows, cols)`` so a single pad is still a 3D array
    with leading dimension 1.

    Args:
        rows: Rows per pad.
        cols: Columns per pad.
        num_pads: Number of independent pads, e.g. 5 for one pad per finger.

    Returns:
        TensorGroupType with one ``(num_pads, rows, cols) float32`` tensor.
    """
    return TensorGroupType(
        f"tactile_heatmap_{num_pads}x{rows}x{cols}",
        [
            NDArrayType(
                "tactile_pressure",
                shape=(num_pads, rows, cols),
                dtype=DLDataType.FLOAT,
                dtype_bits=32,
            ),
        ],
    )


# ============================================================================
# Device-side types
# ============================================================================


def FingerPowerVector(num_fingers: int = NUM_HAPTIC_FINGERS) -> TensorGroupType:
    """Per-finger vibration intensities [unitless, 0..1].

    Device-side schema for vibration-glove output. Manus order:
    ``[Thumb, Index, Middle, Ring, Pinky]`` (see :class:`FingerIndex` for the
    indices).

    Consumed by :class:`isaacteleop.haptic_devices.ManusHapticDevice`.

    Args:
        num_fingers: Number of finger channels. Defaults to 5 (Manus).

    Returns:
        TensorGroupType with one ``(num_fingers,) float32`` tensor.
    """
    return TensorGroupType(
        f"finger_power_vector_{num_fingers}",
        [
            NDArrayType(
                "finger_power",
                shape=(num_fingers,),
                dtype=DLDataType.FLOAT,
                dtype_bits=32,
            ),
        ],
    )


def ControllerHapticPulse() -> TensorGroupType:
    """One-frame OpenXR motion-controller pulse ``[amplitude, frequency_hz, duration_s]``.

    Fields, in order (see :class:`ControllerHapticPulseField`):

    * ``amplitude`` [unitless, 0..1] -- 0 stops any active pulse via
      :c:func:`xrStopHapticFeedback`.
    * ``frequency_hz`` [Hz] -- ``0.0`` selects ``XR_FREQUENCY_UNSPECIFIED``
      (the runtime's default frequency).
    * ``duration_s`` [s] -- ``0.0`` selects ``XR_MIN_HAPTIC_DURATION``
      (the shortest pulse the runtime supports).

    Maps directly to ``XrHapticVibration``. Consumed by
    :class:`isaacteleop.haptic_devices.OpenXRControllerHapticDevice`.
    """
    return TensorGroupType(
        "controller_haptic_pulse",
        [
            NDArrayType(
                "haptic_pulse",
                shape=(NUM_CONTROLLER_HAPTIC_FIELDS,),
                dtype=DLDataType.FLOAT,
                dtype_bits=32,
            ),
        ],
    )


def EndEffectorForce() -> TensorGroupType:
    """3-DoF directional force at a single point ``[fx, fy, fz]`` [N].

    Device-side schema for grounded-haptic devices like the Haply Inverse3.
    Components are in the *device* frame -- spatial retargeters upstream of
    the :class:`HapticSink` rotate sim-frame forces into device frame via the
    optional ``world_T_haptic`` ValueInput leaf and :class:`Vector3FrameTransform`.

    Shipped in v1 (no v1 device consumes it) so the schema set is stable when
    the Haply force-feedback adapter lands.
    """
    return TensorGroupType(
        "end_effector_force",
        [
            NDArrayType(
                "force",
                shape=(NUM_END_EFFECTOR_FORCE_AXES,),
                dtype=DLDataType.FLOAT,
                dtype_bits=32,
            ),
        ],
    )
