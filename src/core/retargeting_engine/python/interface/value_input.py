# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Value Input Node - Generic typed placeholder for external graph inputs.

Provides a way to represent an externally-fed input as a proper graph node,
so it can be wired into connect() calls alongside other graph outputs.

Use ValueInput when you need to feed a simple value into the graph from
external code (e.g., from the simulator or caller) without defining a
custom BaseRetargeter subclass. It's a shortcut: one input, one output,
data passed straight through.
"""

from .base_retargeter import BaseRetargeter
from .retargeter_core_types import RetargeterIO, RetargeterIOType
from .tensor_group_type import TensorGroupType
from .tensor_group import OptionalTensorGroup


class ValueInput(BaseRetargeter):
    """
    Generic value-input node representing a single external input in the graph.

    Takes any TensorGroupType and creates a leaf node with one input and one
    output of that type. Data is fed externally (e.g., by TeleopSession) and
    passed straight through to the output.

    This is useful when a downstream node has multiple inputs, and some come
    from other graph nodes while others come from external code. Use
    ValueInput for the externally-provided ones so they can participate
    in connect() wiring.

    Inputs:
        - "value": TensorGroup of the specified type (fed externally)

    Outputs:
        - "value": TensorGroup of the same type (passthrough)

    Example:
        # HeadTransform has two inputs: "head" and "transform"
        # "head" comes from the graph, "transform" comes from TeleopSession

        from ..tensor_types import TransformMatrix

        transform_input = ValueInput("xform_input", TransformMatrix())
        head_xform = HeadTransform("head_xform")

        graph = head_xform.connect({
            "head": head_source.output("head"),
            "transform": transform_input.output("value"),
        })

        # At runtime, TeleopSession feeds data to the value input node:
        # leaf_inputs["xform_input"] = {"value": tensor_group_with_matrix}
    """

    VALUE = "value"

    def __init__(self, name: str, tensor_type: TensorGroupType) -> None:
        """
        Initialize a value input node.

        Args:
            name: Unique name for this node (used as the leaf input key).
            tensor_type: The TensorGroupType this node accepts and outputs.
        """
        self._tensor_type = tensor_type
        super().__init__(name)

    def input_spec(self) -> RetargeterIOType:
        """Single input of the specified type."""
        return {self.VALUE: self._tensor_type}

    def output_spec(self) -> RetargeterIOType:
        """Single output of the same type."""
        return {self.VALUE: self._tensor_type}

    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Copy all tensor values from input to output.

        Args:
            inputs: Dict with "value" TensorGroup (fed externally).
            outputs: Dict with "value" TensorGroup to populate.
        """
        inp: OptionalTensorGroup = inputs[self.VALUE]
        out: OptionalTensorGroup = outputs[self.VALUE]
        if inp.is_none:
            out.set_none()
            return
        for i in range(len(inp)):
            out[i] = inp[i]
