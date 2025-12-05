# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for basic retargeting module functionality with scalar computations.
"""

import pytest
from typing import Dict
from .. import (
    BaseRetargeter,
    RetargeterIO,
    TensorGroupType,
    TensorGroup,
    FloatType,
    IntType,
    BoolType,
    OutputLayer,
)


# ============================================================================
# Helper Modules for Testing
# ============================================================================

class ConstantSource(BaseRetargeter):
    """A source module that outputs constant values."""
    
    def __init__(self, name: str, x: float = 0.0, y: float = 0.0):
        self.x = x
        self.y = y
        super().__init__(name)
    
    def input_spec(self) -> RetargeterIO:
        return {}  # No inputs - this is a source
    
    def output_spec(self) -> RetargeterIO:
        return {
            "x": TensorGroupType("x_output", [FloatType("x")]),
            "y": TensorGroupType("y_output", [FloatType("y")]),
        }
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        outputs["x"][0] = self.x
        outputs["y"][0] = self.y


class ScaleAndOffset(BaseRetargeter):
    """Module that scales and offsets two float values."""
    
    def __init__(self, name: str):
        super().__init__(name)
    
    def input_spec(self) -> RetargeterIO:
        return {
            "x": TensorGroupType("x_input", [FloatType("x")]),
            "y": TensorGroupType("y_input", [FloatType("y")]),
            "scale": TensorGroupType("scale_input", [FloatType("scale")]),
            "offset": TensorGroupType("offset_input", [FloatType("offset")]),
        }
    
    def output_spec(self) -> RetargeterIO:
        return {
            "result": TensorGroupType("result_output", [
                FloatType("scaled_x"),
                FloatType("scaled_y"),
                FloatType("sum"),
            ])
        }
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        x = inputs["x"][0]
        y = inputs["y"][0]
        scale = inputs["scale"][0]
        offset = inputs["offset"][0]
        
        scaled_x = x * scale + offset
        scaled_y = y * scale + offset
        
        outputs["result"][0] = scaled_x
        outputs["result"][1] = scaled_y
        outputs["result"][2] = scaled_x + scaled_y


class Adder(BaseRetargeter):
    """Module that adds two float values."""
    
    def __init__(self, name: str):
        super().__init__(name)
    
    def input_spec(self) -> RetargeterIO:
        return {
            "a": TensorGroupType("a_input", [FloatType("a")]),
            "b": TensorGroupType("b_input", [FloatType("b")]),
        }
    
    def output_spec(self) -> RetargeterIO:
        return {
            "sum": TensorGroupType("sum_output", [FloatType("sum")])
        }
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        a = inputs["a"][0]
        b = inputs["b"][0]
        outputs["sum"][0] = a + b


class Doubler(BaseRetargeter):
    """Module that doubles a float value."""
    
    def __init__(self, name: str):
        super().__init__(name)
    
    def input_spec(self) -> RetargeterIO:
        return {
            "value": TensorGroupType("value_input", [FloatType("value")])
        }
    
    def output_spec(self) -> RetargeterIO:
        return {
            "result": TensorGroupType("result_output", [FloatType("doubled")])
        }
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        value = inputs["value"][0]
        outputs["result"][0] = value * 2.0


class Incrementer(BaseRetargeter):
    """Module that increments a float value by 1."""
    
    def __init__(self, name: str):
        super().__init__(name)
    
    def input_spec(self) -> RetargeterIO:
        return {
            "value": TensorGroupType("value_input", [FloatType("value")])
        }
    
    def output_spec(self) -> RetargeterIO:
        return {
            "result": TensorGroupType("result_output", [FloatType("incremented")])
        }
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        value = inputs["value"][0]
        outputs["result"][0] = value + 1.0


# ============================================================================
# Tests
# ============================================================================

def test_simple_source_module():
    """Test a simple source module with no inputs."""
    source = ConstantSource("source", 5.0, 10.0)
    
    outputs = source()
    
    assert outputs["x"][0] == 5.0
    assert outputs["y"][0] == 10.0


def test_simple_connection():
    """Test connecting a single processor to a source."""
    values = ConstantSource("values", 10.0, 20.0)
    params = ConstantSource("params", 2.0, 5.0)
    processor = ScaleAndOffset("processor")
    
    # Connect processor to sources
    pipeline = processor.connect({
        "x": values.output("x"),
        "y": values.output("y"),
        "scale": params.output("x"),
        "offset": params.output("y")
    })
    
    # Execute - outputs are flat now (no nesting)
    outputs = pipeline()
    
    # scaled_x = 10 * 2 + 5 = 25
    # scaled_y = 20 * 2 + 5 = 45
    # sum = 25 + 45 = 70
    assert outputs["result"][0] == 25.0
    assert outputs["result"][1] == 45.0
    assert outputs["result"][2] == 70.0


def test_multi_input_connection():
    """Test connecting multiple inputs from different sources."""
    source_a = ConstantSource("source_a", 3.0, 7.0)
    source_b = ConstantSource("source_b", 2.0, 5.0)
    adder = Adder("adder")
    
    pipeline = adder.connect({
        "a": source_a.output("x"),
        "b": source_b.output("y")
    })
    
    outputs = pipeline()
    assert outputs["sum"][0] == 8.0  # 3 + 5


def test_chained_connections():
    """Test chaining multiple modules together."""
    # Create a source that outputs a single value
    class SingleValueSource(BaseRetargeter):
        def __init__(self, name: str, value: float):
            self.value = value
            super().__init__(name)
        
        def input_spec(self) -> RetargeterIO:
            return {}
        
        def output_spec(self) -> RetargeterIO:
            return {"value": TensorGroupType("output", [FloatType("value")])}
        
        def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
            outputs["value"][0] = self.value
    
    source = SingleValueSource("source", 5.0)
    doubler = Doubler("doubler")
    incrementer = Incrementer("incrementer")
    
    # Chain: source (5) -> doubler (10) -> incrementer (11)
    step1 = doubler.connect({"value": source.output("value")})
    step2 = incrementer.connect({"value": step1.output("result")})
    
    outputs = step2()
    assert outputs["result"][0] == 11.0  # (5 * 2) + 1


def test_zero_scale():
    """Test ScaleAndOffset with zero scale."""
    values = ConstantSource("values", 10.0, 20.0)
    params = ConstantSource("params", 0.0, 5.0)  # scale=0, offset=5
    processor = ScaleAndOffset("processor")
    
    pipeline = processor.connect({
        "x": values.output("x"),
        "y": values.output("y"),
        "scale": params.output("x"),
        "offset": params.output("y")
    })
    
    outputs = pipeline()
    
    # scaled_x = 10 * 0 + 5 = 5
    # scaled_y = 20 * 0 + 5 = 5
    # sum = 5 + 5 = 10
    assert outputs["result"][0] == 5.0
    assert outputs["result"][1] == 5.0
    assert outputs["result"][2] == 10.0


def test_negative_values():
    """Test with negative values."""
    values = ConstantSource("values", -5.0, 10.0)
    params = ConstantSource("params", 3.0, -2.0)  # scale=3, offset=-2
    processor = ScaleAndOffset("processor")
    
    pipeline = processor.connect({
        "x": values.output("x"),
        "y": values.output("y"),
        "scale": params.output("x"),
        "offset": params.output("y")
    })
    
    outputs = pipeline()
    
    # scaled_x = -5 * 3 + (-2) = -17
    # scaled_y = 10 * 3 + (-2) = 28
    # sum = -17 + 28 = 11
    assert outputs["result"][0] == -17.0
    assert outputs["result"][1] == 28.0
    assert outputs["result"][2] == 11.0


def test_shared_source_executes_once():
    """Test that a shared source only executes once (basic sanity check)."""
    # Create a counting source to verify single execution
    class CountingSource(BaseRetargeter):
        def __init__(self, name: str):
            self.call_count = 0
            super().__init__(name)
        
        def input_spec(self) -> RetargeterIO:
            return {}
        
        def output_spec(self) -> RetargeterIO:
            return {"value": TensorGroupType("output", [FloatType("value")])}
        
        def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
            self.call_count += 1
            outputs["value"][0] = 42.0
    
    source = CountingSource("source")
    adder = Adder("adder")
    
    # Use the same source for both inputs
    pipeline = adder.connect({
        "a": source.output("value"),
        "b": source.output("value")
    })
    
    outputs = pipeline()
    
    # Source should execute once (due to caching)
    assert source.call_count == 1
    assert outputs["sum"][0] == 84.0  # 42 + 42


# ============================================================================
# OutputLayer Tests
# ============================================================================

def test_output_layer_basic():
    """Test basic OutputLayer functionality with custom names."""
    left_source = ConstantSource("left", 10.0, 20.0)
    right_source = ConstantSource("right", 30.0, 40.0)
    
    # Gather outputs with custom names
    output_layer = OutputLayer({
        "left_x": left_source.output("x"),
        "left_y": left_source.output("y"),
        "right_x": right_source.output("x"),
        "right_y": right_source.output("y")
    }, name="output_layer")
    
    # Execute
    result = output_layer()
    
    # Verify flat output structure with custom names
    assert "left_x" in result
    assert "left_y" in result
    assert "right_x" in result
    assert "right_y" in result
    
    assert result["left_x"][0] == 10.0
    assert result["left_y"][0] == 20.0
    assert result["right_x"][0] == 30.0
    assert result["right_y"][0] == 40.0


def test_output_layer_with_connected_modules():
    """Test OutputLayer gathering outputs from connected modules."""
    source = ConstantSource("source", 5.0, 10.0)
    doubler = Doubler("doubler")
    incrementer = Incrementer("incrementer")
    
    # Create connected modules
    doubled = doubler.connect({"value": source.output("x")})
    incremented = incrementer.connect({"value": source.output("y")})
    
    # Gather their outputs
    output_layer = OutputLayer({
        "doubled_value": doubled.output("result"),
        "incremented_value": incremented.output("result")
    }, name="gatherer")
    
    result = output_layer()
    
    assert result["doubled_value"][0] == 10.0  # 5 * 2
    assert result["incremented_value"][0] == 11.0  # 10 + 1


def test_output_layer_execution_caching():
    """Test that OutputLayer caches shared source execution."""
    class CountingSource(BaseRetargeter):
        def __init__(self, name: str, value: float):
            self.value = value
            self.call_count = 0
            super().__init__(name)
        
        def input_spec(self) -> RetargeterIO:
            return {}
        
        def output_spec(self) -> RetargeterIO:
            return {"value": TensorGroupType("output", [FloatType("value")])}
        
        def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
            self.call_count += 1
            outputs["value"][0] = self.value
    
    source = CountingSource("source", 42.0)
    doubler = Doubler("doubler")
    incrementer = Incrementer("incrementer")
    
    # Both use the same source
    doubled = doubler.connect({"value": source.output("value")})
    incremented = incrementer.connect({"value": source.output("value")})
    
    # Gather outputs
    output_layer = OutputLayer({
        "doubled": doubled.output("result"),
        "incremented": incremented.output("result")
    }, name="output_layer")
    
    result = output_layer()
    
    # Source should execute only once despite being used by two downstream modules
    assert source.call_count == 1
    assert result["doubled"][0] == 84.0  # 42 * 2
    assert result["incremented"][0] == 43.0  # 42 + 1


def test_output_layer_can_be_connected():
    """Test that OutputLayer can be used as a source for other modules."""
    source_a = ConstantSource("source_a", 10.0, 20.0)
    source_b = ConstantSource("source_b", 5.0, 3.0)
    
    # Create output layer
    gathered = OutputLayer({
        "val_a": source_a.output("x"),
        "val_b": source_b.output("x")
    }, name="gathered")
    
    # Connect OutputLayer to an Adder
    adder = Adder("adder")
    pipeline = adder.connect({
        "a": gathered.output("val_a"),
        "b": gathered.output("val_b")
    })
    
    result = pipeline()
    
    assert result["sum"][0] == 15.0  # 10 + 5


def test_output_layer_get_output_type():
    """Test that OutputLayer correctly exposes output types."""
    source = ConstantSource("source", 1.0, 2.0)
    
    output_layer = OutputLayer({
        "custom_x": source.output("x"),
        "custom_y": source.output("y")
    }, name="output_layer")
    
    # Should be able to get output types
    x_type = output_layer.get_output_type("custom_x")
    y_type = output_layer.get_output_type("custom_y")
    
    assert x_type is not None
    assert y_type is not None
    
    # Should raise for invalid output name
    with pytest.raises(ValueError):
        output_layer.get_output_type("nonexistent")


def test_output_layer_empty_inputs():
    """Test OutputLayer with source modules (no inputs needed)."""
    source1 = ConstantSource("s1", 100.0, 200.0)
    source2 = ConstantSource("s2", 300.0, 400.0)
    
    output_layer = OutputLayer({
        "first": source1.output("x"),
        "second": source2.output("y")
    }, name="output_layer")
    
    # Should work with no inputs
    result = output_layer()
    
    assert result["first"][0] == 100.0
    assert result["second"][0] == 400.0


def test_output_layer_complex_pipeline():
    """Test OutputLayer in a complex pipeline with multiple stages."""
    # Stage 1: Sources
    source1 = ConstantSource("source1", 10.0, 20.0)
    source2 = ConstantSource("source2", 2.0, 3.0)
    
    # Stage 2: Processing
    doubler1 = Doubler("doubler1")
    doubler2 = Doubler("doubler2")
    doubled1 = doubler1.connect({"value": source1.output("x")})
    doubled2 = doubler2.connect({"value": source2.output("x")})
    
    # Stage 3: Combine with Adder
    adder = Adder("adder")
    summed = adder.connect({
        "a": doubled1.output("result"),
        "b": doubled2.output("result")
    })
    
    # Stage 4: Gather everything with OutputLayer
    output_layer = OutputLayer({
        "original_x": source1.output("x"),
        "doubled_1": doubled1.output("result"),
        "doubled_2": doubled2.output("result"),
        "final_sum": summed.output("sum")
    }, name="final_output")
    
    result = output_layer()
    
    assert result["original_x"][0] == 10.0
    assert result["doubled_1"][0] == 20.0  # 10 * 2
    assert result["doubled_2"][0] == 4.0   # 2 * 2
    assert result["final_sum"][0] == 24.0  # 20 + 4


def test_output_layer_invalid_initialization():
    """Test that OutputLayer validates initialization parameters."""
    # Empty mapping should raise
    with pytest.raises(ValueError):
        OutputLayer({}, name="empty")
    
    # Non-OutputSelector should raise
    with pytest.raises(TypeError):
        OutputLayer({"bad": "not_an_output_selector"}, name="bad")


# ============================================================================
# OutputLayer as Input Examples
# ============================================================================

def test_example_output_layer_as_intermediate_hub():
    """
    Example: Using OutputLayer as an intermediate hub that gathers outputs
    from multiple sources and feeds them to multiple downstream modules.
    """
    # Create multiple sources
    sensor_a = ConstantSource("sensor_a", 10.0, 20.0)
    sensor_b = ConstantSource("sensor_b", 5.0, 15.0)
    sensor_c = ConstantSource("sensor_c", 3.0, 7.0)
    
    # Gather all sensor readings with custom names
    sensor_hub = OutputLayer({
        "left_sensor": sensor_a.output("x"),
        "right_sensor": sensor_b.output("x"),
        "center_sensor": sensor_c.output("x")
    }, name="sensor_hub")
    
    # Use the hub as input to multiple downstream modules
    left_right_sum = Adder("left_right_sum")
    all_sensors_sum = Adder("all_sensors_sum")
    
    # Connect different combinations from the hub
    lr_pipeline = left_right_sum.connect({
        "a": sensor_hub.output("left_sensor"),
        "b": sensor_hub.output("right_sensor")
    })
    
    # Can also create a nested adder
    temp_adder = Adder("temp_adder")
    temp_sum = temp_adder.connect({
        "a": sensor_hub.output("center_sensor"),
        "b": lr_pipeline.output("sum")
    })
    
    result = temp_sum()
    
    # Verify: (10 + 5) + 3 = 18
    assert result["sum"][0] == 18.0


def test_example_output_layer_with_processing_chain():
    """
    Example: OutputLayer gathering outputs from a processing chain,
    then feeding into downstream analytics.
    """
    # Create a processing pipeline
    raw_data = ConstantSource("raw_data", 10.0, 20.0)
    
    doubler1 = Doubler("doubler1")
    doubler2 = Doubler("doubler2")
    
    first_double = doubler1.connect({"value": raw_data.output("x")})
    second_double = doubler2.connect({"value": first_double.output("result")})
    
    # Gather both raw and processed data
    data_layer = OutputLayer({
        "raw": raw_data.output("x"),
        "once_doubled": first_double.output("result"),
        "twice_doubled": second_double.output("result")
    }, name="data_layer")
    
    # Use the layer for downstream analysis
    # Compare raw vs processed
    comparator = Adder("comparator")
    result = comparator.connect({
        "a": data_layer.output("raw"),
        "b": data_layer.output("twice_doubled")
    })
    
    output = result()
    
    # raw=10, once_doubled=20, twice_doubled=40
    # sum = 10 + 40 = 50
    assert output["sum"][0] == 50.0


def test_example_output_layer_multi_stage_pipeline():
    """
    Example: Multi-stage pipeline where OutputLayer serves as a stage boundary,
    collecting stage outputs before passing to next stage.
    """
    # Stage 1: Data sources
    input_a = ConstantSource("input_a", 5.0, 10.0)
    input_b = ConstantSource("input_b", 3.0, 6.0)
    
    # Stage 2: Processing
    doubler_a = Doubler("double_a")
    doubler_b = Doubler("double_b")
    
    doubled_a = doubler_a.connect({"value": input_a.output("x")})
    doubled_b = doubler_b.connect({"value": input_b.output("x")})
    
    # OutputLayer marks stage boundary - gather all stage 2 outputs
    stage2_outputs = OutputLayer({
        "processed_a": doubled_a.output("result"),
        "processed_b": doubled_b.output("result")
    }, name="stage2_outputs")
    
    # Stage 3: Aggregation - uses stage 2 outputs
    aggregator = Adder("final_aggregator")
    final = aggregator.connect({
        "a": stage2_outputs.output("processed_a"),
        "b": stage2_outputs.output("processed_b")
    })
    
    result = final()
    
    # input_a=5 -> doubled=10
    # input_b=3 -> doubled=6
    # sum = 10 + 6 = 16
    assert result["sum"][0] == 16.0


def test_connect_twice_on_same_module():
    """
    Test what happens when calling connect() twice on the same base module.
    
    This demonstrates:
    - Each connect() creates a NEW ConnectedModule instance
    - Both instances reference the same target BaseRetargeter
    - Name collision occurs (both get "_connected" suffix)
    - Both work independently with different input connections
    """
    # Create multiple sources
    source_a = ConstantSource("source_a", 10.0, 20.0)
    source_b = ConstantSource("source_b", 5.0, 15.0)
    
    # Create a single processor
    processor = Doubler("processor")
    
    # Connect it twice with different sources
    connected1 = processor.connect({"value": source_a.output("x")})
    connected2 = processor.connect({"value": source_b.output("x")})
    
    # Both create separate ConnectedModule instances
    assert connected1 is not connected2, "Should create different ConnectedModule instances"
    
    # But they reference the same target module
    assert connected1._target_module is connected2._target_module, "Should share same target module"
    assert connected1._target_module is processor, "Target should be the original processor"
    
    # Name collision - both have the same name!
    assert connected1.name == "processor_connected"
    assert connected2.name == "processor_connected"
    assert connected1.name == connected2.name, "Name collision occurs"
    
    # Despite sharing the target module, they work independently
    result1 = connected1()
    result2 = connected2()
    
    # Results are different because they're connected to different sources
    assert result1["result"][0] == 20.0  # source_a.x=10 -> doubled=20
    assert result2["result"][0] == 10.0  # source_b.x=5 -> doubled=10


def test_connect_twice_different_connection_patterns():
    """
    Test connecting the same module with completely different input patterns.
    
    This shows you can create multiple connection variants of the same module,
    useful for reusing logic with different data flows.
    """
    # Create sources
    left_source = ConstantSource("left", 100.0, 200.0)
    right_source = ConstantSource("right", 5.0, 10.0)
    
    # Create an adder that we'll connect in different ways
    adder = Adder("adder")
    
    # First connection: add left.x + left.y
    left_self_sum = adder.connect({
        "a": left_source.output("x"),
        "b": left_source.output("y")
    })
    
    # Second connection: add left.x + right.x
    cross_sum = adder.connect({
        "a": left_source.output("x"),
        "b": right_source.output("x")
    })
    
    # Third connection: add right.x + right.y
    right_self_sum = adder.connect({
        "a": right_source.output("x"),
        "b": right_source.output("y")
    })
    
    # All three are different instances
    assert left_self_sum is not cross_sum
    assert cross_sum is not right_self_sum
    assert left_self_sum is not right_self_sum
    
    # All share the same target
    assert left_self_sum._target_module is adder
    assert cross_sum._target_module is adder
    assert right_self_sum._target_module is adder
    
    # All have the same name (collision)
    assert left_self_sum.name == "adder_connected"
    assert cross_sum.name == "adder_connected"
    assert right_self_sum.name == "adder_connected"
    
    # But produce different results based on their connections
    result1 = left_self_sum()
    result2 = cross_sum()
    result3 = right_self_sum()
    
    assert result1["sum"][0] == 300.0  # 100 + 200
    assert result2["sum"][0] == 105.0  # 100 + 5
    assert result3["sum"][0] == 15.0   # 5 + 10


def test_connect_twice_shared_execution_context():
    """
    Test that when the same connected module is used in a pipeline,
    execution context handles it correctly even with duplicate connections.
    """
    source = ConstantSource("source", 42.0, 84.0)
    
    doubler = Doubler("doubler")
    
    # Create two connections of the same doubler
    doubled_x = doubler.connect({"value": source.output("x")})
    doubled_y = doubler.connect({"value": source.output("y")})
    
    # Use both in an OutputLayer
    output_layer = OutputLayer({
        "doubled_x": doubled_x.output("result"),
        "doubled_y": doubled_y.output("result")
    }, name="outputs")
    
    result = output_layer()
    
    # Both execute correctly
    assert result["doubled_x"][0] == 84.0   # 42 * 2
    assert result["doubled_y"][0] == 168.0  # 84 * 2


def test_connect_twice_combine_outputs_downstream():
    """
    Test combining outputs from two connections of the same module into a downstream node.
    
    This is the critical test: Can we connect the same module twice with different inputs,
    then feed both outputs into a single downstream module?
    
    Pattern:
        source_a    source_b
            |           |
        doubler     doubler  (same module, connected twice)
            |           |
             \         /
              \       /
                adder (downstream module combines both outputs)
    """
    # Create two independent sources
    source_a = ConstantSource("source_a", 10.0, 20.0)
    source_b = ConstantSource("source_b", 5.0, 15.0)
    
    # Single doubler module
    doubler = Doubler("doubler")
    
    # Connect it twice with different sources
    doubled_a = doubler.connect({"value": source_a.output("x")})  # 10 * 2 = 20
    doubled_b = doubler.connect({"value": source_b.output("x")})  # 5 * 2 = 10
    
    # Now combine BOTH outputs in a downstream adder
    adder = Adder("adder")
    combined = adder.connect({
        "a": doubled_a.output("result"),
        "b": doubled_b.output("result")
    })
    
    # Execute the pipeline
    result = combined()
    
    # Should get: (10 * 2) + (5 * 2) = 20 + 10 = 30
    assert result["sum"][0] == 30.0
    
    print(f"✓ Combined result: {result['sum'][0]}")


def test_connect_twice_complex_diamond_with_reuse():
    """
    Test a complex pattern: diamond with module reuse.
    
    Pattern:
               source
              /      \
             /        \
        doubler    doubler  (same module connected twice)
             \        /
              \      /
               adder
    
    Both paths use the same doubler module but connected differently.
    The downstream adder should receive correct values from both.
    """
    source = ConstantSource("source", 7.0, 3.0)
    
    # Same doubler, connected twice to different outputs of same source
    doubler = Doubler("doubler")
    
    path_a = doubler.connect({"value": source.output("x")})  # 7 * 2 = 14
    path_b = doubler.connect({"value": source.output("y")})  # 3 * 2 = 6
    
    # Merge both paths
    adder = Adder("merger")
    final = adder.connect({
        "a": path_a.output("result"),
        "b": path_b.output("result")
    })
    
    result = final()
    
    # (7 * 2) + (3 * 2) = 14 + 6 = 20
    assert result["sum"][0] == 20.0


def test_connect_twice_multi_level_reuse():
    """
    Test multiple levels of reuse: connect twice, process each, then combine.
    
    Pattern:
        s1      s2
        |       |
      double  double  (same doubler)
        |       |
      incr    incr    (same incrementer)  
        |       |
         \     /
          adder
    """
    source1 = ConstantSource("s1", 10.0, 0.0)
    source2 = ConstantSource("s2", 20.0, 0.0)
    
    # Reuse doubler twice
    doubler = Doubler("doubler")
    doubled1 = doubler.connect({"value": source1.output("x")})  # 10 * 2 = 20
    doubled2 = doubler.connect({"value": source2.output("x")})  # 20 * 2 = 40
    
    # Reuse incrementer twice
    incrementer = Incrementer("incrementer")
    inc1 = incrementer.connect({"value": doubled1.output("result")})  # 20 + 1 = 21
    inc2 = incrementer.connect({"value": doubled2.output("result")})  # 40 + 1 = 41
    
    # Combine final results
    adder = Adder("final_adder")
    final = adder.connect({
        "a": inc1.output("result"),
        "b": inc2.output("result")
    })
    
    result = final()
    
    # 21 + 41 = 62
    assert result["sum"][0] == 62.0


def test_connect_twice_with_output_layer_then_downstream():
    """
    Test using OutputLayer to gather outputs from duplicate connections,
    then feeding into downstream processing.
    
    Pattern:
        s1      s2
        |       |
      double  double  (same doubler)
        |       |
         \     /
       OutputLayer
        |       |
         \     /
          adder
    """
    source1 = ConstantSource("s1", 100.0, 0.0)
    source2 = ConstantSource("s2", 50.0, 0.0)
    
    # Connect doubler twice
    doubler = Doubler("doubler")
    doubled1 = doubler.connect({"value": source1.output("x")})  # 100 * 2 = 200
    doubled2 = doubler.connect({"value": source2.output("x")})  # 50 * 2 = 100
    
    # Gather with OutputLayer
    gathered = OutputLayer({
        "result1": doubled1.output("result"),
        "result2": doubled2.output("result")
    }, name="gathered")
    
    # Use gathered outputs downstream
    adder = Adder("downstream")
    final = adder.connect({
        "a": gathered.output("result1"),
        "b": gathered.output("result2")
    })
    
    result = final()
    
    # 200 + 100 = 300
    assert result["sum"][0] == 300.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
