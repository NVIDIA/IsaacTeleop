#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Thin launcher for the G1-Wuji AVP + MANUS teleop application."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_app_import_path() -> None:
    example_root = Path(__file__).resolve().parents[1]
    app_python_dir = example_root / "python"
    path_str = str(app_python_dir)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def main() -> int:
    _ensure_app_import_path()
    from g1_wuji_teleop.cli import teleop_main

    return teleop_main()


if __name__ == "__main__":
    raise SystemExit(main())
