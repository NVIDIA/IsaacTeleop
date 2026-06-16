# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Async unit tests for :mod:`oob_teleop_hub.OOBControlHub`.

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

from oob_teleop_hub import (
    APP_DESCRIPTOR_ENV,
    APP_DESCRIPTOR_FILE_ENV,
    HUB_CLIENT_DEV_URL_ENV,
    OOBControlHub,
    hub_client_dev_redirect_location,
    hub_client_dev_url_from_env,
    hub_client_asset_path,
    hub_client_content_type,
    load_app_descriptor_from_env,
)


class QueueWS:
    """Minimal async-iterable WebSocket stand-in for :meth:`OOBControlHub.handle_connection`."""

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
    hub = OOBControlHub(control_token=None)
    assert hub.check_token(None) is True
    assert hub.check_token("anything") is True


def test_check_token_required() -> None:
    hub = OOBControlHub(control_token="secret")
    assert hub.check_token(None) is False
    assert hub.check_token("wrong") is False
    assert hub.check_token("secret") is True


@pytest.mark.asyncio
async def test_get_snapshot_empty() -> None:
    hub = OOBControlHub()
    snap = await hub.get_snapshot()
    assert snap["configVersion"] == 0
    assert snap["config"] == {}
    assert snap["headsets"] == []
    assert "updatedAt" in snap
    assert snap["web2SchemaVersion"] == 1
    assert snap["app"]["displayName"] == "Isaac Teleop"
    assert snap["clients"] == []


@pytest.mark.asyncio
async def test_get_snapshot_includes_web2_join_links() -> None:
    hub = OOBControlHub(initial_config={"serverIP": "10.0.0.8", "port": 48322})

    snap = await hub.get_snapshot(
        request_origin="https://10.0.0.8:48322",
        local_client_available=True,
        published_client_base="https://pages.example/client/main/",
    )

    assert snap["join"]["preferred"] == "local-hosted"
    links = snap["join"]["links"]
    assert links[0]["kind"] == "local-hosted"
    assert links[0]["href"].startswith("https://10.0.0.8:48322/client/?")
    assert "serverIP=10.0.0.8" in links[0]["href"]
    assert "port=48322" in links[0]["href"]
    assert links[1]["kind"] == "github-pages"


@pytest.mark.asyncio
async def test_app_descriptor_and_televiz_flow_into_web2_snapshot() -> None:
    hub = OOBControlHub(
        app_descriptor={
            "id": "isaac-lab",
            "displayName": "Isaac Lab Pick Place",
            "sessionDisplayName": "Pick Place Session",
            "lifecycle": {"adapter": "isaac-lab", "supportedActions": ["launch"]},
            "televiz": {"present": True, "mode": "xr", "state": "ready"},
        }
    )

    snap = await hub.get_snapshot()

    assert snap["app"]["id"] == "isaac-lab"
    assert snap["app"]["displayName"] == "Isaac Lab Pick Place"
    assert snap["app"]["descriptorSource"] == "app_descriptor"
    assert snap["app"]["lifecycle"]["adapterAvailable"] is True
    assert snap["session"]["displayName"] == "Pick Place Session"
    assert snap["televiz"]["present"] is True
    assert snap["televiz"]["mode"] == "xr"


@pytest.mark.asyncio
async def test_headset_register_hello_and_snapshot() -> None:
    hub = OOBControlHub(initial_config={"serverIP": "1.2.3.4", "port": 1111})
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
async def test_headset_register_accepts_identity_and_capabilities() -> None:
    hub = OOBControlHub()
    ws = QueueWS()
    task = asyncio.create_task(hub.handle_connection(ws))

    await ws.inject(
        json.dumps(
            {
                "type": "register",
                "payload": {
                    "role": "headset",
                    "deviceLabel": "Quest 3",
                    "identity": {"displayName": "Lab headset"},
                    "capabilities": {"handTracking": True, "refreshRates": [72, 90]},
                },
            }
        )
    )
    await asyncio.sleep(0)

    snap = await hub.get_snapshot()
    client = snap["clients"][0]
    assert client["identity"]["displayName"] == "Lab headset"
    assert client["capabilities"]["handTracking"] is True
    assert snap["headsets"][0]["capabilities"]["refreshRates"] == [72, 90]

    await ws.end_stream()
    await task


