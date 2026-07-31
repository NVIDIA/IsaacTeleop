# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

try:
    from ._orbbec_capture import Capture
except ImportError as exc:
    raise ImportError(
        "Orbbec camera_viz binding is not built. Run "
        "`orbbec/build.sh --orbbec-sdk-root PATH`."
    ) from exc

__all__ = ["Capture"]
