# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Async unit tests for :mod:`teleop_ws_hub.TeleopControlHub`.

Run from this directory (after ``pip install pytest``)::

    pytest -q

No CloudXR runtime, TLS, or ``isaacteleop`` install required — ``conftest.py`` adds
``src/core/cloudxr/python`` to ``sys.path``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from teleop_ws_hub import TeleopControlHub


class QueueWS:
    """Minimal async-iterable WebSocket stand-in for :meth:`TeleopControlHub.handle_connection`."""

    def __init__(self) -> None:
        self._q: asyncio.Queue[str | None] = asyncio.Queue()
        self.sent: list[str] = []
        self.close_calls: list[tuple[Any, ...]] = []

    async def inject(self, message: str) -> None:
        await self._q.put(message)

    async def end_stream(self) -> None:
        await self._q.put(None)

    def __aiter__(self) -> QueueWS:
        return self

    async def __anext__(self) -> str:
        item = await self._q.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def close(self, *_args: Any, **_kwargs: Any) -> None:
        self.close_calls.append(_args)


def _loads_sent(ws: QueueWS) -> list[dict]:
    return [json.loads(s) for s in ws.sent]


def test_check_token_no_requirement() -> None:
    hub = TeleopControlHub(control_token=None)
    assert hub.check_token(None) is True
    assert hub.check_token("anything") is True


def test_check_token_required() -> None:
    hub = TeleopControlHub(control_token="secret")
    assert hub.check_token(None) is False
    assert hub.check_token("wrong") is False
    assert hub.check_token("secret") is True


@pytest.mark.asyncio
async def test_get_snapshot_empty() -> None:
    hub = TeleopControlHub()
    snap = await hub.get_snapshot()
    assert snap["configVersion"] == 0
    assert snap["config"] == {}
    assert snap["headsets"] == []
    assert snap["dashboards"] == []
    assert "updatedAt" in snap


@pytest.mark.asyncio
async def test_headset_register_hello_and_snapshot() -> None:
    hub = TeleopControlHub(initial_config={"serverIP": "1.2.3.4", "port": 1111})
    ws = QueueWS()
    task = asyncio.create_task(hub.handle_connection(ws))

    await ws.inject(
        json.dumps(
            {"type": "register", "payload": {"role": "headset", "deviceLabel": "Q3"}}
        )
    )
    await asyncio.sleep(0)
    hello = json.loads(ws.sent[0])
    assert hello["type"] == "hello"
    assert hello["payload"]["config"]["serverIP"] == "1.2.3.4"
    assert hello["payload"]["config"]["port"] == 1111
    hid = hello["payload"]["clientId"]

    snap = await hub.get_snapshot()
    assert len(snap["headsets"]) == 1
    assert snap["headsets"][0]["clientId"] == hid
    assert snap["headsets"][0]["deviceLabel"] == "Q3"

    await ws.end_stream()
    await task


@pytest.mark.asyncio
async def test_register_rejects_bad_token() -> None:
    hub = TeleopControlHub(control_token="ok")
    ws = QueueWS()
    task = asyncio.create_task(hub.handle_connection(ws))

    await ws.inject(
        json.dumps({"type": "register", "payload": {"role": "headset", "token": "bad"}})
    )
    await asyncio.sleep(0)
    err = json.loads(ws.sent[0])
    assert err["type"] == "error"
    assert err["payload"]["code"] == "UNAUTHORIZED"
    assert ws.close_calls

    await ws.end_stream()
    await task


@pytest.mark.asyncio
async def test_first_message_must_be_register() -> None:
    hub = TeleopControlHub()
    ws = QueueWS()
    task = asyncio.create_task(hub.handle_connection(ws))

    await ws.inject(json.dumps({"type": "clientMetrics", "payload": {}}))
    await asyncio.sleep(0)
    err = json.loads(ws.sent[0])
    assert err["payload"]["code"] == "BAD_REQUEST"

    await ws.end_stream()
    await task


@pytest.mark.asyncio
async def test_set_config_pushes_to_headset() -> None:
    hub = TeleopControlHub(initial_config={"serverIP": "127.0.0.1", "port": 49100})
    hw = QueueWS()
    dw = QueueWS()
    th = asyncio.create_task(hub.handle_connection(hw))
    td = asyncio.create_task(hub.handle_connection(dw))

    await hw.inject(json.dumps({"type": "register", "payload": {"role": "headset"}}))
    await dw.inject(json.dumps({"type": "register", "payload": {"role": "dashboard"}}))
    await asyncio.sleep(0)

    hw.sent.clear()
    await dw.inject(
        json.dumps(
            {
                "type": "setConfig",
                "payload": {"config": {"serverIP": "10.0.0.2", "port": 48322}},
            }
        )
    )
    await asyncio.sleep(0)

    cfg_msgs = [m for m in _loads_sent(hw) if m["type"] == "config"]
    assert len(cfg_msgs) == 1
    assert cfg_msgs[0]["payload"]["config"]["serverIP"] == "10.0.0.2"
    assert cfg_msgs[0]["payload"]["config"]["port"] == 48322
    assert cfg_msgs[0]["payload"]["configVersion"] == 1

    await hw.end_stream()
    await dw.end_stream()
    await th
    await td


