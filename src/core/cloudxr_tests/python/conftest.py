# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Make ``teleop_ws_hub`` importable without installing the full ``isaacteleop`` package."""

from __future__ import annotations

import sys
from pathlib import Path

_CLOUDXR_PY = Path(__file__).resolve().parents[2] / "cloudxr" / "python"
if _CLOUDXR_PY.is_dir() and str(_CLOUDXR_PY) not in sys.path:
    sys.path.insert(0, str(_CLOUDXR_PY))
