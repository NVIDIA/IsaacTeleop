# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Interface module for retargeting engine type system."""

from .tensor_type import TensorType
from .tensor_group_type import TensorGroupType

__all__ = [
    "TensorType",
    "TensorGroupType",
]

