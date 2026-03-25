# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Teleop control hub — WebSocket application layer for operator ↔ headset control.

Mount point: wss://<host>:<PORT>/teleop/v1/ws
State API:   GET  /api/teleop/v1/state

See ``docs/source/references/teleop_control_protocol.rst`` (Sphinx: *Teleop Control Protocol*).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("teleop-hub")

TELEOP_WS_PATH = "/teleop/v1/ws"

# ---------------------------------------------------------------------------
# Internal state containers
# ---------------------------------------------------------------------------


@dataclass
class _HeadsetState:
    client_id: str
    ws: Any
    registered_at: float
    device_label: str | None = None
    metrics_by_cadence: dict = field(default_factory=dict)


@dataclass
class _DashboardState:
    client_id: str
    ws: Any
    registered_at: float


# ---------------------------------------------------------------------------
# Hub
# ---------------------------------------------------------------------------


class TeleopControlHub:
    """Routes control messages between operator dashboards and XR headsets.

    One instance per server process; all WebSocket connections that arrive on
    TELEOP_WS_PATH are dispatched here via :meth:`handle_connection`.
    """

    def __init__(
        self,
        control_token: str | None = None,
        initial_config: dict | None = None,
    ) -> None:
        self._token = control_token
        self._headsets: dict[Any, _HeadsetState] = {}
        self._dashboards: dict[Any, _DashboardState] = {}
        self._stream_config: dict = dict(initial_config or {})
        self._config_version: int = 0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def handle_connection(self, ws: Any) -> None:
        """Entry point for each new WebSocket client on /teleop/v1/ws."""
        client_id = str(uuid.uuid4())
        role: str | None = None

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

                if role is None:
                    if msg_type != "register":
                        await self._send_error(
                            ws, "BAD_REQUEST", "First message must be register"
                        )
                        return
                    role = await self._handle_register(ws, client_id, payload)
                    if role is None:
                        return  # rejected; connection already closed
                    continue

                if role == "headset":
                    await self._dispatch_headset(ws, msg_type, payload)
                else:
                    await self._dispatch_dashboard(ws, msg_type, payload)

        except Exception:
            log.debug("Teleop WS closed", exc_info=True)
        finally:
            async with self._lock:
                self._headsets.pop(ws, None)
                self._dashboards.pop(ws, None)
            log.info(
                "Teleop client disconnected (clientId=%s role=%s)", client_id, role
            )

    async def get_snapshot(self) -> dict:
        """Build the JSON Snapshot for GET /api/teleop/v1/state."""
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
            dashboards = [
                {
                    "clientId": s.client_id,
                    "connected": True,
                    "registeredAt": int(s.registered_at * 1000),
                }
                for s in self._dashboards.values()
            ]
            return {
                "updatedAt": int(time.time() * 1000),
                "configVersion": self._config_version,
                "config": dict(self._stream_config),
                "headsets": headsets,
                "dashboards": dashboards,
            }

    def check_token(self, token: str | None) -> bool:
        """Return True if token satisfies the hub's auth requirement."""
        if not self._token:
            return True
        return token == self._token

    # ------------------------------------------------------------------
    # Private: registration
    # ------------------------------------------------------------------

    async def _handle_register(
        self, ws: Any, client_id: str, payload: dict
    ) -> str | None:
        """Validate, register, and send hello. Returns role or None on rejection."""
        if self._token and payload.get("token") != self._token:
            await self._send_error(ws, "UNAUTHORIZED", "Invalid or missing token")
            try:
                await ws.close(1008, "Unauthorized")
            except Exception:
                pass
            return None

        role = payload.get("role")
        if role not in ("headset", "dashboard"):
            await self._send_error(
                ws, "BAD_REQUEST", "role must be 'headset' or 'dashboard'"
            )
            return None

        async with self._lock:
            if role == "headset":
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
            else:
                self._dashboards[ws] = _DashboardState(
                    client_id=client_id,
                    ws=ws,
                    registered_at=time.time(),
                )
                log.info("Dashboard registered: clientId=%s", client_id)
                hello_payload = {"clientId": client_id}

        await self._send(ws, "hello", hello_payload)
        return role

    # ------------------------------------------------------------------
    # Private: message dispatch
    # ------------------------------------------------------------------

    async def _dispatch_headset(self, ws: Any, msg_type: str, payload: dict) -> None:
        if msg_type == "clientMetrics":
            await self._handle_client_metrics(ws, payload)
        else:
            await self._send_error(
                ws, "BAD_REQUEST", f"Unknown message type for headset: {msg_type}"
            )

    async def _dispatch_dashboard(self, ws: Any, msg_type: str, payload: dict) -> None:
        # Defense-in-depth: re-validate token on dashboard messages
        if self._token and payload.get("token") != self._token:
            await self._send_error(ws, "UNAUTHORIZED", "Invalid or missing token")
            return

        if msg_type == "setConfig":
            await self._handle_set_config(ws, payload)
        elif msg_type == "command":
            await self._handle_command(ws, payload)
        else:
            await self._send_error(
                ws, "BAD_REQUEST", f"Unknown message type for dashboard: {msg_type}"
            )

    # ------------------------------------------------------------------
    # Private: message handlers
    # ------------------------------------------------------------------

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

    async def _handle_set_config(self, ws: Any, payload: dict) -> None:
        new_config = payload.get("config")
        if not isinstance(new_config, dict):
            await self._send_error(
                ws, "BAD_REQUEST", "payload.config must be an object"
            )
            return

        target_id: str | None = payload.get("targetClientId")

        missing_target: str | None = None
        version: int
        config_snapshot: dict
        targets: list[_HeadsetState]

        async with self._lock:
            merged = {**self._stream_config, **new_config}
            if merged == self._stream_config:
                return  # no-op: empty {}, redundant values, or no change

            all_headsets = list(self._headsets.values())

            if target_id is not None:
                targets = [s for s in all_headsets if s.client_id == target_id]
                if not targets:
                    missing_target = target_id
                else:
                    self._stream_config = merged
                    self._config_version += 1
                    version = self._config_version
                    config_snapshot = dict(self._stream_config)
            else:
                targets = all_headsets
                self._stream_config = merged
                self._config_version += 1
                version = self._config_version
                config_snapshot = dict(self._stream_config)

        if missing_target is not None:
            await self._send_error(
                ws, "NOT_FOUND", f"Headset '{missing_target}' not connected"
            )
            return

        log.info("setConfig configVersion=%d → %d headset(s)", version, len(targets))
        push_payload = {"configVersion": version, "config": config_snapshot}
        for headset in targets:
            await self._send(headset.ws, "config", push_payload)

    async def _handle_command(self, ws: Any, payload: dict) -> None:
        action = payload.get("action")
        if action not in ("connect", "disconnect"):
            await self._send_error(
                ws, "BAD_REQUEST", "action must be 'connect' or 'disconnect'"
            )
            return

        target_id: str | None = payload.get("targetClientId")
        request_id: str | None = payload.get("requestId")

        async with self._lock:
            all_headsets = list(self._headsets.values())

        if target_id is not None:
            targets = [s for s in all_headsets if s.client_id == target_id]
            if not targets:
                await self._send_error(
                    ws, "NOT_FOUND", f"Headset '{target_id}' not connected"
                )
                return
        else:
            if not all_headsets:
                await self._send_error(ws, "NOT_FOUND", "No headsets connected")
                return
            if len(all_headsets) > 1:
                await self._send_error(
                    ws,
                    "CONFLICT",
                    "Multiple headsets connected; specify targetClientId",
                )
                return
            targets = all_headsets

        log.info("command action=%s → %d headset(s)", action, len(targets))
        sc_payload: dict = {"action": action}
        if request_id is not None:
            sc_payload["requestId"] = request_id

        for headset in targets:
            await self._send(headset.ws, "sessionCommand", sc_payload)

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
