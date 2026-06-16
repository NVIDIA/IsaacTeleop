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
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

log = logging.getLogger("oob-teleop-hub")

APP_DESCRIPTOR_ENV = "TELEOP_APP_DESCRIPTOR"
APP_DESCRIPTOR_FILE_ENV = "TELEOP_APP_DESCRIPTOR_FILE"
HUB_CLIENT_STATIC_DIR_ENV = "TELEOP_HUB_CLIENT_STATIC_DIR"
HUB_CLIENT_DEV_URL_ENV = "TELEOP_HUB_CLIENT_DEV_URL"

DEFAULT_APP_ID = "isaacteleop"
DEFAULT_APP_DISPLAY_NAME = "Isaac Teleop"
DEFAULT_PUBLISHED_CLIENT_BASE = "https://nvidia.github.io/IsaacTeleop/client/main/"
WEB2_SCHEMA_VERSION = 1

HUB_CLIENT_MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
}

_CLIENT_QUERY_FIELDS = (
    "serverIP",
    "port",
    "codec",
    "panelHiddenAtStart",
    "turnServer",
    "turnUsername",
    "turnCredential",
    "iceRelayOnly",
)

_FRAME_RATE_KEYS = (
    "streamingframerate",
    "streaming_framerate",
    "framerate",
    "frame_rate",
    "fps",
)

_LATENCY_KEYS = (
    "latencyms",
    "latency_ms",
    "roundtripdelayms",
    "round_trip_delay_ms",
    "rttms",
    "rtt_ms",
)

OOB_WS_PATH = "/oob/v1/ws"


def load_app_descriptor_from_env() -> tuple[dict | None, str | None]:
    """Load a development app descriptor override from env or a JSON file."""
    raw = os.environ.get(APP_DESCRIPTOR_ENV, "").strip()
    if raw:
        return _parse_descriptor_text(raw, APP_DESCRIPTOR_ENV), APP_DESCRIPTOR_ENV

    raw_path = os.environ.get(APP_DESCRIPTOR_FILE_ENV, "").strip()
    if not raw_path:
        return None, None

    path = Path(raw_path).expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Could not read {APP_DESCRIPTOR_FILE_ENV}: {path}") from exc
    return _parse_descriptor_text(
        text, APP_DESCRIPTOR_FILE_ENV
    ), APP_DESCRIPTOR_FILE_ENV


def default_hub_client_static_dir() -> Path:
    """Default Vite build output for the Teleop Hub client."""
    return Path(__file__).resolve().parent.parent / "hub_client" / "build"


def resolve_hub_client_static_dir() -> Path:
    """Return the static hub client directory, honoring a development override."""
    override = os.environ.get(HUB_CLIENT_STATIC_DIR_ENV, "").strip()
    return Path(override).expanduser() if override else default_hub_client_static_dir()


def hub_client_dev_url_from_env() -> str | None:
    """Return the optional hot-reload Hub client URL used during UI development."""
    raw = os.environ.get(HUB_CLIENT_DEV_URL_ENV, "").strip()
    if not raw:
        return None
    return raw.rstrip("/") + "/"


def hub_client_dev_redirect_location(
    dev_base_url: str, path: str, raw_path: str | None = None, prefix: str = "/hub"
) -> str:
    """Build the dev-server redirect location for a /hub request."""
    base = dev_base_url.rstrip("/") + "/"
    tail = ""
    if path.startswith(prefix):
        tail = path[len(prefix) :].lstrip("/")
    query = ""
    if raw_path and "?" in raw_path:
        query = "?" + raw_path.split("?", 1)[1]
    return base + tail + query


def hub_client_asset_path(static_root: Path, path: str, prefix: str = "/hub") -> Path:
    """Resolve a /hub asset path within *static_root* with traversal protection."""
    root = static_root.resolve()
    tail = path[len(prefix) :].lstrip("/") if path.startswith(prefix) else ""
    if not tail:
        tail = "index.html"
    candidate = (root / tail).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("hub asset path escapes static root")
    return candidate


def hub_client_content_type(path: Path) -> str:
    """Return the MIME type used when serving a hub client asset."""
    return HUB_CLIENT_MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")