@pytest.mark.asyncio
async def test_register_rejects_bad_token() -> None:
    hub = OOBControlHub(control_token="ok")
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
async def test_register_rejects_non_headset_role() -> None:
    hub = OOBControlHub()
    ws = QueueWS()
    task = asyncio.create_task(hub.handle_connection(ws))

    await ws.inject(json.dumps({"type": "register", "payload": {"role": "dashboard"}}))
    await asyncio.sleep(0)
    err = json.loads(ws.sent[0])
    assert err["type"] == "error"
    assert err["payload"]["code"] == "BAD_REQUEST"

    await ws.end_stream()
    await task


@pytest.mark.asyncio
async def test_first_message_must_be_register() -> None:
    hub = OOBControlHub()
    ws = QueueWS()
    task = asyncio.create_task(hub.handle_connection(ws))

    await ws.inject(json.dumps({"type": "clientMetrics", "payload": {}}))
    await asyncio.sleep(0)
    err = json.loads(ws.sent[0])
    assert err["payload"]["code"] == "BAD_REQUEST"

    await ws.end_stream()
    await task


@pytest.mark.asyncio
async def test_client_metrics_stored_in_snapshot() -> None:
    hub = OOBControlHub()
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
async def test_stream_status_updates_snapshot() -> None:
    hub = OOBControlHub()
    ws = QueueWS()
    task = asyncio.create_task(hub.handle_connection(ws))

    await ws.inject(json.dumps({"type": "register", "payload": {"role": "headset"}}))
    await asyncio.sleep(0)

    # Snapshot before any streamStatus: defaults to streaming=False, since=None.
    snap = await hub.get_snapshot()
    assert snap["headsets"][0]["streaming"] is False
    assert snap["headsets"][0]["streamingSince"] is None

    # Rising edge sets the timestamp.
    await ws.inject(
        json.dumps({"type": "streamStatus", "payload": {"streaming": True}})
    )
    await asyncio.sleep(0)
    snap = await hub.get_snapshot()
    assert snap["headsets"][0]["streaming"] is True
    first_since = snap["headsets"][0]["streamingSince"]
    assert isinstance(first_since, int) and first_since > 0

    # Repeat True must NOT reset the timestamp (only rising edges count).
    await asyncio.sleep(0.005)
    await ws.inject(
        json.dumps({"type": "streamStatus", "payload": {"streaming": True}})
    )
    await asyncio.sleep(0)
    snap = await hub.get_snapshot()
    assert snap["headsets"][0]["streamingSince"] == first_since

    # Falling edge clears the timestamp.
    await ws.inject(
        json.dumps({"type": "streamStatus", "payload": {"streaming": False}})
    )
    await asyncio.sleep(0)
    snap = await hub.get_snapshot()
    assert snap["headsets"][0]["streaming"] is False
    assert snap["headsets"][0]["streamingSince"] is None

    await ws.end_stream()
    await task


@pytest.mark.asyncio
async def test_wait_for_streaming_returns_on_rising_edge() -> None:
    hub = OOBControlHub()
    ws = QueueWS()
    task = asyncio.create_task(hub.handle_connection(ws))

    await ws.inject(json.dumps({"type": "register", "payload": {"role": "headset"}}))
    await asyncio.sleep(0)

    waiter = asyncio.create_task(hub.wait_for_streaming(poll_seconds=0.01))
    # Give the waiter a chance to start polling without a True yet.
    await asyncio.sleep(0.02)
    assert not waiter.done()

    await ws.inject(
        json.dumps({"type": "streamStatus", "payload": {"streaming": True}})
    )
    client_id, since = await asyncio.wait_for(waiter, timeout=1.0)
    assert isinstance(client_id, str) and client_id
    assert isinstance(since, float) and since > 0

    await ws.end_stream()
    await task


