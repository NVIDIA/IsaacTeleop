# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Vendor-agnostic device output adapters consumed by ``DeviceOutputSink``."""

from .interface import Endpoint, IDeviceOutputAdapter
from .schema_push import SchemaPushOutputAdapter

__all__ = ["Endpoint", "IDeviceOutputAdapter", "SchemaPushOutputAdapter"]
