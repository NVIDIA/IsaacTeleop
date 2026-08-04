# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Message channel sink node.

Queues raw message payloads for delivery by MessageChannelSource.poll_tracker().
"""

from collections import deque
from typing import TYPE_CHECKING

from ..interface.base_retargeter import BaseRetargeter
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from .deviceio_tensor_types import MessageChannelMessagesTrackedGroup

if TYPE_CHECKING:
    from isaacteleop.schema import MessageChannelMessagesTrackedT


class MessageChannelSink(BaseRetargeter):
    """Sink node that enqueues outbound message channel payloads."""

    def __init__(
        self, name: str, outbound_queue: "deque[MessageChannelMessagesTrackedT]"
    ) -> None:
        self._outbound_queue = outbound_queue
        super().__init__(name)

    def input_spec(self) -> RetargeterIOType:
        return {"messages_tracked": MessageChannelMessagesTrackedGroup()}

    def output_spec(self) -> RetargeterIOType:
        return {}

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        messages_tracked = inputs["messages_tracked"][0]
        self._outbound_queue.append(messages_tracked)
