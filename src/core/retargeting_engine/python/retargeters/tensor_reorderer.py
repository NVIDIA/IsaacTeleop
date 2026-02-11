# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tensor Reorderer Retargeter.

A generic retargeter that reorders inputs and flattens them into a single NDArray.
"""

from typing import Dict, List, Tuple, Optional
import numpy as np

from ..interface import (
    BaseRetargeter,
    RetargeterIOType,
    TensorGroup,
    TensorGroupType,
)
from ..tensor_types import FloatType, NDArrayType, DLDataType


class TensorReorderer(BaseRetargeter):
    """
    A retargeter that reorders inputs and flattens them into a single NDArray.

    This is useful for preparing a final action vector for simulation environments (like Isaac Lab)
    that expect a specific order of joint values or action terms.

    It supports inputs that are:
    1. TensorGroups of scalar FloatTypes (e.g. from DexHandRetargeter)
    2. TensorGroups containing NDArrays (e.g. from Se3Retargeter)

    Output:
        "output": A TensorGroup containing a SINGLE tensor ("action_flat") which is
                  a 1D numpy array of float32 values in the specified order.
    """

    def __init__(
        self,
        input_config: Dict[str, List[str]],
        output_order: List[str],
        name: str,
        input_types: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Initialize the reorderer.

        Args:
            input_config: Dict mapping input names to the list of joint/element names they contain.
                          e.g. {
                              "left_hand": ["joint_1", "joint_2"],
                              "right_arm_ik": ["pos_x", "pos_y", "pos_z", "quat_x", ...]
                          }
            output_order: List of names in the desired output order.
                          e.g. ["pos_x", "pos_y", ..., "joint_1", "joint_2"]
            name: Name identifier for this retargeter
            input_types: Optional dict mapping input names to "scalar" (default) or "array".
                         "scalar": Expects a list of FloatType tensors (e.g. DexHand).
                         "array": Expects a single NDArrayType tensor (e.g. Se3).
        """
        self._input_config = input_config
        self._output_order = output_order
        self._output_len = len(output_order)
        self._input_types = input_types or {}

        super().__init__(name=name)

        # Pre-calculate mapping indices
        # List of tuples: (input_name, source_index, target_index)
        self._mapping: List[Tuple[str, int, int]] = []

        for target_idx, element_name in enumerate(output_order):
            found = False
            for input_name, source_elements in input_config.items():
                if element_name in source_elements:
                    source_idx = source_elements.index(element_name)
                    self._mapping.append((input_name, source_idx, target_idx))
                    found = True
                    break

            if not found:
                # If an element in output_order is not found in inputs, it will remain 0.0 (default)
                pass

    def input_spec(self) -> RetargeterIOType:
        """Define input collections based on config."""
        inputs = {}
        for input_name, element_names in self._input_config.items():
            input_type = self._input_types.get(input_name, "scalar")

            if input_type == "array":
                inputs[input_name] = TensorGroupType(
                    input_name,
                    [
                        NDArrayType(
                            "array_input",
                            shape=(len(element_names),),
                            dtype=DLDataType.FLOAT,
                            dtype_bits=32
                        )
                    ]
                )
            else:
                inputs[input_name] = TensorGroupType(
                    input_name,
                    [FloatType(name) for name in element_names]
                )
        return inputs

    def output_spec(self) -> RetargeterIOType:
        """Define output as a single 1D NDArray."""
        return {
            "output": TensorGroupType("output", [
                NDArrayType(
                    "action_flat",
                    shape=(self._output_len,),
                    dtype=DLDataType.FLOAT,
                    dtype_bits=32
                )
            ])
        }

    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        """
        Gather values and pack them into a single numpy array.
        """
        # Allocate the flat array (float32 for Isaac Lab/Torch compatibility)
        flat_action = np.zeros((self._output_len,), dtype=np.float32)

        # Cache flattened inputs to handle both scalars and arrays uniformly
        flattened_inputs = {}
        for name, group in inputs.items():
            # Check if group contains a single NDArray (like Se3Retargeter)
            if len(group) == 1 and isinstance(group[0], (np.ndarray, list, tuple)):
                 # It's likely an array wrapped in a TensorGroup
                 val = group[0]
                 if hasattr(val, "flatten"):
                     flattened_inputs[name] = val.flatten()
                 else:
                     flattened_inputs[name] = np.array(val).flatten()
            else:
                # It's likely a group of scalars (like DexHandRetargeter)
                # We can treat the group itself as the list
                flattened_inputs[name] = group

        # Fill the array using our pre-calculated mapping
        for input_name, src_idx, dst_idx in self._mapping:
            # Extract value from the appropriate source
            source = flattened_inputs.get(input_name)

            if source is not None:
                # If source is a TensorGroup (list-like), we access by index.
                # If source is a numpy array, we access by index.
                try:
                    val = source[src_idx]
                    flat_action[dst_idx] = float(val)
                except (IndexError, TypeError):
                    # Fallback or error logging
                    pass

        # Set the single output tensor
        outputs["output"][0] = flat_action
