# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for hand-tracking provider parameter validation."""

from types import SimpleNamespace

import pytest
from constants import HandRetargeter, HandTrackingProvider, TeleopMode
from isaacteleop.teleop_session_manager import SessionMode
from node_parameters import _load_hand_tracking_provider


class _Logger:
    def info(self, _message: str) -> None:
        pass


class _Node:
    def __init__(self, **overrides) -> None:
        self._parameters = dict(overrides)
        self._logger = _Logger()

    def declare_parameter(self, name, default, _descriptor=None):
        self._parameters.setdefault(name, default)

    def get_parameter(self, name):
        value = self._parameters[name]
        parameter_value = SimpleNamespace(
            string_value=value if isinstance(value, str) else "",
            bool_value=value if isinstance(value, bool) else False,
        )
        return SimpleNamespace(get_parameter_value=lambda: parameter_value)

    def get_logger(self):
        return self._logger


def test_external_provider_is_preserved_without_plugin_paths(monkeypatch) -> None:
    monkeypatch.delenv("ISAAC_TELEOP_PLUGIN_PATH", raising=False)
    node = _Node(
        hand_tracking_provider="manus",
        start_hand_tracking_plugin=False,
    )

    provider, start_plugin, search_paths = _load_hand_tracking_provider(
        node,
        TeleopMode.CONTROLLER_TELEOP,
        HandRetargeter.DEXPILOT,
        SessionMode.LIVE,
    )

    assert provider == HandTrackingProvider.MANUS
    assert not start_plugin
    assert search_paths == ()


def test_replay_preserves_provider_when_plugin_startup_is_disabled() -> None:
    node = _Node(
        hand_tracking_provider="wuji",
        start_hand_tracking_plugin=False,
    )

    provider, start_plugin, _search_paths = _load_hand_tracking_provider(
        node,
        TeleopMode.CONTROLLER_TELEOP,
        HandRetargeter.WUJI,
        SessionMode.REPLAY,
    )

    assert provider == HandTrackingProvider.WUJI
    assert not start_plugin


def test_managed_plugin_requires_non_native_provider() -> None:
    node = _Node(
        hand_tracking_provider="native",
        start_hand_tracking_plugin=True,
    )

    with pytest.raises(
        ValueError,
        match="requires hand_tracking_provider:=manus or hand_tracking_provider:=wuji",
    ):
        _load_hand_tracking_provider(
            node,
            TeleopMode.CONTROLLER_TELEOP,
            HandRetargeter.DEXPILOT,
            SessionMode.LIVE,
        )


def test_replay_rejects_managed_plugin_startup() -> None:
    node = _Node(
        hand_tracking_provider="wuji",
        start_hand_tracking_plugin=True,
    )

    with pytest.raises(ValueError, match="must be false during MCAP replay"):
        _load_hand_tracking_provider(
            node,
            TeleopMode.CONTROLLER_TELEOP,
            HandRetargeter.WUJI,
            SessionMode.REPLAY,
        )


def test_non_native_provider_requires_tracked_hand_mode() -> None:
    node = _Node(
        hand_tracking_provider="manus",
        start_hand_tracking_plugin=False,
    )

    with pytest.raises(ValueError, match="requires a tracked-hand mode"):
        _load_hand_tracking_provider(
            node,
            TeleopMode.CONTROLLER_TELEOP,
            HandRetargeter.TRIHAND,
            SessionMode.LIVE,
        )


def test_managed_provider_requires_and_returns_plugin_paths(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("ISAAC_TELEOP_PLUGIN_PATH", str(tmp_path))
    node = _Node(
        hand_tracking_provider="wuji",
        start_hand_tracking_plugin=True,
    )

    provider, start_plugin, search_paths = _load_hand_tracking_provider(
        node,
        TeleopMode.HAND_TELEOP,
        HandRetargeter.DEXPILOT,
        SessionMode.LIVE,
    )

    assert provider == HandTrackingProvider.WUJI
    assert start_plugin
    assert search_paths == (tmp_path.resolve(),)


def test_managed_provider_requires_plugin_path(monkeypatch) -> None:
    monkeypatch.delenv("ISAAC_TELEOP_PLUGIN_PATH", raising=False)
    node = _Node(
        hand_tracking_provider="manus",
        start_hand_tracking_plugin=True,
    )

    with pytest.raises(FileNotFoundError, match="ISAAC_TELEOP_PLUGIN_PATH"):
        _load_hand_tracking_provider(
            node,
            TeleopMode.HAND_TELEOP,
            HandRetargeter.DEXPILOT,
            SessionMode.LIVE,
        )