@pytest.mark.asyncio
async def test_set_config_empty_is_noop() -> None:
    hub = TeleopControlHub(initial_config={"serverIP": "127.0.0.1", "port": 49100})
    hw = QueueWS()
    dw = QueueWS()
    th = asyncio.create_task(hub.handle_connection(hw))
    td = asyncio.create_task(hub.handle_connection(dw))

    await hw.inject(json.dumps({"type": "register", "payload": {"role": "headset"}}))
    await dw.inject(json.dumps({"type": "register", "payload": {"role": "dashboard"}}))
    await asyncio.sleep(0)
    hw.sent.clear()

    await dw.inject(json.dumps({"type": "setConfig", "payload": {"config": {}}}))
    await asyncio.sleep(0)

    assert not any(m["type"] == "config" for m in _loads_sent(hw))
    assert (await hub.get_snapshot())["configVersion"] == 0

    await hw.end_stream()
    await dw.end_stream()
    await th
    await td


@pytest.mark.asyncio
async def test_set_config_identical_values_is_noop() -> None:
    hub = TeleopControlHub(initial_config={"serverIP": "10.0.0.1", "port": 9000})
    hw = QueueWS()
    dw = QueueWS()
    th = asyncio.create_task(hub.handle_connection(hw))
    td = asyncio.create_task(hub.handle_connection(dw))

    await hw.inject(json.dumps({"type": "register", "payload": {"role": "headset"}}))
    await dw.inject(json.dumps({"type": "register", "payload": {"role": "dashboard"}}))
    await asyncio.sleep(0)
    hw.sent.clear()

    await dw.inject(
        json.dumps(
            {
                "type": "setConfig",
                "payload": {"config": {"serverIP": "10.0.0.1", "port": 9000}},
            }
        )
    )
    await asyncio.sleep(0)

    assert not any(m["type"] == "config" for m in _loads_sent(hw))
    assert (await hub.get_snapshot())["configVersion"] == 0

    await hw.end_stream()
    await dw.end_stream()
    await th
    await td


@pytest.mark.asyncio
async def test_command_connect_single_headset() -> None:
    hub = TeleopControlHub()
    hw = QueueWS()
    dw = QueueWS()
    th = asyncio.create_task(hub.handle_connection(hw))
    td = asyncio.create_task(hub.handle_connection(dw))

    await hw.inject(json.dumps({"type": "register", "payload": {"role": "headset"}}))
    await dw.inject(json.dumps({"type": "register", "payload": {"role": "dashboard"}}))
    await asyncio.sleep(0)
    hw.sent.clear()

    await dw.inject(json.dumps({"type": "command", "payload": {"action": "connect"}}))
    await asyncio.sleep(0)

    sc = [m for m in _loads_sent(hw) if m["type"] == "sessionCommand"]
    assert len(sc) == 1
    assert sc[0]["payload"]["action"] == "connect"

    await hw.end_stream()
    await dw.end_stream()
    await th
    await td


@pytest.mark.asyncio
async def test_command_conflict_two_headsets() -> None:
    hub = TeleopControlHub()
    h1 = QueueWS()
    h2 = QueueWS()
    dw = QueueWS()
    t1 = asyncio.create_task(hub.handle_connection(h1))
    t2 = asyncio.create_task(hub.handle_connection(h2))
    td = asyncio.create_task(hub.handle_connection(dw))

    await h1.inject(json.dumps({"type": "register", "payload": {"role": "headset"}}))
    await h2.inject(json.dumps({"type": "register", "payload": {"role": "headset"}}))
    await dw.inject(json.dumps({"type": "register", "payload": {"role": "dashboard"}}))
    await asyncio.sleep(0)
    dw.sent.clear()

    await dw.inject(json.dumps({"type": "command", "payload": {"action": "connect"}}))
    await asyncio.sleep(0)

    errs = [m for m in _loads_sent(dw) if m["type"] == "error"]
    assert errs and errs[0]["payload"]["code"] == "CONFLICT"

    await h1.end_stream()
    await h2.end_stream()
    await dw.end_stream()
    await t1
    await t2
    await td


@pytest.mark.asyncio
async def test_client_metrics_stored_in_snapshot() -> None:
    hub = TeleopControlHub()
    ws = QueueWS()
    task = asyncio.create_task(hub.handle_connection(ws))

    await ws.inject(json.dumps({"type": "register", "payload": {"role": "headset"}}))
    await asyncio.sleep(0)
    await ws.inject(
        json.dumps(
            {
                "type": "clientMetrics",
                "payload": {
                    "t": 12345000,
                    "cadence": "frame",
                    "metrics": {"StreamingFramerate": 72.5},
                },
            }
        )
    )
    await asyncio.sleep(0)

    snap = await hub.get_snapshot()
    m = snap["headsets"][0]["metricsByCadence"]["frame"]
    assert m["at"] == 12345000
    assert m["metrics"]["StreamingFramerate"] == 72.5

    await ws.end_stream()
    await task


@pytest.mark.asyncio
async def test_dashboard_set_config_requires_token_when_configured() -> None:
    hub = TeleopControlHub(control_token="t")
    hw = QueueWS()
    dw = QueueWS()
    th = asyncio.create_task(hub.handle_connection(hw))
    td = asyncio.create_task(hub.handle_connection(dw))

    await hw.inject(
        json.dumps({"type": "register", "payload": {"role": "headset", "token": "t"}})
    )
    await dw.inject(
        json.dumps({"type": "register", "payload": {"role": "dashboard", "token": "t"}})
    )
    await asyncio.sleep(0)
    dw.sent.clear()

    await dw.inject(
        json.dumps(
            {
                "type": "setConfig",
                "payload": {"config": {"port": 1}, "token": "wrong"},
            }
        )
    )
    await asyncio.sleep(0)
    err = [m for m in _loads_sent(dw) if m["type"] == "error"]
    assert err and err[0]["payload"]["code"] == "UNAUTHORIZED"

    await hw.end_stream()
    await dw.end_stream()
    await th
    await td
