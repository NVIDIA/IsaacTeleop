# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from collections import deque

from isaacteleop.schema import (
    MessageChannelMessages,
    MessageChannelMessagesTrackedT,
)
from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    MessageChannelConnectionStatus,
    MessageChannelSink,
    MessageChannelSource,
)
from isaacteleop.retargeting_engine.interface.base_retargeter import _make_output_group
from isaacteleop.retargeting_engine.interface.tensor_group import TensorGroup


class DummyTracker:
    """Tiny fake tracker used to unit test source/sink behavior."""

    def __init__(self):
        self.sent_payloads = []
        self._drained = MessageChannelMessagesTrackedT()
        self.connected = True

    def send_message(self, session, payload):
        if not self.connected:
            raise RuntimeError("channel is not connected")
        self.sent_payloads.append(payload.payload)

    def get_status(self, session):
        return 1 if self.connected else 0

    def get_messages(self, session):
        return self._drained


def _make_inputs(node, raw):
    spec = node.input_spec()
    result = {}
    for name, objects in raw.items():
        tg = TensorGroup(spec[name])
        for i, obj in enumerate(objects):
            tg[i] = obj
        result[name] = tg
    return result


def test_message_channel_source_active_message():
    tracker = DummyTracker()
    source = MessageChannelSource("msg_source", tracker, deque())
    message = MessageChannelMessages(b"hello")
    tracker._drained = MessageChannelMessagesTrackedT([message])

    inputs = source.poll_tracker(deviceio_session=object())
    outputs = {k: _make_output_group(v) for k, v in source.output_spec().items()}
    source.compute(inputs, outputs)

    tracked_batch = outputs["messages_tracked"][0]
    assert tracked_batch.data is not None
    assert tracked_batch.data[0].payload == b"hello"
    assert outputs["status"][0] == MessageChannelConnectionStatus.CONNECTED


def test_message_channel_source_inactive_message():
    tracker = DummyTracker()
    source = MessageChannelSource("msg_source", tracker, deque())
    tracker._drained = MessageChannelMessagesTrackedT()

    inputs = source.poll_tracker(deviceio_session=object())
    outputs = {k: _make_output_group(v) for k, v in source.output_spec().items()}
    source.compute(inputs, outputs)

    tracked_batch = outputs["messages_tracked"][0]
    assert tracked_batch.data == []
    assert outputs["status"][0] == MessageChannelConnectionStatus.CONNECTED


def test_message_channel_sink_enqueues_message():
    outbound_queue = deque()
    sink = MessageChannelSink("msg_sink", outbound_queue)
    m1 = MessageChannelMessages(b"echo")
    m2 = MessageChannelMessages(b"pong")

    batch = MessageChannelMessagesTrackedT([m1, m2])
    inputs = _make_inputs(sink, {"messages_tracked": [batch]})
    outputs = {k: _make_output_group(v) for k, v in sink.output_spec().items()}
    sink.compute(inputs, outputs)

    assert sink.output_spec() == {}
    assert outputs == {}
    assert len(outbound_queue) == 1
    queued_batch = outbound_queue[0]
    assert queued_batch.data is not None
    assert queued_batch.data[0].payload == b"echo"
    assert queued_batch.data[1].payload == b"pong"


def test_message_channel_source_returns_all_drained_messages():
    tracker = DummyTracker()
    source = MessageChannelSource("msg_source_list", tracker, deque())
    m1 = MessageChannelMessages(b"x")
    m2 = MessageChannelMessages(b"y")
    tracker._drained = MessageChannelMessagesTrackedT([m1, m2])

    inputs = source.poll_tracker(deviceio_session=object())
    outputs = {k: _make_output_group(v) for k, v in source.output_spec().items()}
    source.compute(inputs, outputs)

    messages_tracked = outputs["messages_tracked"][0]
    assert messages_tracked.data is not None
    assert len(messages_tracked.data) == 2
    assert messages_tracked.data[0].payload == b"x"
    assert messages_tracked.data[1].payload == b"y"
    assert outputs["status"][0] == MessageChannelConnectionStatus.CONNECTED


def test_message_channel_source_keeps_outbound_queue_while_disconnected():
    tracker = DummyTracker()
    tracker.connected = False
    outbound_queue = deque()
    source = MessageChannelSource("msg_source_disconnected", tracker, outbound_queue)

    outbound_queue.append(
        MessageChannelMessagesTrackedT([MessageChannelMessages(b"a")])
    )
    outbound_queue.append(
        MessageChannelMessagesTrackedT([MessageChannelMessages(b"b")])
    )

    inputs = source.poll_tracker(deviceio_session=object())
    outputs = {k: _make_output_group(v) for k, v in source.output_spec().items()}
    source.compute(inputs, outputs)

    assert len(outbound_queue) == 2
    assert outbound_queue[0].data[0].payload == b"a"
    assert outbound_queue[1].data[0].payload == b"b"
    assert outputs["status"][0] == MessageChannelConnectionStatus.CONNECTING

    tracker.connected = True
    source.poll_tracker(deviceio_session=object())
    assert len(outbound_queue) == 0
    assert tracker.sent_payloads == [b"a", b"b"]

    inputs = source.poll_tracker(deviceio_session=object())
    outputs = {k: _make_output_group(v) for k, v in source.output_spec().items()}
    source.compute(inputs, outputs)
    assert outputs["status"][0] == MessageChannelConnectionStatus.CONNECTED


def test_message_channel_sink_bounded_queue_drops_oldest():
    outbound_queue = deque(maxlen=2)
    sink = MessageChannelSink("msg_sink_bounded", outbound_queue)
    m1 = MessageChannelMessages(b"1")
    m2 = MessageChannelMessages(b"2")
    m3 = MessageChannelMessages(b"3")

    b1 = MessageChannelMessagesTrackedT([m1])
    b2 = MessageChannelMessagesTrackedT([m2])
    b3 = MessageChannelMessagesTrackedT([m3])
    outputs = {k: _make_output_group(v) for k, v in sink.output_spec().items()}
    sink.compute(_make_inputs(sink, {"messages_tracked": [b1]}), outputs)
    sink.compute(_make_inputs(sink, {"messages_tracked": [b2]}), outputs)
    sink.compute(_make_inputs(sink, {"messages_tracked": [b3]}), outputs)

    assert len(outbound_queue) == 2
    assert outbound_queue[0].data[0].payload == b"2"
    assert outbound_queue[1].data[0].payload == b"3"
