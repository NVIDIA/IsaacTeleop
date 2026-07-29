# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Message channel source node.

Converts DeviceIO MessageChannelMessagesTrackedT wrapper data for graph use.
"""

from collections import deque
from typing import Any, TYPE_CHECKING

from .interface import IDeviceIOSource
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group import TensorGroup
from isaacteleop.schema import MessageChannelMessages, MessageChannelMessagesTrackedT
from .deviceio_tensor_types import (
    DeviceIOMessageChannelMessagesTracked,
    MessageChannelMessagesTrackedGroup,
    MessageChannelStatusGroup,
    MessageChannelConnectionStatus,
)

if TYPE_CHECKING:
    from isaacteleop.deviceio_trackers import (
        ITracker,
        MessageChannelTracker,
    )
    from isaacteleop.schema import (
        MessageChannelMessagesTrackedT,
    )


class MessageChannelSource(IDeviceIOSource):
    """Source node for reading message channel payloads from DeviceIO."""

    def __init__(
        self,
        name: str,
        tracker: "MessageChannelTracker",
        outbound_queue: "deque[MessageChannelMessagesTrackedT]",
    ) -> None:
        self._tracker = tracker
        self._outbound_queue = outbound_queue
        self._last_drained_messages_tracked: MessageChannelMessagesTrackedT | None = (
            None
        )
        self._last_status: MessageChannelConnectionStatus = (
            MessageChannelConnectionStatus.UNKNOWN
        )
        super().__init__(name)

    def get_tracker(self) -> "ITracker":
        return self._tracker

    def poll_tracker(self, deviceio_session: Any) -> RetargeterIO:
        raw_status = self._tracker.get_status(deviceio_session)
        try:
            self._last_status = MessageChannelConnectionStatus(int(raw_status))
        except ValueError:
            self._last_status = MessageChannelConnectionStatus.UNKNOWN

        # Flush queued outbound messages before polling inbound data.
        if self._last_status == MessageChannelConnectionStatus.CONNECTED:
            while self._outbound_queue:
                batch = self._outbound_queue[0]
                if batch.data:
                    sent = 0
                    try:
                        for message in batch.data:
                            outbound_message = MessageChannelMessages(message.payload)
                            self._tracker.send_message(
                                deviceio_session, outbound_message
                            )
                            sent += 1
                    except Exception:
                        # Drop the delivered prefix so already-sent messages are
                        # not re-delivered on the next flush attempt.
                        if sent < len(batch.data):
                            self._outbound_queue[0] = MessageChannelMessagesTrackedT(
                                batch.data[sent:]
                            )
                        else:
                            self._outbound_queue.popleft()
                        raise
                self._outbound_queue.popleft()

        self._last_drained_messages_tracked = self._tracker.get_messages(
            deviceio_session
        )

        source_inputs = self.input_spec()
        result: RetargeterIO = {}
        for input_name, group_type in source_inputs.items():
            tg = TensorGroup(group_type)
            if self._last_drained_messages_tracked is None:
                tg[0] = MessageChannelMessagesTrackedT()
            else:
                tg[0] = self._last_drained_messages_tracked
            result[input_name] = tg
        return result

    def input_spec(self) -> RetargeterIOType:
        return {
            "deviceio_message_channel_messages": DeviceIOMessageChannelMessagesTracked()
        }

    def output_spec(self) -> RetargeterIOType:
        return {
            "messages_tracked": MessageChannelMessagesTrackedGroup(),
            "status": MessageChannelStatusGroup(),
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        if self._last_drained_messages_tracked is None:
            outputs["messages_tracked"][0] = MessageChannelMessagesTrackedT()
        else:
            outputs["messages_tracked"][0] = self._last_drained_messages_tracked
        outputs["status"][0] = self._last_status
