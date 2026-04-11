# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Make CloudXR python sources importable without installing ``isaacteleop``."""

from __future__ import annotations

import sys
from pathlib import Path

_CLOUDXR_PY = Path(__file__).resolve().parents[2] / "cloudxr" / "python"
if _CLOUDXR_PY.is_dir() and str(_CLOUDXR_PY) not in sys.path:
    sys.path.insert(0, str(_CLOUDXR_PY))
