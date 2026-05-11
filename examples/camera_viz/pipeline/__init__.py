# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Lightweight source → display orchestration for camera_viz.

Not a DAG framework — cameras feed Televiz directly. The renderer is the
only sink; sources are pull-based via ``latest()`` returning the freshest
GPU-resident frame (mailbox semantics matching QuadLayer's own 3-slot
internal mailbox).
"""

from .interface import Frame, FrameSource, SourceSpec
from .runner import VizRunner

__all__ = ["Frame", "FrameSource", "SourceSpec", "VizRunner"]