def build_web2_hub_fields(
    *,
    config: dict,
    headsets: list[dict],
    app_descriptor: dict | None = None,
    app_descriptor_source: str | None = None,
    request_origin: str | None = None,
    local_client_available: bool = False,
    published_client_base: str | None = None,
) -> dict:
    """Build additive Web 2.0 fields for the legacy OOB state snapshot."""
    app, session = _normalise_app_descriptor(
        app_descriptor, app_descriptor_source=app_descriptor_source
    )
    clients = [_client_from_headset(h) for h in headsets]
    join_links = build_join_links(
        config=config,
        request_origin=request_origin,
        local_client_available=local_client_available,
        published_client_base=published_client_base,
    )
    preflight = _build_preflight(
        config=config,
        client_count=len(clients),
        local_client_available=local_client_available,
    )
    return {
        "web2SchemaVersion": WEB2_SCHEMA_VERSION,
        "app": app,
        "session": session,
        "clients": clients,
        "join": {
            "preferred": _preferred_join_kind(join_links),
            "links": join_links,
        },
        "preflight": preflight,
        "metrics": _build_metric_summary(headsets),
        "televiz": _normalise_televiz(app_descriptor),
        "prototype": {
            "mocked": True,
            "phase": "web2-contract-first",
            "notes": [
                "Preflight and TeleViz details are placeholders until runtime adapters report them.",
                "Client capability fields are accepted when WebXR starts sending them.",
            ],
        },
    }


def build_join_links(
    *,
    config: dict,
    request_origin: str | None = None,
    local_client_available: bool = False,
    published_client_base: str | None = None,
) -> list[dict]:
    """Return operator-visible WebXR client links for the hub dashboard."""
    links: list[dict] = []

    if local_client_available and request_origin:
        local_base = request_origin.rstrip("/") + "/client/"
        links.append(
            {
                "kind": "local-hosted",
                "label": "Hosted client",
                "href": _append_client_query(local_base, config),
                "preferred": True,
                "availability": "available",
            }
        )

    published_base = _clean_str(published_client_base) or DEFAULT_PUBLISHED_CLIENT_BASE
    if published_base:
        links.append(
            {
                "kind": "github-pages",
                "label": "Published client",
                "href": _append_client_query(published_base, config),
                "preferred": not links,
                "availability": "available",
            }
        )

    return links


@dataclass
class _HeadsetState:
    client_id: str
    ws: Any
    registered_at: float
    device_label: str | None = None
    identity: dict = field(default_factory=dict)
    capabilities: dict = field(default_factory=dict)
    metrics_by_cadence: dict = field(default_factory=dict)
    # Updated by streamStatus messages; streaming_since is set on the rising
    # edge only (so a repeated True doesn't reset the timestamp).
    streaming: bool = False
    streaming_since: float | None = None


