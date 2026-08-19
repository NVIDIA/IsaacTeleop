# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""TensorGroupType definitions for the latency_probe vendor I/O sample."""

from ..interface.tensor_group_type import TensorGroupType
from .ndarray_types import NDArrayType, DLDataType

NUM_LATENCY_PROBE_FIELDS = 2
"""Tensor slots in :func:`LatencyProbeTensor`: float32 value, uint32 sequence."""


def LatencyProbeTensor() -> TensorGroupType:
    """Probe payload as separate float32 value and uint32 sequence tensors."""
    return TensorGroupType(
        "latency_probe_tensor",
        [
            NDArrayType(
                "probe_value",
                shape=(1,),
                dtype=DLDataType.FLOAT,
                dtype_bits=32,
            ),
            NDArrayType(
                "probe_sequence",
                shape=(1,),
                dtype=DLDataType.UINT,
                dtype_bits=32,
            ),
        ],
    )
