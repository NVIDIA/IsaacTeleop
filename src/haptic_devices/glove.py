# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Haptic-glove adapter — the cross-process device reference for gloves.

A vibration glove is a cross-process device: the vendor SDK runs in its own
plugin process and reads per-finger powers off a push-tensor collection. On
the Isaac Teleop side the glove is therefore just a
:class:`~isaacteleop.haptic_devices.push_tensor.PushTensorHapticDevice`
configured to accept a
:func:`~isaacteleop.retargeting_engine.tensor_types.FingerPowerVector`.
:func:`haptic_glove_device` is the named constructor for that configuration, so
glove integrators get a discoverable entry point without needing to know the
generic push device exists.
"""

from __future__ import annotations

from typing import Iterable

from isaacteleop.retargeting_engine.tensor_types import (
    FingerPowerVector,
    NUM_HAPTIC_FINGERS,
)

from .interface import Endpoint
from .push_tensor import PushTensorHapticDevice


def haptic_glove_device(
    collection_id: str,
    *,
    num_fingers: int = NUM_HAPTIC_FINGERS,
    endpoints: Iterable[Endpoint] = ("left", "right"),
    tensor_identifier: str = "haptic_command",
) -> PushTensorHapticDevice:
    """Construct a cross-process haptic-glove device.

    The returned device accepts a ``FingerPowerVector(num_fingers)`` per
    endpoint (values in ``[0, 1]``, standard order Thumb..Pinky) and pushes
    each frame's powers as a ``HapticCommand`` to the glove plugin process
    listening on ``collection_id``.

    Args:
        collection_id: Push-tensor collection that pairs Isaac Teleop with the
            glove plugin process. Both must use the same string on the same
            system.
        num_fingers: Per-endpoint finger channels. Defaults to 5.
        endpoints: Named gloves to drive. Defaults to ``("left", "right")``;
            pass ``("left",)`` for a single glove.
        tensor_identifier: Tensor name within the collection; must match the
            plugin's reader.

    Returns:
        A :class:`PushTensorHapticDevice` bound to ``FingerPowerVector(num_fingers)``.
    """
    return PushTensorHapticDevice(
        collection_id,
        FingerPowerVector(num_fingers),
        tensor_identifier=tensor_identifier,
        endpoints=endpoints,
    )