class OOBControlHub:
    """Collects headset metrics and exposes state via HTTP.

    One instance per proxy process; WebSocket connections on ``OOB_WS_PATH``
    are dispatched via :meth:`handle_connection`.
    """

    def __init__(
        self,
        control_token: str | None = None,
        initial_config: dict | None = None,
        app_descriptor: dict | None = None,
        app_descriptor_source: str | None = None,
    ) -> None:
        self._token = control_token
        self._headsets: dict[Any, _HeadsetState] = {}
        self._stream_config: dict = dict(initial_config or {})
        self._config_version: int = 0
        self._app_descriptor: dict | None = (
            dict(app_descriptor) if app_descriptor else None
        )
        self._app_descriptor_source = app_descriptor_source
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

    async def get_snapshot(
        self,
        *,
        request_origin: str | None = None,
        local_client_available: bool = False,
        published_client_base: str | None = None,
    ) -> dict:
        """Build the JSON snapshot for ``GET /api/oob/v1/state``."""
        async with self._lock:
            headsets = [
                {
                    "clientId": s.client_id,
                    "connected": True,
                    "streaming": s.streaming,
                    "streamingSince": (
                        int(s.streaming_since * 1000)
                        if s.streaming_since is not None
                        else None
                    ),
                    "deviceLabel": s.device_label,
                    "identity": dict(s.identity),
                    "capabilities": dict(s.capabilities),
                    "registeredAt": int(s.registered_at * 1000),
                    "metricsByCadence": s.metrics_by_cadence,
                }
                for s in self._headsets.values()
            ]
            config = dict(self._stream_config)
            snapshot = {
                "updatedAt": int(time.time() * 1000),
                "configVersion": self._config_version,
                "config": config,
                "headsets": headsets,
            }
            snapshot.update(
                build_web2_hub_fields(
                    config=config,
                    headsets=headsets,
                    app_descriptor=self._app_descriptor,
                    app_descriptor_source=self._app_descriptor_source,
                    request_origin=request_origin,
                    local_client_available=local_client_available,
                    published_client_base=published_client_base,
                )
            )
            return snapshot

    async def wait_for_streaming(
        self, *, poll_seconds: float = 1.0
    ) -> tuple[str, float]:
        """Block until any headset reports ``streaming=True``; return ``(clientId, since)``."""
        while True:
            async with self._lock:
                for s in self._headsets.values():
                    if s.streaming and s.streaming_since is not None:
                        return s.client_id, s.streaming_since
            await asyncio.sleep(poll_seconds)

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

        identity = payload.get("identity") or payload.get("clientIdentity") or {}
        if not isinstance(identity, dict):
            identity = {}
        capabilities = payload.get("capabilities") or {}
        if not isinstance(capabilities, dict):
            capabilities = {}

        async with self._lock:
            state = _HeadsetState(
                client_id=client_id,
                ws=ws,
                registered_at=time.time(),
                device_label=payload.get("deviceLabel"),
                identity=identity,
                capabilities=capabilities,
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
        elif msg_type == "streamStatus":
            await self._handle_stream_status(ws, payload)
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
                # Targeted push: send merged snapshot without mutating global state.
                return ("push", self._config_version, merged, targets)

            # Global push: update shared config and version.
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

    async def _handle_stream_status(self, ws: Any, payload: dict) -> None:
        """Wire format: ``{"streaming": true|false}``. Rising edge stamps ``streaming_since``."""
        streaming = bool(payload.get("streaming", False))
        async with self._lock:
            state = self._headsets.get(ws)
            if state is None:
                return
            if streaming and not state.streaming:
                state.streaming_since = time.time()
            elif not streaming:
                state.streaming_since = None
            state.streaming = streaming
            log.info(
                "Headset %s streamStatus: streaming=%s", state.client_id, streaming
            )

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


def _parse_descriptor_text(raw: str, source: str) -> dict:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"displayName": raw}
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, str) and parsed.strip():
        return {"displayName": parsed.strip()}
    raise RuntimeError(f"{source} must be a JSON object or display name")


def _normalise_app_descriptor(
    descriptor: dict | None, *, app_descriptor_source: str | None = None
) -> tuple[dict, dict]:
    data = dict(descriptor or {})
    source = app_descriptor_source or ("app_descriptor" if descriptor else "stub")
    display_name = (
        _first_text(data, "displayName", "display_name", "appName", "app_name", "name")
        or DEFAULT_APP_DISPLAY_NAME
    )
    app_id = _first_text(data, "id", "appId", "app_id") or DEFAULT_APP_ID
    lifecycle = data.get("lifecycle") if isinstance(data.get("lifecycle"), dict) else {}
    actions = lifecycle.get("supportedActions") or lifecycle.get("actions") or []
    if not isinstance(actions, list):
        actions = []
    adapter_name = _clean_str(lifecycle.get("adapter") or data.get("lifecycleAdapter"))
    app = {
        "id": app_id,
        "displayName": display_name,
        "status": _first_text(data, "status")
        or ("stub" if source == "stub" else "ready"),
        "descriptorSource": source,
        "lifecycle": {
            "adapterAvailable": bool(adapter_name or actions),
            "adapter": adapter_name,
            "supportedActions": [str(a) for a in actions],
        },
    }
    session = {
        "displayName": _first_text(
            data, "sessionDisplayName", "session_display_name", "sessionName"
        )
        or display_name,
        "mode": _first_text(data, "mode") or "teleop",
        "runtime": _first_text(data, "runtime") or "CloudXR",
    }
    return app, session


def _normalise_televiz(descriptor: dict | None) -> dict:
    data = dict(descriptor or {})
    raw = data.get("televiz") or data.get("teleViz") or {}
    if not isinstance(raw, dict):
        raw = {}
    layers = raw.get("layers") or []
    if not isinstance(layers, list):
        layers = []
    timing = raw.get("timing") or {}
    if not isinstance(timing, dict):
        timing = {}
    return {
        "present": bool(raw.get("present", bool(raw))),
        "mode": _clean_str(raw.get("mode")) or "unknown",
        "state": _clean_str(raw.get("state")) or "not_reported",
        "layers": layers,
        "timing": timing,
    }


