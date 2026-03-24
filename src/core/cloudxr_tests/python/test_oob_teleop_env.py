# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for :mod:`oob_teleop_env` (bookmark URLs, env-driven defaults, LAN helpers).

Uses ``cloudxr_py_test_ns`` from ``conftest`` so relative imports inside the package resolve.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

import pytest

from cloudxr_py_test_ns.oob_teleop_env import (
    CHROME_INSPECT_DEVICES_URL,
    TELEOP_WEB_CLIENT_BASE_ENV,
    WSS_PROXY_DEFAULT_PORT,
    build_headset_bookmark_url,
    client_ui_fields_from_env,
    default_initial_stream_config,
    guess_lan_ipv4,
    print_oob_hub_startup_banner,
    resolve_lan_host_for_oob,
    web_client_base_override_from_env,
    wss_proxy_port,
)
from cloudxr_py_test_ns.oob_teleop_hub import OOB_WS_PATH


@pytest.fixture
def clear_teleop_env(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = (
        "PROXY_PORT",
        "TELEOP_STREAM_SERVER_IP",
        "TELEOP_STREAM_PORT",
        "TELEOP_CLIENT_CODEC",
        "TELEOP_CLIENT_PANEL_HIDDEN_AT_START",
        "TELEOP_CLIENT_PER_EYE_WIDTH",
        "TELEOP_CLIENT_PER_EYE_HEIGHT",
        "TELEOP_WEB_CLIENT_BASE",
        "TELEOP_PROXY_HOST",
        "CONTROL_TOKEN",
    )
    for k in keys:
        monkeypatch.delenv(k, raising=False)


def test_wss_proxy_port_default(clear_teleop_env: None) -> None:
    assert wss_proxy_port() == WSS_PROXY_DEFAULT_PORT


def test_wss_proxy_port_from_env(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROXY_PORT", "50000")
    assert wss_proxy_port() == 50000


def test_web_client_base_override_from_env(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert web_client_base_override_from_env() is None
    monkeypatch.setenv(TELEOP_WEB_CLIENT_BASE_ENV, "  https://example.test/app  ")
    assert web_client_base_override_from_env() == "https://example.test/app"


def test_build_headset_bookmark_url_minimal() -> None:
    u = build_headset_bookmark_url(
        web_client_base="https://h.test/",
        stream_config={"serverIP": "10.0.0.1", "port": 48322},
    )
    assert urlparse(u).hostname == "h.test"
    q = parse_qs(urlparse(u).query)
    assert q["oobEnable"] == ["1"]
    assert q["serverIP"] == ["10.0.0.1"]
    assert q["port"] == ["48322"]


def test_build_headset_bookmark_url_appends_when_base_has_query() -> None:
    u = build_headset_bookmark_url(
        web_client_base="https://h.test/page?x=1",
        stream_config={"serverIP": "1.1.1.1", "port": 1},
    )
    q = parse_qs(urlparse(u).query)
    assert q["x"] == ["1"]
    assert q["oobEnable"] == ["1"]
    assert q["serverIP"] == ["1.1.1.1"]


def test_build_headset_bookmark_url_token_and_media_and_codec() -> None:
    u = build_headset_bookmark_url(
        web_client_base="https://x/",
        stream_config={
            "serverIP": "192.168.0.2",
            "port": 99,
            "mediaAddress": "192.168.0.2",
            "mediaPort": 47998,
            "codec": "h265",
            "panelHiddenAtStart": True,
            "perEyeWidth": 1920,
            "perEyeHeight": 1680,
        },
        control_token="tok",
    )
    q = parse_qs(urlparse(u).query)
    assert q["controlToken"] == ["tok"]
    assert q["codec"] == ["h265"]
    assert q["panelHiddenAtStart"] == ["true"]
    assert q["mediaPort"] == ["47998"]
    assert q["perEyeWidth"] == ["1920"]


def test_build_headset_bookmark_url_requires_server_ip_and_port() -> None:
    with pytest.raises(ValueError, match="serverIP and port"):
        build_headset_bookmark_url(
            web_client_base="https://x/",
            stream_config={"serverIP": "", "port": 1},
        )
    with pytest.raises(ValueError, match="serverIP and port"):
        build_headset_bookmark_url(
            web_client_base="https://x/",
            stream_config={"serverIP": "1.2.3.4"},
        )


def test_default_initial_stream_config_uses_env_and_fallback(
    clear_teleop_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cloudxr_py_test_ns.oob_teleop_env.guess_lan_ipv4", lambda: None
    )
    cfg = default_initial_stream_config(5555)
    assert cfg == {"serverIP": "127.0.0.1", "port": 5555}

    monkeypatch.setenv("TELEOP_STREAM_SERVER_IP", "10.0.0.5")
    monkeypatch.setenv("TELEOP_STREAM_PORT", "6000")
    cfg2 = default_initial_stream_config(5555)
    assert cfg2 == {"serverIP": "10.0.0.5", "port": 6000}


def test_client_ui_fields_from_env(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert client_ui_fields_from_env() == {}

    monkeypatch.setenv("TELEOP_CLIENT_CODEC", "av1")
    monkeypatch.setenv("TELEOP_CLIENT_PANEL_HIDDEN_AT_START", "yes")
    monkeypatch.setenv("TELEOP_CLIENT_PER_EYE_WIDTH", "100")
    monkeypatch.setenv("TELEOP_CLIENT_PER_EYE_HEIGHT", "200")
    d = client_ui_fields_from_env()
    assert d["codec"] == "av1"
    assert d["panelHiddenAtStart"] is True
    assert d["perEyeWidth"] == 100
    assert d["perEyeHeight"] == 200


def test_client_ui_fields_from_env_invalid_width_warns(
    clear_teleop_env: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("TELEOP_CLIENT_PER_EYE_WIDTH", "nope")
    caplog.set_level(logging.WARNING)
    d = client_ui_fields_from_env()
    assert "perEyeWidth" not in d
    assert any("TELEOP_CLIENT_PER_EYE_WIDTH" in r.message for r in caplog.records)


def test_resolve_lan_host_prefers_teleop_proxy_host(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEOP_PROXY_HOST", "  10.10.10.10 ")
    assert resolve_lan_host_for_oob() == "10.10.10.10"


def test_resolve_lan_host_runtime_error_when_unresolvable(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cloudxr_py_test_ns.oob_teleop_env.guess_lan_ipv4", lambda: None
    )
    with pytest.raises(RuntimeError, match="TELEOP_PROXY_HOST"):
        resolve_lan_host_for_oob()


def test_guess_lan_ipv4_returns_none_on_loopback_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSock:
        def __enter__(self) -> FakeSock:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def settimeout(self, _t: float) -> None:
            return None

        def connect(self, _a: object) -> None:
            return None

        def getsockname(self) -> tuple[str, int]:
            return ("127.0.0.1", 12345)

    monkeypatch.setattr(
        "cloudxr_py_test_ns.oob_teleop_env.socket.socket", lambda *a, **k: FakeSock()
    )
    assert guess_lan_ipv4() is None


def test_guess_lan_ipv4_returns_address_when_non_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSock:
        def __enter__(self) -> FakeSock:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def settimeout(self, _t: float) -> None:
            return None

        def connect(self, _a: object) -> None:
            return None

        def getsockname(self) -> tuple[str, int]:
            return ("192.168.50.2", 44444)

    monkeypatch.setattr(
        "cloudxr_py_test_ns.oob_teleop_env.socket.socket", lambda *a, **k: FakeSock()
    )
    assert guess_lan_ipv4() == "192.168.50.2"


def test_print_oob_hub_startup_banner_tethered(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TELEOP_PROXY_HOST", "192.168.42.1")
    print_oob_hub_startup_banner(oob_mode="tethered")
    out = capsys.readouterr().out
    assert "OOB TELEOP" in out
    assert "tethered" in out.lower()
    assert "192.168.42.1" in out
    assert CHROME_INSPECT_DEVICES_URL in out
    assert f"wss://192.168.42.1:{WSS_PROXY_DEFAULT_PORT}{OOB_WS_PATH}" in out


def test_print_oob_hub_startup_banner_wireless_with_lan_host(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "cloudxr_py_test_ns.oob_teleop_env.guess_lan_ipv4", lambda: None
    )
    print_oob_hub_startup_banner(oob_mode="wireless", lan_host="172.16.0.5")
    out = capsys.readouterr().out
    assert "wireless" in out.lower() or "Wireless" in out
    assert "172.16.0.5" in out
    assert f"wss://172.16.0.5:{WSS_PROXY_DEFAULT_PORT}{OOB_WS_PATH}" in out
