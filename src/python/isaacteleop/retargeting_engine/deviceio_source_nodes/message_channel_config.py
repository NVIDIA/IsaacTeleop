# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Factory helpers for message channel source/sink node pairs."""

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .message_channel_sink import MessageChannelSink
from .message_channel_source import MessageChannelSource

import isaacteleop.deviceio as deviceio

if TYPE_CHECKING:
    from isaacteleop.schema import MessageChannelMessagesTrackedT


@dataclass
class MessageChannelConfig:
    """Configuration for creating message channel retargeter nodes."""

    name: str
    channel_uuid: bytes
    channel_name: str = ""
    max_message_size: int = 64 * 1024
    outbound_queue_capacity: int = 256

    def create_nodes(self) -> tuple[MessageChannelSource, MessageChannelSink]:
        if len(self.channel_uuid) != 16:
            raise ValueError(
                "MessageChannelConfig.channel_uuid must be exactly 16 bytes"
            )
        if self.outbound_queue_capacity <= 0:
            raise ValueError("MessageChannelConfig.outbound_queue_capacity must be > 0")
        tracker = deviceio.MessageChannelTracker(
            self.channel_uuid,
            self.channel_name,
            self.max_message_size,
        )
        # deque(maxlen=N) provides bounded queueing and drops oldest on overflow.
        outbound_queue: deque["MessageChannelMessagesTrackedT"] = deque(
            maxlen=self.outbound_queue_capacity
        )
        source = MessageChannelSource(
            f"{self.name}_source",
            tracker,
            outbound_queue,
        )
        sink = MessageChannelSink(f"{self.name}_sink", outbound_queue)
        return source, sink


def message_channel_config(
    name: str,
    channel_uuid: bytes,
    channel_name: str = "",
    max_message_size: int = 64 * 1024,
    outbound_queue_capacity: int = 256,
) -> tuple[MessageChannelSource, MessageChannelSink]:
    """Create source/sink nodes and shared tracker for a message channel."""
    return MessageChannelConfig(
        name=name,
        channel_uuid=channel_uuid,
        channel_name=channel_name,
        max_message_size=max_message_size,
        outbound_queue_capacity=outbound_queue_capacity,
    ).create_nodes()


# Backward-compatible alias matching requested API name.
messageChannelConfig = message_channel_config