def _client_from_headset(headset: dict) -> dict:
    identity = (
        headset.get("identity") if isinstance(headset.get("identity"), dict) else {}
    )
    capabilities = (
        headset.get("capabilities")
        if isinstance(headset.get("capabilities"), dict)
        else {}
    )
    display_name = (
        _first_text(identity, "displayName", "display_name", "name")
        or _clean_str(headset.get("deviceLabel"))
        or "XR client"
    )
    return {
        "clientId": headset.get("clientId"),
        "identity": {
            **identity,
            "displayName": display_name,
            "deviceLabel": headset.get("deviceLabel"),
            "role": "headset",
        },
        "connection": {
            "connected": bool(headset.get("connected", True)),
            "registeredAt": headset.get("registeredAt"),
        },
        "stream": {
            "streaming": bool(headset.get("streaming", False)),
            "streamingSince": headset.get("streamingSince"),
        },
        "capabilities": capabilities,
        "metricsByCadence": headset.get("metricsByCadence") or {},
    }


def _build_preflight(
    *, config: dict, client_count: int, local_client_available: bool
) -> dict:
    server_ip = _clean_str(config.get("serverIP"))
    port = config.get("port")
    checks = [
        {
            "id": "hub-api",
            "label": "Hub API",
            "status": "pass",
            "detail": "state endpoint is serving",
        },
        {
            "id": "stream-target",
            "label": "Client entrypoint",
            "status": "pass" if server_ip and port is not None else "warn",
            "detail": f"{server_ip}:{port}"
            if server_ip and port is not None
            else "serverIP or port missing",
        },
        {
            "id": "hosted-client",
            "label": "Hosted client",
            "status": "pass" if local_client_available else "unknown",
            "detail": "/client/"
            if local_client_available
            else "enable --host-client for local hosting",
        },
        {
            "id": "xr-client",
            "label": "XR client",
            "status": "pass" if client_count else "unknown",
            "detail": f"{client_count} connected"
            if client_count
            else "waiting for client registration",
        },
        {
            "id": "firewall",
            "label": "Firewall reachability",
            "status": "unknown",
            "detail": "pending host preflight integration",
        },
    ]
    return {"status": _rollup_status(checks), "checks": checks}


def _build_metric_summary(headsets: list[dict]) -> dict:
    clients_connected = len(headsets)
    streaming_clients = sum(1 for h in headsets if h.get("streaming"))
    return {
        "clientsConnected": clients_connected,
        "streamingClients": streaming_clients,
        "frameRate": _latest_numeric_metric(headsets, _FRAME_RATE_KEYS),
        "latencyMs": _latest_numeric_metric(headsets, _LATENCY_KEYS),
    }


def _latest_numeric_metric(
    headsets: list[dict], names: tuple[str, ...]
) -> float | None:
    latest_at = -1
    latest_value: float | None = None
    wanted = set(names)
    for headset in headsets:
        by_cadence = headset.get("metricsByCadence") or {}
        if not isinstance(by_cadence, dict):
            continue
        for sample in by_cadence.values():
            if not isinstance(sample, dict):
                continue
            metrics = sample.get("metrics") or {}
            if not isinstance(metrics, dict):
                continue
            at = int(sample.get("at", 0) or 0)
            for key, value in metrics.items():
                if _metric_key(str(key)) in wanted and isinstance(value, (int, float)):
                    if at >= latest_at:
                        latest_at = at
                        latest_value = round(float(value), 2)
    return latest_value


def _append_client_query(base: str, config: dict) -> str:
    params: dict[str, str] = {"oobEnable": "1"}
    for key in _CLIENT_QUERY_FIELDS:
        if key not in config:
            continue
        value = config[key]
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            params[key] = "true" if value else "false"
        else:
            params[key] = str(value)
    clean_base = base.rstrip("/") + "/"
    sep = "&" if "?" in clean_base else "?"
    return clean_base + sep + urlencode(params)


def _rollup_status(checks: list[dict]) -> str:
    statuses = [c.get("status") for c in checks]
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    if "unknown" in statuses:
        return "unknown"
    return "pass"


def _preferred_join_kind(links: list[dict]) -> str | None:
    for link in links:
        if link.get("preferred"):
            return str(link.get("kind"))
    return None


def _first_text(data: dict, *keys: str) -> str | None:
    for key in keys:
        value = _clean_str(data.get(key))
        if value:
            return value
    return None


def _clean_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _metric_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum())
