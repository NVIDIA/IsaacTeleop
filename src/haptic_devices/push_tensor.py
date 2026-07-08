# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Cross-process haptic adapter — the out-of-process device reference.

``PushTensorHapticDevice`` is an :class:`IHapticDevice` that forwards graph
output to a device plugin running in a *separate process*. Where
``ControllerHapticDevice`` calls a vendor SDK in-process, this adapter
serialises each endpoint's values into a vendor-neutral ``HapticCommand``
FlatBuffer and pushes it over ``XR_NVX1_push_tensor`` to a peer-process consumer
(a plugin built on ``HapticCommandReaderTracker``) sharing the same
``collection_id`` + ``tensor_identifier``.

It is the Python half of the "push device" layer: a partner ships a small
out-of-process plugin that owns their SDK and reads ``HapticCommand`` from the
shared collection, and reuses this adapter unchanged on the Isaac Teleop side.
The adapter is deliberately payload-agnostic -- ``accepted_type`` and
``endpoints`` are constructor arguments, so a haptic glove (per-finger powers),
a grounded force device (a force vector), or a multi-actuator exoskeleton all
reuse it without a new C++ tracker or a new wire schema. The meaning and
ordering of ``values`` is a contract between the upstream retargeter and the
plugin, documented in the plugin's README.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Iterable

import numpy as np

from isaacteleop.deviceio_trackers import TensorPushTracker
from isaacteleop.retargeting_engine.interface.tensor_group_type import TensorGroupType
from isaacteleop.schema import pack_haptic_command

from .interface import Endpoint, IHapticDevice


if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker


logger = logging.getLogger(__name__)


class PushTensorHapticDevice(IHapticDevice):
    """:class:`IHapticDevice` that pushes ``HapticCommand`` to a peer process.

    Each frame, :meth:`apply` stores the latest values per endpoint, and
    :meth:`flush` serialises one ``HapticCommand`` per endpoint (via
    ``pack_haptic_command``) and pushes it through a :class:`TensorPushTracker`.
    The paired consumer process reads them back with a
    ``HapticCommandReaderTracker`` on the same ``collection_id`` and
    ``tensor_identifier`` and drives the real hardware there.

    Args:
        collection_id: Push-tensor collection that pairs this producer with the
            consumer plugin. Both processes must use the same string and run on
            the same system.
        accepted_type: Device-side ``TensorGroupType`` the upstream retargeter
            must output (e.g. a per-finger power vector for a glove). Checked at
            ``HapticSink.connect()`` time.
        tensor_identifier: Name of the tensor within the collection; must match
            the consumer. Defaults to ``"haptic_command"``.
        endpoints: Named actuators this device drives. Defaults to the
            hand-mounted convention ``("left", "right")``; a single grounded
            device may pass ``("device",)``.
        max_payload_size: Fixed per-sample buffer size in bytes; must be at
            least the largest serialised ``HapticCommand`` (endpoint name +
            ``values``). Defaults to the tracker's own default.
    """

    def __init__(
        self,
        collection_id: str,
        accepted_type: TensorGroupType,
        *,
        tensor_identifier: str = "haptic_command",
        endpoints: Iterable[Endpoint] = ("left", "right"),
        max_payload_size: int = TensorPushTracker.DEFAULT_MAX_PAYLOAD_SIZE,
    ) -> None:
        self._accepted_type = accepted_type
        self._endpoints: tuple[Endpoint, ...] = tuple(endpoints)
        self._tracker = TensorPushTracker(
            collection_id, tensor_identifier, max_payload_size
        )
        # Latest-wins per endpoint within a frame; emitted and cleared by flush.
        self._pending: dict[Endpoint, list[float]] = {}
        self._error_logged: dict[Endpoint, bool] = {
            endpoint: False for endpoint in self._endpoints
        }

    def accepted_type(self) -> TensorGroupType:
        return self._accepted_type

    def endpoints(self) -> tuple[Endpoint, ...]:
        return self._endpoints

    def get_tracker(self) -> "ITracker":
        return self._tracker

    def apply(self, endpoint: Endpoint, values: np.ndarray) -> None:
        self._pending[endpoint] = np.asarray(values, dtype=np.float32).ravel().tolist()

    def flush(self, deviceio_session: Any) -> None:
        pending, self._pending = self._pending, {}
        for endpoint, values in pending.items():
            try:
                payload = pack_haptic_command(endpoint, values)
                self._tracker.push(deviceio_session, payload)
            except Exception as exc:
                if not self._error_logged.get(endpoint, False):
                    logger.warning(
                        "PushTensorHapticDevice.flush(%s) failed (further errors "
                        "for this endpoint will be silenced): %s",
                        endpoint,
                        exc,
                    )
                    self._error_logged[endpoint] = True
