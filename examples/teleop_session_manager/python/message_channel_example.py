#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Message channel example using TeleopSession + retargeting source/sink nodes.

Behavior:
- Prints any incoming messages each frame.
- Once channel status is CONNECTED, sends one message every second.
"""

import argparse
import sys
import time
import uuid

from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    MessageChannelConnectionStatus,
    message_channel_config,
)
from isaacteleop.retargeting_engine.interface import TensorGroup
from isaacteleop.schema import MessageChannelMessages, MessageChannelMessagesTrackedT
from isaacteleop.teleop_session_manager import TeleopSession, TeleopSessionConfig


def _positive_int(value: str) -> int:
    """Argparse type= callable that rejects non-positive integers."""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {value!r}")
    if n <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {n}")
    return n


def _parse_uuid_bytes(uuid_text: str) -> bytes:
    """Parse canonical UUID text to 16-byte payload (argparse type= callable)."""
    try:
        return uuid.UUID(uuid_text).bytes
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--channel-uuid: invalid UUID {uuid_text!r} (expected canonical form, "
            "e.g. 550e8400-e29b-41d4-a716-446655440000)"
        )


def _enqueue_outbound_message(sink, payload: bytes) -> None:
    """Push one outbound message through MessageChannelSink."""
    tg = TensorGroup(sink.input_spec()["messages_tracked"])
    tg[0] = MessageChannelMessagesTrackedT([MessageChannelMessages(payload)])
    sink.compute({"messages_tracked": tg}, {})


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Message channel TeleopSession example"
    )
    parser.add_argument(
        "--channel-uuid",
        type=_parse_uuid_bytes,
        required=True,
        help="Message channel UUID (canonical form, e.g. 550e8400-e29b-41d4-a716-446655440000)",
    )
    parser.add_argument(
        "--channel-name",
        type=str,
        default="example_message_channel",
        help="Optional channel display name",
    )
    parser.add_argument(
        "--outbound-queue-capacity",
        type=_positive_int,
        default=256,
        help="Bounded outbound queue length",
    )
    args = parser.parse_args()

    source, sink = message_channel_config(
        name="message_channel",
        channel_uuid=args.channel_uuid,
        channel_name=args.channel_name,
        outbound_queue_capacity=args.outbound_queue_capacity,
    )

    config = TeleopSessionConfig(
        app_name="MessageChannelExample",
        pipeline=source,
    )

    print("=" * 80)
    print("Message Channel TeleopSession Example")
    print("=" * 80)
    print(f"Channel UUID: {args.channel_uuid}")
    print(f"Channel Name: {args.channel_name}")
    print("Press Ctrl+C to exit.")
    print()

    send_counter = 0
    last_send_time = 0.0

    with TeleopSession(config) as session:
        while True:
            result = session.step()
            status = result["status"][0]
            messages_tracked = result["messages_tracked"][0]
            messages = (
                messages_tracked.data if messages_tracked.data is not None else []
            )

            for msg in messages:
                payload = bytes(msg.payload)
                try:
                    decoded = payload.decode("utf-8")
                    print(f"[rx] {decoded}")
                except UnicodeDecodeError:
                    print(f"[rx] 0x{payload.hex()}")

            now = time.monotonic()
            if (
                status == MessageChannelConnectionStatus.CONNECTED
                and now - last_send_time >= 1.0
            ):
                payload_text = f"hello #{send_counter} @ {time.time():.3f}"
                _enqueue_outbound_message(sink, payload_text.encode("utf-8"))
                print(f"[tx] {payload_text}")
                last_send_time = now
                send_counter += 1

            time.sleep(0.01)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nExiting.")
        sys.exit(0)
