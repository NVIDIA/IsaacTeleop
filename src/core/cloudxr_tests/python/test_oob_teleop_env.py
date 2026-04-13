# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for :mod:`oob_teleop_env` (bookmark URLs, env-driven defaults, LAN helpers)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from cloudxr_py_test_ns.oob_teleop_env import (
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


def test_build_headset_bookmark_url_with_token() -> None:
    u = build_headset_bookmark_url(
        web_client_base="https://h.test/",
        stream_config={"serverIP": "10.0.0.1", "port": 48322},
        control_token="secret123",
    )
    q = parse_qs(urlparse(u).query)
    assert q["controlToken"] == ["secret123"]


def test_build_headset_bookmark_url_with_codec() -> None:
    u = build_headset_bookmark_url(
        web_client_base="https://h.test/",
        stream_config={"serverIP": "10.0.0.1", "port": 48322, "codec": "av1"},
    )
    q = parse_qs(urlparse(u).query)
    assert q["codec"] == ["av1"]


def test_build_headset_bookmark_url_panel_hidden() -> None:
    u = build_headset_bookmark_url(
        web_client_base="https://h.test/",
        stream_config={
            "serverIP": "10.0.0.1",
            "port": 48322,
            "panelHiddenAtStart": True,
        },
    )
    q = parse_qs(urlparse(u).query)
    assert q["panelHiddenAtStart"] == ["true"]


def test_build_headset_bookmark_url_requires_server_ip() -> None:
    with pytest.raises(ValueError, match="serverIP"):
        build_headset_bookmark_url(
            web_client_base="https://h.test/",
            stream_config={"port": 48322},
        )


def test_client_ui_fields_from_env_empty(clear_teleop_env: None) -> None:
    assert client_ui_fields_from_env() == {}


def test_client_ui_fields_from_env_codec(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEOP_CLIENT_CODEC", "h265")
    fields = client_ui_fields_from_env()
    assert fields["codec"] == "h265"


def test_client_ui_fields_from_env_panel_hidden(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEOP_CLIENT_PANEL_HIDDEN_AT_START", "true")
    fields = client_ui_fields_from_env()
    assert fields["panelHiddenAtStart"] is True


def test_default_initial_stream_config_defaults(clear_teleop_env: None) -> None:
    cfg = default_initial_stream_config(48322)
    assert cfg["port"] == 48322
    assert "serverIP" in cfg


def test_default_initial_stream_config_env_override(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEOP_STREAM_SERVER_IP", "10.0.0.99")
    monkeypatch.setenv("TELEOP_STREAM_PORT", "50000")
    cfg = default_initial_stream_config(48322)
    assert cfg["serverIP"] == "10.0.0.99"
    assert cfg["port"] == 50000


def test_resolve_lan_host_from_env(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEOP_PROXY_HOST", "10.0.0.42")
    assert resolve_lan_host_for_oob() == "10.0.0.42"


def test_guess_lan_ipv4_returns_string_or_none() -> None:
    result = guess_lan_ipv4()
    assert result is None or isinstance(result, str)


def test_print_oob_hub_startup_banner(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("TELEOP_PROXY_HOST", "10.0.0.1")
    print_oob_hub_startup_banner(lan_host="10.0.0.1")
    out = capsys.readouterr().out
    assert "OOB TELEOP" in out
    assert "10.0.0.1" in out
    assert OOB_WS_PATH in out
