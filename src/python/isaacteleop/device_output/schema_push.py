# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Cross-process output adapter — push typed FlatBuffer samples to a plugin."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Iterable, Sequence, TypeVar

import numpy as np

from isaacteleop.retargeting_engine.interface.tensor_group_type import TensorGroupType

from .interface import Endpoint, IDeviceOutputAdapter, TensorSlotValues


if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker


logger = logging.getLogger(__name__)

SchemaPayload = TypeVar("SchemaPayload")


class SchemaPushOutputAdapter(IDeviceOutputAdapter):
    """Push a typed FlatBuffer table to a peer-process plugin each frame.

    The host-side half of the generic vendor-output path: a generated
    ``*PushTracker`` serialises ``payload_type`` over ``XR_NVX1_push_tensor``;
    the plugin reads the same table with a matching pull tracker on the same
    ``collection_id`` + ``tensor_identifier``.

    Args:
        push_tracker: Generated push tracker instance (e.g.
            ``LatencyProbeResponsePushTracker``).
        accepted_type: ``TensorGroupType`` the upstream retargeter must output.
        pack_sample: ``(endpoint, values) -> payload_type`` builder used at flush.
        endpoints: Output channels. Defaults to ``("device",)``.
    """

    def __init__(
        self,
        push_tracker: Any,
        accepted_type: TensorGroupType,
        pack_sample: Callable[[Endpoint, TensorSlotValues], SchemaPayload],
        *,
        endpoints: Iterable[Endpoint] = ("device",),
    ) -> None:
        self._tracker = push_tracker
        self._accepted_type = accepted_type
        self._pack_sample = pack_sample
        self._endpoints: tuple[Endpoint, ...] = tuple(endpoints)
        self._pending: dict[Endpoint, TensorSlotValues] = {}
        self._error_logged: dict[Endpoint, bool] = {
            endpoint: False for endpoint in self._endpoints
        }

    def accepted_type(self) -> TensorGroupType:
        return self._accepted_type

    def endpoints(self) -> tuple[Endpoint, ...]:
        return self._endpoints

    def get_tracker(self) -> "ITracker":
        return self._tracker

    def apply(self, endpoint: Endpoint, values: Sequence[np.ndarray]) -> None:
        self._pending[endpoint] = tuple(np.asarray(value).copy() for value in values)

    def flush(self, deviceio_session: Any) -> None:
        pending, self._pending = self._pending, {}
        for endpoint, values in pending.items():
            try:
                sample = self._pack_sample(endpoint, values)
                self._tracker.push(deviceio_session, sample)
            except Exception as exc:
                if not self._error_logged.get(endpoint, False):
                    logger.warning(
                        "SchemaPushOutputAdapter.flush(%s) failed (further errors "
                        "for this endpoint will be silenced): %s",
                        endpoint,
                        exc,
                    )
                    self._error_logged[endpoint] = True
