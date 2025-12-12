"""
Tests for the sample retargeter example.
"""

import pytest
from ..retargeters.examples.sample_retargeter import SampleRetargeter
from .. import (
    InputNode,
    TensorCollection,
    FloatType,
    RetargeterExecutor,
)


class FloatPairInputNode(InputNode):
    """Input node that produces two float values."""
    
    def __init__(self, name: str, value_x: float = 0.0, value_y: float = 0.0):
        self.value_x = value_x
        self.value_y = value_y
        super().__init__(name)
    
    def _define_outputs(self):
        return [TensorCollection(f"{self._name}_output", [
            FloatType(f"{self._name}_x"),
            FloatType(f"{self._name}_y"),
        ])]
    
    def update(self, outputs):
        outputs[0][0] = self.value_x
        outputs[0][1] = self.value_y


def test_sample_retargeter_basic():
    """Test basic functionality of SampleRetargeter."""
    # Create inputs
    values = FloatPairInputNode("values", 10.0, 20.0)
    params = FloatPairInputNode("params", 2.0, 5.0)  # scale, offset
    
    # Build graph
    retargeter = SampleRetargeter()
    retargeter.connect_inputs(values.output(0), params.output(0))
    
    # Create executor
    executor = RetargeterExecutor([retargeter])
    
    # Execute
    executor.execute()
    
    # Check results
    # scaled_x = 10 * 2 + 5 = 25
    # scaled_y = 20 * 2 + 5 = 45
    # sum = 25 + 45 = 70
    output = executor.get_output(retargeter, 0)
    assert output[0] == 25.0
    assert output[1] == 45.0
    assert output[2] == 70.0


def test_sample_retargeter_zero_scale():
    """Test SampleRetargeter with zero scale."""
    values = FloatPairInputNode("values", 10.0, 20.0)
    params = FloatPairInputNode("params", 0.0, 5.0)  # scale=0, offset=5
    
    retargeter = SampleRetargeter()
    retargeter.connect_inputs(values.output(0), params.output(0))
    
    executor = RetargeterExecutor([retargeter])
    executor.execute()
    
    # scaled_x = 10 * 0 + 5 = 5
    # scaled_y = 20 * 0 + 5 = 5
    # sum = 5 + 5 = 10
    output = executor.get_output(retargeter, 0)
    assert output[0] == 5.0
    assert output[1] == 5.0
    assert output[2] == 10.0


def test_sample_retargeter_negative_values():
    """Test SampleRetargeter with negative values."""
    values = FloatPairInputNode("values", -5.0, 10.0)
    params = FloatPairInputNode("params", 3.0, -2.0)  # scale=3, offset=-2
    
    retargeter = SampleRetargeter()
    retargeter.connect_inputs(values.output(0), params.output(0))
    
    executor = RetargeterExecutor([retargeter])
    executor.execute()
    
    # scaled_x = -5 * 3 + (-2) = -17
    # scaled_y = 10 * 3 + (-2) = 28
    # sum = -17 + 28 = 11
    output = executor.get_output(retargeter, 0)
    assert output[0] == -17.0
    assert output[1] == 28.0
    assert output[2] == 11.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

