"""
Test for RetargeterExecutor with simple float-based compute graphs.

Uses simple float operations to test compute graphs with various tensor patterns.
"""

import pytest
import math
from .. import (
    InputNode,
    RetargeterNode,
    TensorCollection,
    FloatType,
    RetargeterExecutor,
    OutputSelector,
)


# ============================================================================
# Input Nodes
# ============================================================================

class FloatInputNode(InputNode):
    """Input node that produces a single float value."""
    
    def __init__(self, name: str, initial_value: float = 0.0):
        self.value = initial_value
        super().__init__(name)
    
    def _define_outputs(self):
        return [TensorCollection(f"{self._name}_output", [
            FloatType(f"{self._name}_value")
        ])]
    
    def output(self) -> OutputSelector:
        return OutputSelector(self, 0)
    
    def update(self, outputs):
        outputs[0][0] = self.value


# ============================================================================
# Basic Operation Retargeters
# ============================================================================

class AddRetargeter(RetargeterNode):
    """Adds two float inputs: result = a + b."""
    
    def __init__(self, name="add"):
        super().__init__(name=name)
    
    def _define_inputs(self):
        return [
            TensorCollection("input_a", [FloatType("input_a_value")]),
            TensorCollection("input_b", [FloatType("input_b_value")]),
        ]
    
    def _define_outputs(self):
        return [TensorCollection("output", [
            FloatType("add_result")
        ])]
    
    def execute(self, inputs, outputs, output_mask=None):
        a = inputs[0][0]
        b = inputs[1][0]
        outputs[0][0] = a + b


class MultiplyRetargeter(RetargeterNode):
    """Multiplies two float inputs: result = a * b."""
    
    def __init__(self, name="multiply"):
        super().__init__(name=name)
    
    def _define_inputs(self):
        return [
            TensorCollection("input_a", [FloatType("input_a_value")]),
            TensorCollection("input_b", [FloatType("input_b_value")]),
        ]
    
    def _define_outputs(self):
        return [TensorCollection("output", [
            FloatType("multiply_result")
        ])]
    
    def execute(self, inputs, outputs, output_mask=None):
        a = inputs[0][0]
        b = inputs[1][0]
        outputs[0][0] = a * b


# ============================================================================
# Tests
# ============================================================================

def test_simple_add():
    """Test a simple add operation: 5 + 3 = 8."""
    # Create inputs
    input_a = FloatInputNode("a", 5.0)
    input_b = FloatInputNode("b", 3.0)
    
    # Build graph
    add = AddRetargeter()
    add.connect([input_a.output(), input_b.output()])
    
    # Create executor
    executor = RetargeterExecutor([add])
    
    # Execute
    executor.execute()
    
    # Check result
    result = executor.get_output(add, 0)[0]
    assert result == 8.0


def test_chained_operations():
    """Test chained operations: (5 + 3) * 2 = 16."""
    # Create inputs
    input_a = FloatInputNode("a", 5.0)
    input_b = FloatInputNode("b", 3.0)
    input_c = FloatInputNode("c", 2.0)
    
    # Build graph
    add = AddRetargeter(name="add")
    add.connect([input_a.output(), input_b.output()])
    multiply = MultiplyRetargeter(name="multiply")
    multiply.connect([add.output(0), input_c.output()])
    
    # Create executor
    executor = RetargeterExecutor([multiply])
    
    # Execute
    executor.execute()
    
    # Check result
    result = executor.get_output(multiply, 0)[0]
    assert result == 16.0


def test_diamond_graph():
    """Test diamond-shaped graph where one node feeds two nodes that both feed a final node.
    
    Graph:
        input_a (5)
           |
         add_ab (5 + 3 = 8)
        /     \\
    mult_1    mult_2
    (8*2=16)  (8*4=32)
        \\     /
        add_final (16 + 32 = 48)
    """
    # Create inputs
    input_a = FloatInputNode("a", 5.0)
    input_b = FloatInputNode("b", 3.0)
    input_c = FloatInputNode("c", 2.0)
    input_d = FloatInputNode("d", 4.0)
    
    # Build diamond graph
    add_ab = AddRetargeter(name="add_ab")
    add_ab.connect([input_a.output(), input_b.output()])
    mult_1 = MultiplyRetargeter(name="mult_1")
    mult_1.connect([add_ab.output(0), input_c.output()])
    mult_2 = MultiplyRetargeter(name="mult_2")
    mult_2.connect([add_ab.output(0), input_d.output()])
    add_final = AddRetargeter(name="add_final")
    add_final.connect([mult_1.output(0), mult_2.output(0)])
    
    # Create executor
    executor = RetargeterExecutor([add_final])
    
    # Execute
    executor.execute()
    
    # Check intermediate results
    add_ab_result = executor.get_output(add_ab, 0)[0]
    mult_1_result = executor.get_output(mult_1, 0)[0]
    mult_2_result = executor.get_output(mult_2, 0)[0]
    
    assert add_ab_result == 8.0
    assert mult_1_result == 16.0
    assert mult_2_result == 32.0
    
    # Check final result
    final_result = executor.get_output(add_final, 0)[0]
    assert final_result == 48.0


def test_multiple_output_nodes():
    """Test executor with multiple output nodes."""
    # Create inputs
    input_a = FloatInputNode("a", 10.0)
    input_b = FloatInputNode("b", 5.0)
    input_c = FloatInputNode("c", 2.0)
    
    # Build two independent branches
    add = AddRetargeter(name="add")
    add.connect([input_a.output(), input_b.output()])
    multiply = MultiplyRetargeter(name="multiply")
    multiply.connect([input_b.output(), input_c.output()])
    
    # Create executor with both outputs
    executor = RetargeterExecutor([add, multiply])
    
    # Execute
    executor.execute()
    
    # Check results
    add_result = executor.get_output(add, 0)[0]
    multiply_result = executor.get_output(multiply, 0)[0]
    
    assert add_result == 15.0
    assert multiply_result == 10.0


def test_input_update():
    """Test that updating input values and re-executing produces new results."""
    # Create inputs
    input_a = FloatInputNode("a", 5.0)
    input_b = FloatInputNode("b", 3.0)
    
    # Build graph
    add = AddRetargeter()
    add.connect([input_a.output(), input_b.output()])
    
    # Create executor
    executor = RetargeterExecutor([add])
    
    # Execute first time
    executor.execute()
    result1 = executor.get_output(add, 0)[0]
    assert result1 == 8.0
    
    # Update inputs
    input_a.value = 10.0
    input_b.value = 20.0
    
    # Execute again
    executor.execute()
    result2 = executor.get_output(add, 0)[0]
    assert result2 == 30.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

