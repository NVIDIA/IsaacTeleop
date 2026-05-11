# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Camera / video sources for camera_viz.

Each source emits GPU-resident RGBA8 frames via the ``FrameSource``
contract. The first batch (M7a) lands sources that stay GPU-resident
end-to-end so the teleop hot path never round-trips through host memory.
"""

from .oakd import OakdSource
from .rtp_h264 import RtpH264Source
from .synthetic import SyntheticSource
from .v4l2 import V4l2Source
from .zed import ZedSource

__all__ = ["OakdSource", "RtpH264Source", "SyntheticSource", "V4l2Source", "ZedSource"]
