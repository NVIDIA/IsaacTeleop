# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""YAML-driven tmux launcher for Isaac Teleop rigs.

A *rig* is one teleop setup: the CloudXR runtime, one or more producer
plugins that publish device data, and one or more consumer apps (a Python
``TeleopSession`` script or a C++ binary) that read the streams. Rigs are
described by small YAML files (see ``rigs/se3_tracker.yaml`` in the Teleop
repository, and :mod:`~isaacteleop.rig.config` for the schema).

Usage::

    python -m isaacteleop.rig rigs/se3_tracker.yaml

The runtime pane starts immediately; producer/consumer panes are pre-typed
but NOT executed — press Enter in each pane after the headset connects.

The YAML schema is the stable contract; the Python API below is exported
for tests and power users on a best-effort basis.
"""

from .config import (
    ProcessConfig,
    RigConfig,
    RigConfigError,
    RigError,
    load_rig_config,
)
from .launcher import PreflightError, kill_rig, launch_rig

__all__ = [
    "PreflightError",
    "ProcessConfig",
    "RigConfig",
    "RigConfigError",
    "RigError",
    "kill_rig",
    "launch_rig",
    "load_rig_config",
]
