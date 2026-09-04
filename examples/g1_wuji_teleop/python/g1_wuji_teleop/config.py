# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Configuration and path helpers for the G1-Wuji teleop example."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def package_root() -> Path:
    return Path(__file__).resolve().parent


def example_root() -> Path:
    return package_root().parents[1]


def default_config_path() -> Path:
    return (example_root() / "config" / "avp_manus.yaml").resolve()


def default_robot_usd_path() -> Path:
    return (example_root() / "assets" / "g1_wuji" / "g1_wuji.usd").resolve()


def example_path(relative_path: str | Path) -> Path:
    path = Path(relative_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (example_root() / path).resolve()


def load_yaml_file(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "PyYAML is required for G1-Wuji teleop configs."
        ) from exc

    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {path}")
    return data
