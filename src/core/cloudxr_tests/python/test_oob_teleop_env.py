# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for :mod:`oob_teleop_env` (bookmark URLs, env-driven defaults, LAN helpers)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import cloudxr_py_test_ns.oob_teleop_env as oob_teleop_env_under_test
import pytest

from cloudxr_py_test_ns.oob_teleop_env import (
    TELEOP_WEB_CLIENT_BASE_ENV,
    TELEOP_WEB_CLIENT_STATIC_DIR_ENV,
    USB_BACKEND_DEFAULT_PORT,
    USB_TURN_DEFAULT_PORT,
    USB_UI_DEFAULT_PORT,
    WSS_PROXY_DEFAULT_PORT,
    build_headset_bookmark_url,
    client_ui_fields_from_env,
    default_initial_stream_config,
    guess_lan_ipv4,
    print_oob_hub_startup_banner,
    require_usb_local_webxr_static_dir,
    resolve_lan_host_for_oob,
    usb_backend_port,
    usb_turn_port,
    usb_ui_port,
    web_client_base_override_from_env,
    wss_proxy_port,
)
from cloudxr_py_test_ns.oob_teleop_hub import OOB_WS_PATH


@pytest.fixture
def clear_teleop_env(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = (
        "PROXY_PORT",
        "USB_UI_PORT",
        "USB_BACKEND_PORT",
        "USB_TURN_PORT",
        "TELEOP_STREAM_SERVER_IP",
        "TELEOP_STREAM_PORT",
        "TELEOP_CLIENT_CODEC",
        "TELEOP_CLIENT_PANEL_HIDDEN_AT_START",
        "TELEOP_CLIENT_ROUTE",
        "TELEOP_WEB_CLIENT_BASE",
        "TELEOP_PROXY_HOST",
        "CONTROL_TOKEN",
        TELEOP_WEB_CLIENT_STATIC_DIR_ENV,
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


def test_usb_ui_port_default(clear_teleop_env: None) -> None:
    assert usb_ui_port() == USB_UI_DEFAULT_PORT


def test_usb_ui_port_from_env(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("USB_UI_PORT", "8081")
    assert usb_ui_port() == 8081


def test_usb_ui_port_invalid_env_raises(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("USB_UI_PORT", "not-a-port")
    with pytest.raises(ValueError, match="USB_UI_PORT"):
        usb_ui_port()


def test_usb_backend_port_default(clear_teleop_env: None) -> None:
    assert usb_backend_port() == USB_BACKEND_DEFAULT_PORT


def test_usb_backend_port_from_env(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("USB_BACKEND_PORT", "49200")
    assert usb_backend_port() == 49200


def test_usb_backend_port_invalid_env_raises(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("USB_BACKEND_PORT", "not-a-port")
    with pytest.raises(ValueError, match="USB_BACKEND_PORT"):
        usb_backend_port()


def test_usb_turn_port_default(clear_teleop_env: None) -> None:
    assert usb_turn_port() == USB_TURN_DEFAULT_PORT


def test_usb_turn_port_from_env(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("USB_TURN_PORT", "5349")
    assert usb_turn_port() == 5349


def test_usb_turn_port_invalid_env_raises(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("USB_TURN_PORT", "not-a-port")
    with pytest.raises(ValueError, match="USB_TURN_PORT"):
        usb_turn_port()


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


def test_build_headset_bookmark_url_default_route(clear_teleop_env: None) -> None:
    u = build_headset_bookmark_url(
        web_client_base="https://h.test/",
        stream_config={"serverIP": "10.0.0.1", "port": 48322},
    )
    assert urlparse(u).fragment == "/real/gear/dexmate"


def test_build_headset_bookmark_url_route_override(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEOP_CLIENT_ROUTE", "/sim/cube")
    u = build_headset_bookmark_url(
        web_client_base="https://h.test/",
        stream_config={"serverIP": "10.0.0.1", "port": 48322},
    )
    assert urlparse(u).fragment == "/sim/cube"


def test_build_headset_bookmark_url_route_strips_leading_hash(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Operators may write ``#/foo`` out of habit; we should produce ``#/foo``,
    # not ``##/foo``.
    monkeypatch.setenv("TELEOP_CLIENT_ROUTE", "#/foo/bar")
    u = build_headset_bookmark_url(
        web_client_base="https://h.test/",
        stream_config={"serverIP": "10.0.0.1", "port": 48322},
    )
    assert urlparse(u).fragment == "/foo/bar"
    assert "##" not in u


def test_build_headset_bookmark_url_route_empty_suppresses_fragment(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEOP_CLIENT_ROUTE", "")
    u = build_headset_bookmark_url(
        web_client_base="https://h.test/",
        stream_config={"serverIP": "10.0.0.1", "port": 48322},
    )
    assert urlparse(u).fragment == ""
    assert "#" not in u


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


def test_require_usb_local_webxr_static_dir_default_downloads(
    clear_teleop_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    # Path.home() consults $HOME on POSIX but %USERPROFILE% on Windows
    # (ntpath.expanduser ignores $HOME when USERPROFILE is set). Patch both
    # so the redirect works on every platform.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    def fake_fetch(url: str, *, timeout: float = 120.0) -> bytes:
        if url.endswith("index.html"):
            return b"<!doctype html><title>t</title>"
        if url.endswith("bundle.js"):
            return b"console.log(1);"
        raise AssertionError(url)

    monkeypatch.setattr(
        oob_teleop_env_under_test,
        "_fetch_url_bytes",
        fake_fetch,
    )
    out = require_usb_local_webxr_static_dir()
    expected = (tmp_path / ".cloudxr" / "static-client").resolve()
    assert out == expected
    assert (out / "index.html").read_bytes().startswith(b"<!doctype")
    assert b"console.log" in (out / "bundle.js").read_bytes()


def test_require_usb_local_webxr_static_dir_ok(
    clear_teleop_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    (tmp_path / "index.html").write_text(
        "<!doctype html><title>x</title>", encoding="utf-8"
    )
    (tmp_path / "bundle.js").write_text("// bundle", encoding="utf-8")
    monkeypatch.setenv(TELEOP_WEB_CLIENT_STATIC_DIR_ENV, str(tmp_path))
    assert require_usb_local_webxr_static_dir() == tmp_path.resolve()


def test_require_usb_local_webxr_static_dir_not_a_directory(
    clear_teleop_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    bogus = tmp_path / "file_not_dir"
    bogus.write_text("x", encoding="utf-8")
    monkeypatch.setenv(TELEOP_WEB_CLIENT_STATIC_DIR_ENV, str(bogus))
    with pytest.raises(RuntimeError, match="not a directory"):
        require_usb_local_webxr_static_dir()


def test_print_oob_hub_startup_banner(
    clear_teleop_env: None, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("TELEOP_PROXY_HOST", "10.0.0.1")
    print_oob_hub_startup_banner(lan_host="10.0.0.1")
    out = capsys.readouterr().out
    assert "OOB TELEOP" in out
    assert "10.0.0.1" in out
    assert OOB_WS_PATH in out


# Host preflight (H5) ------------------------------------------------------


from unittest.mock import MagicMock, patch  # noqa: E402

from cloudxr_py_test_ns.oob_teleop_env import (  # noqa: E402
    _ufw_unallowed_ports,
    print_host_preflight_warnings,
)


@patch("cloudxr_py_test_ns.oob_teleop_env.subprocess.run")
def test_ufw_unallowed_ports_inactive_returns_none(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="Status: inactive\n")
    assert _ufw_unallowed_ports([48322]) is None


@patch(
    "cloudxr_py_test_ns.oob_teleop_env.subprocess.run", side_effect=FileNotFoundError()
)
def test_ufw_unallowed_ports_no_ufw_returns_none(mock_run: MagicMock) -> None:
    assert _ufw_unallowed_ports([48322]) is None


@patch("cloudxr_py_test_ns.oob_teleop_env.subprocess.run")
def test_ufw_unallowed_ports_active_with_allow(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=(
            "Status: active\n\n"
            "To                         Action      From\n"
            "--                         ------      ----\n"
            "48322/tcp                  ALLOW       Anywhere\n"
        ),
    )
    assert _ufw_unallowed_ports([48322]) == []


@patch("cloudxr_py_test_ns.oob_teleop_env.subprocess.run")
def test_ufw_unallowed_ports_active_missing_allow(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=(
            "Status: active\n\n"
            "To                         Action      From\n"
            "22/tcp                     ALLOW       Anywhere\n"
        ),
    )
    assert _ufw_unallowed_ports([48322]) == [48322]


def test_print_host_preflight_warnings_clean(capsys) -> None:
    with (
        patch("cloudxr_py_test_ns.oob_teleop_env._port_in_use", return_value=False),
        patch(
            "cloudxr_py_test_ns.oob_teleop_env._ufw_unallowed_ports", return_value=None
        ),
    ):
        print_host_preflight_warnings(usb_local=False)
    assert capsys.readouterr().out == ""


def test_print_host_preflight_warnings_busy_port(capsys) -> None:
    with (
        patch("cloudxr_py_test_ns.oob_teleop_env._port_in_use", return_value=True),
        patch(
            "cloudxr_py_test_ns.oob_teleop_env._ufw_unallowed_ports", return_value=None
        ),
    ):
        print_host_preflight_warnings(usb_local=False)
    out = capsys.readouterr().out
    assert "already in use" in out
    assert "PROXY_PORT" in out


def test_print_host_preflight_warnings_ufw_blocks(capsys) -> None:
    with (
        patch("cloudxr_py_test_ns.oob_teleop_env._port_in_use", return_value=False),
        patch(
            "cloudxr_py_test_ns.oob_teleop_env._ufw_unallowed_ports",
            return_value=[48322],
        ),
    ):
        print_host_preflight_warnings(usb_local=False)
    out = capsys.readouterr().out
    assert "ufw" in out
    assert "sudo ufw allow 48322/tcp" in out


def test_print_host_preflight_warnings_skips_ufw_in_usb_local(capsys) -> None:
    with (
        patch("cloudxr_py_test_ns.oob_teleop_env._port_in_use", return_value=False),
        patch(
            "cloudxr_py_test_ns.oob_teleop_env._ufw_unallowed_ports",
            return_value=[48322],
        ) as mock_ufw,
    ):
        print_host_preflight_warnings(usb_local=True)
    assert mock_ufw.call_count == 0
    assert capsys.readouterr().out == ""
