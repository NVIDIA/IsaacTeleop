# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Camera / video sources for camera_viz.

Each source emits GPU-resident RGBA8 frames via the ``FrameSource``
contract. The first batch (M7a) lands sources that stay GPU-resident
end-to-end so the teleop hot path never round-trips through host memory.
"""

from .synthetic import SyntheticSource

__all__ = ["SyntheticSource"]
