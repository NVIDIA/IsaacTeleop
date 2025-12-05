"""
Sample Retargeter Node.

Example implementation that demonstrates multiple input collections.

Inputs:
- Collection 0 "values": two floats at indices 0 (x) and 1 (y)
- Collection 1 "params": two floats at indices 0 (scale) and 1 (offset)

Outputs:
- Collection 0 "results": three floats at indices 0 (scaled_x), 1 (scaled_y), and 2 (sum)

Transformation:
- scaled_x = x * scale + offset
- scaled_y = y * scale + offset
- sum = scaled_x + scaled_y
"""

from typing import List, Optional
from ...tensor_types.examples.scalar_types import FloatType
from ...interface.tensor_collection import TensorCollection
from ...interface.tensor_group import TensorGroup
from ...interface.retargeter_node import RetargeterNode
from ...interface.output_selector import OutputSelector


class SampleRetargeter(RetargeterNode):
    """
    Sample retargeter demonstrating multiple input collections.
    
    Inputs:
        - Collection 0 "values": index 0 (x), index 1 (y)
        - Collection 1 "params": index 0 (scale), index 1 (offset)
    
    Outputs:
        - Collection 0 "results": index 0 (scaled_x), index 1 (scaled_y), index 2 (sum)
    
    Transformation:
        - scaled_x = x * scale + offset
        - scaled_y = y * scale + offset
        - sum = scaled_x + scaled_y
    """
    
    def __init__(self, name: str = "sample_retargeter") -> None:
        """
        Initialize sample retargeter.
        
        Args:
            name: Name identifier for this retargeter
        """
        super().__init__(name=name)
    
    def connect_inputs(self, value_inputs: OutputSelector, param_inputs: OutputSelector) -> None:
        """
        Connect the sample retargeter to its input sources.
        
        Args:
            value_inputs: OutputSelector for values input (x, y)
            param_inputs: OutputSelector for params input (scale, offset)
        """
        self.connect([value_inputs, param_inputs])
    
    def _define_inputs(self) -> List[TensorCollection]:
        """Define input collections."""
        return [
            TensorCollection("values", [
                FloatType("x"),
                FloatType("y")
            ]),
            TensorCollection("params", [
                FloatType("scale"),
                FloatType("offset")
            ])
        ]
    
    def _define_outputs(self) -> List[TensorCollection]:
        """Define output collections."""
        return [
            TensorCollection("results", [
                FloatType("scaled_x"),
                FloatType("scaled_y"),
                FloatType("sum")
            ])
        ]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup], output_mask: Optional[List[bool]] = None) -> None:
        """
        Execute the retargeting transformation using index-based access.
        
        Writes directly to pre-allocated outputs for direct assignment performance.
        
        Args:
            inputs: List with two input TensorGroups (values at 0, params at 1)
            outputs: List with one output TensorGroup at index 0 (pre-allocated)
            output_mask: Optional mask for which outputs to compute. If None, compute all.
        """
        # Get input groups by index (fast)
        values_group = inputs[0]  # "values" collection
        params_group = inputs[1]  # "params" collection
        output_group = outputs[0]  # "results" collection
        
        # Get input values by index (O(1) access)
        x = values_group[0]      # "x" at index 0
        y = values_group[1]      # "y" at index 1
        scale = params_group[0]  # "scale" at index 0
        offset = params_group[1] # "offset" at index 1
        
        # Compute transformations and write directly to output (respecting mask)
        if output_mask is None or output_mask[0]:
            scaled_x = x * scale + offset
            output_group[0] = scaled_x   # "scaled_x" at index 0
        
        if output_mask is None or output_mask[0]:
            scaled_y = y * scale + offset
            output_group[1] = scaled_y   # "scaled_y" at index 1
        
        if output_mask is None or output_mask[0]:
            # Need scaled values for sum
            if output_mask is not None and not output_mask[0]:
                # If we skipped computing them above, compute now
                scaled_x = x * scale + offset
                scaled_y = y * scale + offset
            sum_value = scaled_x + scaled_y
            output_group[2] = sum_value  # "sum" at index 2

