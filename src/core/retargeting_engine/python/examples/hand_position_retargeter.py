# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Hand Position Retargeter Module.

Demonstrates proper NDArray handling with DLPack conversions.
Takes hand tracking positions and applies transformations using numpy operations.
"""

import numpy as np
from typing import Dict
from ..interface.retargeting_module import BaseRetargeter, RetargeterIO
from ..interface.tensor_group_type import TensorGroupType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import FloatType, NDArrayType, DLDataType, DLDeviceType


class HandPositionRetargeter(BaseRetargeter):
    """
    Hand position retargeter that transforms hand positions with scale and offset.
    
    This retargeter demonstrates proper NDArray handling:
    - Convert NDArray inputs to numpy arrays using np.from_dlpack()
    - Perform numpy operations
    - Assign numpy results to NDArray outputs (automatically converts via DLPack)
    
    Inputs:
        - "left_hand": 3D position array (x, y, z)
        - "right_hand": 3D position array (x, y, z)
        - "transform": scale (float) and offset array (3D)
    
    Outputs:
        - "left_hand_transformed": transformed 3D position
        - "right_hand_transformed": transformed 3D position
        - "distance": scalar distance between transformed hands
    
    Transformation:
        - transformed = position * scale + offset
        - distance = ||left_transformed - right_transformed||
    """
    
    def __init__(self, name: str) -> None:
        """
        Initialize hand position retargeter.
        
        Args:
            name: Name identifier for this retargeter (must be unique)
        """
        super().__init__(name=name)
    
    def input_spec(self) -> RetargeterIO:
        """Define input collections."""
        return {
            "left_hand": TensorGroupType("left_hand", [
                NDArrayType("position", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32)
            ]),
            "right_hand": TensorGroupType("right_hand", [
                NDArrayType("position", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32)
            ]),
            "transform": TensorGroupType("transform", [
                FloatType("scale"),
                NDArrayType("offset", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32)
            ])
        }
    
    def output_spec(self) -> RetargeterIO:
        """Define output collections."""
        return {
            "left_hand_transformed": TensorGroupType("left_hand_transformed", [
                NDArrayType("position", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32)
            ]),
            "right_hand_transformed": TensorGroupType("right_hand_transformed", [
                NDArrayType("position", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32)
            ]),
            "distance": TensorGroupType("distance", [
                FloatType("value")
            ])
        }
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        """
        Execute the hand position retargeting transformation.
        
        Demonstrates proper NDArray handling with DLPack protocol:
        1. Convert input NDArrays to numpy using np.from_dlpack()
        2. Perform numpy operations
        3. Assign numpy results directly to outputs (auto-converts via DLPack)
        
        Args:
            inputs: Dict with "left_hand", "right_hand", and "transform" TensorGroups
            outputs: Dict with "left_hand_transformed", "right_hand_transformed", "distance"
        """
        # ==============================================================================
        # Step 1: Convert NDArray inputs to numpy arrays using DLPack
        # ==============================================================================
        
        # Get input groups
        left_hand_group = inputs["left_hand"]
        right_hand_group = inputs["right_hand"]
        transform_group = inputs["transform"]
        
        # Convert NDArray tensors to numpy arrays
        left_pos = np.from_dlpack(left_hand_group[0])      # shape (3,) float32
        right_pos = np.from_dlpack(right_hand_group[0])    # shape (3,) float32
        scale = transform_group[0]                         # FloatType - already a scalar
        offset = np.from_dlpack(transform_group[1])        # shape (3,) float32
        
        # ==============================================================================
        # Step 2: Perform numpy operations
        # ==============================================================================
        
        # Apply transformation: transformed = position * scale + offset
        left_transformed = left_pos * scale + offset
        right_transformed = right_pos * scale + offset
        
        # Calculate distance between transformed positions
        distance = float(np.linalg.norm(left_transformed - right_transformed))
        
        # ==============================================================================
        # Step 3: Assign results to outputs
        # ==============================================================================
        
        # Get output groups
        left_out_group = outputs["left_hand_transformed"]
        right_out_group = outputs["right_hand_transformed"]
        distance_out_group = outputs["distance"]
        
        # Assign numpy arrays to NDArray outputs (auto-converts via DLPack)
        left_out_group[0] = left_transformed.astype(np.float32)   # Ensure float32
        right_out_group[0] = right_transformed.astype(np.float32)
        
        # Assign scalar to FloatType output
        distance_out_group[0] = distance

