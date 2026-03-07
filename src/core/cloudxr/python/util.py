# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Path helpers for CloudXR run and log directories.

Respects CXR_HOST_VOLUME_PATH when set (e.g. by setup_cloudxr_env.sh or .env);
otherwise defaults to ~/.cloudxr (run and logs under that volume).
"""

import os
from pathlib import Path


def _cloudxr_root_path() -> str:
    """Return the CloudXR volume root (CXR_HOST_VOLUME_PATH or default ~/.cloudxr)."""
    raw = os.environ.get("CXR_HOST_VOLUME_PATH")
    if raw:
        return os.path.abspath(os.path.expanduser(raw))

    if os.environ.get("HOME"):
        return os.path.abspath(os.path.join(os.environ["HOME"], ".cloudxr"))

    raise RuntimeError(
        "Failed to determine CloudXR volume path (set CXR_HOST_VOLUME_PATH or HOME)"
    )


def openxr_run_dir() -> str:
    """Return the CloudXR OpenXR run directory (volume/run, e.g. ~/.cloudxr/run)."""
    return os.path.join(_cloudxr_root_path(), "run")


def ensure_logs_dir() -> Path:
    """Return the directory for CloudXR log files (volume/logs, e.g. ~/.cloudxr/logs)."""
    logs_dir = Path(_cloudxr_root_path()) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir
