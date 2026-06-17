# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Path helpers for the workspace-local G1-Wuji teleop app."""

from __future__ import annotations

import sys
from pathlib import Path


def package_root() -> Path:
    return Path(__file__).resolve().parent


def app_root() -> Path:
    return package_root().parents[1]


def repo_root() -> Path:
    return app_root().parents[1]


def default_config_path() -> Path:
    return (app_root() / "config" / "avp_manus.yml").resolve()


def default_robot_usd_path() -> Path:
    return (app_root() / "assets" / "g1_wuji" / "g1_wuji.usd").resolve()


def resolve_repo_relative_path(relative_path: str | Path) -> Path:
    relative = Path(relative_path)
    app_path = app_root() / relative
    if app_path.exists():
        return app_path.resolve()
    return (app_root() / relative).resolve()


def ensure_import_paths() -> None:
    candidates = (
        app_root() / "python",
        repo_root() / "build-local" / "python_package" / "Release",
    )
    for path in candidates:
        if path.exists():
            path_str = str(path)
            if path_str not in sys.path:
                sys.path.insert(0, path_str)