@pytest.mark.asyncio
async def test_unknown_message_type_returns_error() -> None:
    hub = OOBControlHub()
    ws = QueueWS()
    task = asyncio.create_task(hub.handle_connection(ws))

    await ws.inject(json.dumps({"type": "register", "payload": {"role": "headset"}}))
    await asyncio.sleep(0)
    ws.sent.clear()

    await ws.inject(json.dumps({"type": "bogus", "payload": {}}))
    await asyncio.sleep(0)
    errs = [m for m in _loads_sent(ws) if m["type"] == "error"]
    assert errs and errs[0]["payload"]["code"] == "BAD_REQUEST"

    await ws.end_stream()
    await task


@pytest.mark.asyncio
async def test_http_oob_set_config_noop_returns_changed_false() -> None:
    hub = OOBControlHub(initial_config={"serverIP": "10.0.0.1", "port": 9000})
    status, body = await hub.http_oob_set_config(
        {"config": {"serverIP": "10.0.0.1", "port": 9000}, "token": None}
    )
    assert status == 200
    assert body.get("changed") is False


@pytest.mark.asyncio
async def test_http_oob_set_config_updates_and_pushes() -> None:
    hub = OOBControlHub(initial_config={"serverIP": "127.0.0.1", "port": 49100})
    hw = QueueWS()
    th = asyncio.create_task(hub.handle_connection(hw))
    await hw.inject(json.dumps({"type": "register", "payload": {"role": "headset"}}))
    await asyncio.sleep(0)
    hw.sent.clear()

    status, body = await hub.http_oob_set_config(
        {"config": {"serverIP": "10.0.0.2"}, "token": None}
    )
    assert status == 200
    assert body.get("changed") is True
    cfg_msgs = [m for m in _loads_sent(hw) if m["type"] == "config"]
    assert len(cfg_msgs) == 1
    assert cfg_msgs[0]["payload"]["config"]["serverIP"] == "10.0.0.2"

    await hw.end_stream()
    await th


def test_load_app_descriptor_from_env_prefers_inline_json(monkeypatch) -> None:
    monkeypatch.setenv(APP_DESCRIPTOR_ENV, '{"displayName":"Dev App"}')
    monkeypatch.setenv(APP_DESCRIPTOR_FILE_ENV, "/tmp/unused-descriptor.json")

    descriptor, source = load_app_descriptor_from_env()

    assert descriptor == {"displayName": "Dev App"}
    assert source == APP_DESCRIPTOR_ENV


def test_load_app_descriptor_from_env_file(monkeypatch, tmp_path) -> None:
    fp = tmp_path / "app.json"
    fp.write_text('{"displayName":"File App"}', encoding="utf-8")
    monkeypatch.delenv(APP_DESCRIPTOR_ENV, raising=False)
    monkeypatch.setenv(APP_DESCRIPTOR_FILE_ENV, str(fp))

    descriptor, source = load_app_descriptor_from_env()

    assert descriptor == {"displayName": "File App"}
    assert source == APP_DESCRIPTOR_FILE_ENV


def test_hub_client_asset_path_resolves_static_assets_safely(tmp_path) -> None:
    build = tmp_path / "build"
    assets = build / "assets"
    assets.mkdir(parents=True)
    (build / "index.html").write_text("<div>hub app</div>", encoding="utf-8")
    (assets / "hub.js").write_text("console.log('hub')", encoding="utf-8")

    index = hub_client_asset_path(build, "/hub/")
    script = hub_client_asset_path(build, "/hub/assets/hub.js")

    assert index == (build / "index.html").resolve()
    assert script == (assets / "hub.js").resolve()
    assert hub_client_content_type(script).startswith("application/javascript")
    with pytest.raises(ValueError):
        hub_client_asset_path(build, "/hub/../secret.txt")


def test_hub_client_dev_redirect_location_preserves_path_and_query(monkeypatch) -> None:
    monkeypatch.setenv(HUB_CLIENT_DEV_URL_ENV, "http://localhost:5173/hub")

    assert hub_client_dev_url_from_env() == "http://localhost:5173/hub/"
    assert (
        hub_client_dev_redirect_location(
            "http://localhost:5173/hub/", "/hub/assets/app.js", "/hub/assets/app.js?x=1"
        )
        == "http://localhost:5173/hub/assets/app.js?x=1"
    )
    assert (
        hub_client_dev_redirect_location(
            "http://localhost:5173/hub/", "/hub/", "/?token=abc"
        )
        == "http://localhost:5173/hub/?token=abc"
    )
