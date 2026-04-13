# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Out-of-band (OOB) teleop hub — WebSocket server for headset metrics and config.

Headsets register via WebSocket and report streaming metrics. Operators read
state and push config via the HTTP API on the same TLS port.

WebSocket: ``wss://<host>:<PORT>/oob/v1/ws``
HTTP API:  ``GET /api/oob/v1/state``, ``GET /api/oob/v1/config``
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

log = logging.getLogger("oob-teleop-hub")

OOB_WS_PATH = "/oob/v1/ws"


@dataclass
class _HeadsetState:
    client_id: str
    ws: Any
    registered_at: float
    device_label: str | None = None
    metrics_by_cadence: dict = field(default_factory=dict)


class OOBControlHub:
    """Collects headset metrics and exposes state via HTTP.

    One instance per proxy process; WebSocket connections on ``OOB_WS_PATH``
    are dispatched via :meth:`handle_connection`.
    """

    def __init__(
        self,
        control_token: str | None = None,
        initial_config: dict | None = None,
    ) -> None:
        self._token = control_token
        self._headsets: dict[Any, _HeadsetState] = {}
        self._stream_config: dict = dict(initial_config or {})
        self._config_version: int = 0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def handle_connection(self, ws: Any) -> None:
        """Entry point for each new WebSocket client on ``OOB_WS_PATH``."""
        client_id = str(uuid.uuid4())
        registered = False

        try:
            async for raw in ws:
                if not isinstance(raw, str):
                    await self._send_error(ws, "BAD_REQUEST", "Expected text frame")
                    continue

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await self._send_error(ws, "BAD_REQUEST", "Invalid JSON")
                    continue

                msg_type: str = msg.get("type", "")
                payload: dict = msg.get("payload") or {}

                if not registered:
                    if msg_type != "register":
                        await self._send_error(
                            ws, "BAD_REQUEST", "First message must be register"
                        )
                        return
                    ok = await self._handle_register(ws, client_id, payload)
                    if not ok:
                        return
                    registered = True
                    continue

                await self._dispatch_headset(ws, msg_type, payload)

        except Exception:
            log.debug("Teleop WS closed", exc_info=True)
        finally:
            async with self._lock:
                self._headsets.pop(ws, None)
            log.info("Teleop client disconnected (clientId=%s)", client_id)

    async def get_snapshot(self) -> dict:
        """Build the JSON snapshot for ``GET /api/oob/v1/state``."""
        async with self._lock:
            headsets = [
                {
                    "clientId": s.client_id,
                    "connected": True,
                    "deviceLabel": s.device_label,
                    "registeredAt": int(s.registered_at * 1000),
                    "metricsByCadence": s.metrics_by_cadence,
                }
                for s in self._headsets.values()
            ]
            return {
                "updatedAt": int(time.time() * 1000),
                "configVersion": self._config_version,
                "config": dict(self._stream_config),
                "headsets": headsets,
            }

    def check_token(self, token: str | None) -> bool:
        """Return True if token satisfies the hub's auth requirement."""
        if not self._token:
            return True
        return token == self._token

    async def http_oob_set_config(self, payload: dict) -> tuple[int, dict]:
        """Merge stream config; for OOB HTTP ``GET /api/oob/v1/config``."""
        if not self.check_token(payload.get("token")):
            return 401, {"error": "Unauthorized"}

        new_config = payload.get("config")
        if not isinstance(new_config, dict):
            return 400, {"error": "config must be an object"}

        target_raw = payload.get("targetClientId")
        target_id: str | None = (
            None if target_raw is None or target_raw == "" else str(target_raw)
        )

        outcome = await self._merge_stream_config(new_config, target_id)
        if outcome[0] == "noop":
            return 200, {
                "ok": True,
                "changed": False,
                "configVersion": outcome[1],
            }
        if outcome[0] == "missing":
            return 404, {"error": f"Headset '{outcome[1]}' not connected"}

        _tag, version, config_snapshot, targets = outcome
        log.info(
            "OOB setConfig configVersion=%d → %d headset(s)", version, len(targets)
        )
        await self._push_config_to_headsets(version, config_snapshot, targets)
        return 200, {
            "ok": True,
            "changed": True,
            "configVersion": version,
            "targetCount": len(targets),
        }

    # ------------------------------------------------------------------
    # Private: registration
    # ------------------------------------------------------------------

    async def _handle_register(self, ws: Any, client_id: str, payload: dict) -> bool:
        """Validate and register a headset. Returns True on success."""
        if self._token and payload.get("token") != self._token:
            await self._send_error(ws, "UNAUTHORIZED", "Invalid or missing token")
            try:
                await ws.close(1008, "Unauthorized")
            except Exception:
                pass
            return False

        role = payload.get("role")
        if role != "headset":
            await self._send_error(ws, "BAD_REQUEST", "role must be 'headset'")
            return False

        async with self._lock:
            state = _HeadsetState(
                client_id=client_id,
                ws=ws,
                registered_at=time.time(),
                device_label=payload.get("deviceLabel"),
            )
            self._headsets[ws] = state
            log.info(
                "Headset registered: clientId=%s label=%s",
                client_id,
                state.device_label,
            )
            hello_payload = {
                "clientId": client_id,
                "configVersion": self._config_version,
                "config": dict(self._stream_config),
            }

        await self._send(ws, "hello", hello_payload)
        return True

    # ------------------------------------------------------------------
    # Private: message dispatch
    # ------------------------------------------------------------------

    async def _dispatch_headset(self, ws: Any, msg_type: str, payload: dict) -> None:
        if msg_type == "clientMetrics":
            await self._handle_client_metrics(ws, payload)
        else:
            await self._send_error(
                ws, "BAD_REQUEST", f"Unknown message type: {msg_type}"
            )

    # ------------------------------------------------------------------
    # Private: message handlers
    # ------------------------------------------------------------------

    async def _merge_stream_config(
        self, new_config: dict, target_id: str | None
    ) -> (
        tuple[Literal["noop"], int]
        | tuple[Literal["missing"], str]
        | tuple[Literal["push"], int, dict, list[_HeadsetState]]
    ):
        async with self._lock:
            merged = {**self._stream_config, **new_config}
            if merged == self._stream_config:
                return ("noop", self._config_version)

            if target_id is not None:
                targets = [
                    s for s in self._headsets.values() if s.client_id == target_id
                ]
                if not targets:
                    return ("missing", target_id)
                return ("push", self._config_version, merged, targets)

            self._stream_config = merged
            self._config_version += 1
            return (
                "push",
                self._config_version,
                dict(self._stream_config),
                list(self._headsets.values()),
            )

    async def _push_config_to_headsets(
        self, version: int, config_snapshot: dict, targets: list[_HeadsetState]
    ) -> None:
        push_payload = {"configVersion": version, "config": config_snapshot}
        for headset in targets:
            await self._send(headset.ws, "config", push_payload)

    async def _handle_client_metrics(self, ws: Any, payload: dict) -> None:
        async with self._lock:
            state = self._headsets.get(ws)
            if state is None:
                return
            cadence = str(payload.get("cadence", "unknown"))
            raw_metrics = payload.get("metrics", {})
            if not isinstance(raw_metrics, dict):
                raw_metrics = {}
            state.metrics_by_cadence[cadence] = {
                "at": int(payload.get("t", time.time() * 1000)),
                "metrics": {
                    str(k): float(v)
                    for k, v in raw_metrics.items()
                    if isinstance(v, (int, float))
                },
            }

    # ------------------------------------------------------------------
    # Private: send helpers
    # ------------------------------------------------------------------

    async def _send(self, ws: Any, msg_type: str, payload: dict) -> None:
        try:
            await ws.send(json.dumps({"type": msg_type, "payload": payload}))
        except Exception:
            log.debug("Failed to send '%s' message", msg_type, exc_info=True)

    async def _send_error(
        self,
        ws: Any,
        code: str,
        message: str,
        request_id: str | None = None,
    ) -> None:
        p: dict = {"code": code, "message": message}
        if request_id is not None:
            p["requestId"] = request_id
        await self._send(ws, "error", p)
