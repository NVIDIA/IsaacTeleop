# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for execution caching in complex graph structures.
"""

import pytest
from typing import Dict
from .. import (
    BaseRetargeter,
    RetargeterIO,
    TensorGroupType,
    TensorGroup,
    FloatType,
    OutputLayer,
)


class CountingModule(BaseRetargeter):
    """A module that counts how many times it's been executed."""
    
    execution_counts = {}  # Class variable to track all instances
    
    def __init__(self, name: str):
        super().__init__(name)
        CountingModule.execution_counts[name] = 0
    
    def input_spec(self) -> RetargeterIO:
        return {"input": TensorGroupType("input", [FloatType("value")])}
    
    def output_spec(self) -> RetargeterIO:
        return {"output": TensorGroupType("output", [FloatType("value")])}
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        CountingModule.execution_counts[self.name] += 1
        outputs["output"][0] = inputs["input"][0] + 1.0
    
    @classmethod
    def reset_counts(cls):
        """Reset all execution counts."""
        cls.execution_counts.clear()


class SourceModule(BaseRetargeter):
    """Simple source that outputs a constant."""
    
    def __init__(self, name: str, value: float = 0.0):
        self.value = value
        self.execution_count = 0
        super().__init__(name)
    
    def input_spec(self) -> RetargeterIO:
        return {}
    
    def output_spec(self) -> RetargeterIO:
        return {"output": TensorGroupType("output", [FloatType("value")])}
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        self.execution_count += 1
        outputs["output"][0] = self.value


class SumModule(BaseRetargeter):
    """Module that sums two inputs."""
    
    def __init__(self, name: str):
        super().__init__(name)
        self.execution_count = 0
    
    def input_spec(self) -> RetargeterIO:
        return {
            "input1": TensorGroupType("input1", [FloatType("value")]),
            "input2": TensorGroupType("input2", [FloatType("value")]),
        }
    
    def output_spec(self) -> RetargeterIO:
        return {"output": TensorGroupType("output", [FloatType("sum")])}
    
    def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
        self.execution_count += 1
        outputs["output"][0] = inputs["input1"][0] + inputs["input2"][0]


def test_diamond_pattern_caching():
    r"""
    Test that in a diamond pattern, the source executes only once.
    
    Pattern:
        source
        /    \
       B      C
        \    /
          D
    """
    CountingModule.reset_counts()
    
    source = SourceModule("source", 5.0)
    module_b = CountingModule("B")
    module_c = CountingModule("C")
    module_d = SumModule("D")
    
    # Build diamond
    connected_b = module_b.connect({"input": source.output("output")})
    connected_c = module_c.connect({"input": source.output("output")})
    
    # D takes outputs from both B and C
    pipeline = module_d.connect({
        "input1": connected_b.output("output"),
        "input2": connected_c.output("output")
    })
    
    # Execute
    outputs = pipeline()
    
    # Verify execution counts
    assert source.execution_count == 1, "Source should execute once"
    assert CountingModule.execution_counts["B"] == 1, "B should execute once"
    assert CountingModule.execution_counts["C"] == 1, "C should execute once"
    assert module_d.execution_count == 1, "D should execute once"

    # Verify output: source(5) -> B(6), C(6) -> D(12)
    assert outputs["output"][0] == 12.0


def test_multiple_shared_sources():
    r"""
    Test caching with multiple sources that are shared.
    
    Pattern:
        A    B
         \  /
          D -> E
    """
    CountingModule.reset_counts()
    
    source_a = SourceModule("A", 10.0)
    source_b = SourceModule("B", 20.0)
    module_d = SumModule("D")
    module_e = CountingModule("E")
    
    # D takes A and B
    connected_d = module_d.connect({
        "input1": source_a.output("output"),
        "input2": source_b.output("output")
    })
    
    # E takes D
    pipeline = module_e.connect({
        "input": connected_d.output("output")
    })
    
    # Execute
    outputs = pipeline()
    
    # A and B should each execute only once
    assert source_a.execution_count == 1, "A should execute once"
    assert source_b.execution_count == 1, "B should execute once"
    assert module_d.execution_count == 1, "D should execute once"
    assert CountingModule.execution_counts["E"] == 1, "E should execute once"

    # Verify: A(10) + B(20) = D(30) -> E(31)
    assert outputs["output"][0] == 31.0


def test_linear_chain_no_redundancy():
    """Test that a simple linear chain doesn't have redundant executions."""
    CountingModule.reset_counts()
    
    source = SourceModule("source", 1.0)
    mod1 = CountingModule("mod1")
    mod2 = CountingModule("mod2")
    mod3 = CountingModule("mod3")
    
    # Build chain: source -> mod1 -> mod2 -> mod3
    chain1 = mod1.connect({"input": source.output("output")})
    chain2 = mod2.connect({"input": chain1.output("output")})
    pipeline = mod3.connect({"input": chain2.output("output")})
    
    outputs = pipeline()
    
    # Each should execute exactly once
    assert source.execution_count == 1
    assert CountingModule.execution_counts["mod1"] == 1
    assert CountingModule.execution_counts["mod2"] == 1
    assert CountingModule.execution_counts["mod3"] == 1

    # Verify output: 1 -> 2 -> 3 -> 4
    assert outputs["output"][0] == 4.0


def test_multiple_calls_resets_cache():
    """Test that multiple calls to the same pipeline work correctly."""
    CountingModule.reset_counts()
    
    source = SourceModule("source", 5.0)
    module_b = CountingModule("B")
    module_c = CountingModule("C")
    module_d = SumModule("D")
    
    # Build diamond
    connected_b = module_b.connect({"input": source.output("output")})
    connected_c = module_c.connect({"input": source.output("output")})
    pipeline = module_d.connect({
        "input1": connected_b.output("output"),
        "input2": connected_c.output("output")
    })
    
    # First execution
    outputs1 = pipeline()
    first_source_count = source.execution_count
    
    # Second execution - cache should be reset
    outputs2 = pipeline()
    
    # Each call should execute the source once
    assert source.execution_count == 2, "Source should execute twice (once per call)"
    assert outputs1["output"][0] == outputs2["output"][0]


def test_wide_fan_out():
    r"""
    Test caching with wide fan-out pattern.
    
    Pattern:
           A
        /  |  \
       B   C   D
        \  |  /
           E
    """
    CountingModule.reset_counts()
    
    source = SourceModule("A", 10.0)
    module_b = CountingModule("B")
    module_c = CountingModule("C")
    module_d = CountingModule("D")
    
    # Special sum module that takes 3 inputs
    class TripleSum(BaseRetargeter):
        def __init__(self, name: str):
            self.execution_count = 0
            super().__init__(name)
        
        def input_spec(self) -> RetargeterIO:
            return {
                "input1": TensorGroupType("input1", [FloatType("value")]),
                "input2": TensorGroupType("input2", [FloatType("value")]),
                "input3": TensorGroupType("input3", [FloatType("value")]),
            }
        
        def output_spec(self) -> RetargeterIO:
            return {"output": TensorGroupType("output", [FloatType("sum")])}
        
        def compute(self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]) -> None:
            self.execution_count += 1
            outputs["output"][0] = inputs["input1"][0] + inputs["input2"][0] + inputs["input3"][0]
    
    module_e = TripleSum("E")
    
    # Connect B, C, D to source
    connected_b = module_b.connect({"input": source.output("output")})
    connected_c = module_c.connect({"input": source.output("output")})
    connected_d = module_d.connect({"input": source.output("output")})
    
    # E takes all three
    pipeline = module_e.connect({
        "input1": connected_b.output("output"),
        "input2": connected_c.output("output"),
        "input3": connected_d.output("output")
    })
    
    outputs = pipeline()
    
    # Source should execute only once despite feeding 3 modules
    assert source.execution_count == 1, "Source A should execute once"
    assert CountingModule.execution_counts["B"] == 1
    assert CountingModule.execution_counts["C"] == 1
    assert CountingModule.execution_counts["D"] == 1
    assert module_e.execution_count == 1

    # Verify: 10 -> B(11), C(11), D(11) -> E(33)
    assert outputs["output"][0] == 33.0


# ============================================================================
# OutputLayer Execution Caching Tests
# ============================================================================

def test_output_layer_diamond_caching():
    r"""
    Test that OutputLayer properly caches shared sources in diamond pattern.
    
    Pattern:
        source
        /    \
       B      C
        \    /
      OutputLayer
    """
    CountingModule.reset_counts()
    
    source = SourceModule("source", 5.0)
    module_b = CountingModule("B")
    module_c = CountingModule("C")
    
    # Build diamond
    connected_b = module_b.connect({"input": source.output("output")})
    connected_c = module_c.connect({"input": source.output("output")})
    
    # Gather outputs with OutputLayer
    output_layer = OutputLayer({
        "result_b": connected_b.output("output"),
        "result_c": connected_c.output("output")
    }, name="output_layer")
    
    # Execute
    result = output_layer()
    
    # Source should execute only once despite being used by both B and C
    assert source.execution_count == 1, "Source should execute once"
    assert CountingModule.execution_counts["B"] == 1, "B should execute once"
    assert CountingModule.execution_counts["C"] == 1, "C should execute once"
    
    # Verify outputs: source(5) -> B(6), C(6)
    assert result["result_b"][0] == 6.0
    assert result["result_c"][0] == 6.0


def test_output_layer_multiple_sources_caching():
    """Test OutputLayer caching with multiple independent sources."""
    CountingModule.reset_counts()
    
    source_a = SourceModule("A", 10.0)
    source_b = SourceModule("B", 20.0)
    source_c = SourceModule("C", 30.0)
    
    module_d = CountingModule("D")
    module_e = CountingModule("E")
    
    # D and E share source_a
    connected_d = module_d.connect({"input": source_a.output("output")})
    connected_e = module_e.connect({"input": source_a.output("output")})
    
    # Gather all outputs
    output_layer = OutputLayer({
        "from_a_via_d": connected_d.output("output"),
        "from_a_via_e": connected_e.output("output"),
        "direct_b": source_b.output("output"),
        "direct_c": source_c.output("output")
    }, name="output_layer")
    
    result = output_layer()
    
    # Each source should execute only once
    assert source_a.execution_count == 1, "Source A should execute once (shared by D and E)"
    assert source_b.execution_count == 1, "Source B should execute once"
    assert source_c.execution_count == 1, "Source C should execute once"
    assert CountingModule.execution_counts["D"] == 1, "D should execute once"
    assert CountingModule.execution_counts["E"] == 1, "E should execute once"
    
    # Verify outputs
    assert result["from_a_via_d"][0] == 11.0  # 10 + 1
    assert result["from_a_via_e"][0] == 11.0  # 10 + 1
    assert result["direct_b"][0] == 20.0
    assert result["direct_c"][0] == 30.0


def test_output_layer_nested_connected_modules():
    r"""
    Test OutputLayer caching with nested ConnectedModules.
    
    Pattern:
           A
          / \
         B   C
         |   |
         D   E
          \ /
       OutputLayer
    """
    CountingModule.reset_counts()
    
    source = SourceModule("A", 100.0)
    module_b = CountingModule("B")
    module_c = CountingModule("C")
    module_d = CountingModule("D")
    module_e = CountingModule("E")
    
    # Build nested connections
    connected_b = module_b.connect({"input": source.output("output")})
    connected_c = module_c.connect({"input": source.output("output")})
    connected_d = module_d.connect({"input": connected_b.output("output")})
    connected_e = module_e.connect({"input": connected_c.output("output")})
    
    # Gather from nested levels
    output_layer = OutputLayer({
        "level_1_b": connected_b.output("output"),
        "level_1_c": connected_c.output("output"),
        "level_2_d": connected_d.output("output"),
        "level_2_e": connected_e.output("output")
    }, name="output_layer")
    
    result = output_layer()
    
    # Each module should execute exactly once
    assert source.execution_count == 1, "Source A should execute once"
    assert CountingModule.execution_counts["B"] == 1, "B should execute once"
    assert CountingModule.execution_counts["C"] == 1, "C should execute once"
    assert CountingModule.execution_counts["D"] == 1, "D should execute once"
    assert CountingModule.execution_counts["E"] == 1, "E should execute once"
    
    # Verify: A(100) -> B(101), C(101) -> D(102), E(102)
    assert result["level_1_b"][0] == 101.0
    assert result["level_1_c"][0] == 101.0
    assert result["level_2_d"][0] == 102.0
    assert result["level_2_e"][0] == 102.0


def test_output_layer_multiple_calls():
    """Test that OutputLayer resets cache between calls."""
    CountingModule.reset_counts()
    
    source = SourceModule("source", 5.0)
    module_a = CountingModule("A")
    module_b = CountingModule("B")
    
    connected_a = module_a.connect({"input": source.output("output")})
    connected_b = module_b.connect({"input": source.output("output")})
    
    output_layer = OutputLayer({
        "out_a": connected_a.output("output"),
        "out_b": connected_b.output("output")
    }, name="output_layer")
    
    # First call
    result1 = output_layer()
    
    # Second call - cache should be reset
    result2 = output_layer()
    
    # Each call should execute everything once
    assert source.execution_count == 2, "Source should execute twice (once per call)"
    assert CountingModule.execution_counts["A"] == 2, "A should execute twice"
    assert CountingModule.execution_counts["B"] == 2, "B should execute twice"
    
    # Results should be identical
    assert result1["out_a"][0] == result2["out_a"][0]
    assert result1["out_b"][0] == result2["out_b"][0]


def test_output_layer_wide_fan_out():
    r"""
    Test OutputLayer with very wide fan-out from single source.
    
    Pattern:
              A
        /  /  |  \  \
       B  C   D   E  F
       |  |   |   |  |
    OutputLayer (5 outputs)
    """
    CountingModule.reset_counts()
    
    source = SourceModule("A", 1.0)
    modules = [CountingModule(f"M{i}") for i in range(5)]
    
    # Connect all modules to same source
    connected = [m.connect({"input": source.output("output")}) for m in modules]
    
    # Gather all outputs
    output_layer = OutputLayer({
        f"out_{i}": conn.output("output") 
        for i, conn in enumerate(connected)
    }, name="output_layer")
    
    result = output_layer()
    
    # Source should execute only once
    assert source.execution_count == 1, "Source should execute once despite 5 consumers"
    
    # All modules should execute once
    for i in range(5):
        assert CountingModule.execution_counts[f"M{i}"] == 1, f"M{i} should execute once"
    
    # All outputs should be 2.0 (1.0 + 1.0)
    for i in range(5):
        assert result[f"out_{i}"][0] == 2.0


def test_output_layer_complex_dag():
    r"""
    Test OutputLayer with complex DAG pattern.
    
    Pattern:
           S1      S2
          / \      / \
         A   B    C   D
          \ /      \ /
           E        F
            \      /
          OutputLayer
    """
    CountingModule.reset_counts()
    
    source1 = SourceModule("S1", 10.0)
    source2 = SourceModule("S2", 20.0)
    
    module_a = CountingModule("A")
    module_b = CountingModule("B")
    module_c = CountingModule("C")
    module_d = CountingModule("D")
    module_e = SumModule("E")
    module_f = SumModule("F")
    
    # Build first diamond
    conn_a = module_a.connect({"input": source1.output("output")})
    conn_b = module_b.connect({"input": source1.output("output")})
    conn_e = module_e.connect({
        "input1": conn_a.output("output"),
        "input2": conn_b.output("output")
    })
    
    # Build second diamond
    conn_c = module_c.connect({"input": source2.output("output")})
    conn_d = module_d.connect({"input": source2.output("output")})
    conn_f = module_f.connect({
        "input1": conn_c.output("output"),
        "input2": conn_d.output("output")
    })
    
    # Gather outputs from all levels
    output_layer = OutputLayer({
        "s1_direct": source1.output("output"),
        "s2_direct": source2.output("output"),
        "e_result": conn_e.output("output"),
        "f_result": conn_f.output("output")
    }, name="output_layer")
    
    result = output_layer()
    
    # Each source and module should execute exactly once
    assert source1.execution_count == 1, "S1 should execute once"
    assert source2.execution_count == 1, "S2 should execute once"
    assert CountingModule.execution_counts["A"] == 1, "A should execute once"
    assert CountingModule.execution_counts["B"] == 1, "B should execute once"
    assert CountingModule.execution_counts["C"] == 1, "C should execute once"
    assert CountingModule.execution_counts["D"] == 1, "D should execute once"
    assert module_e.execution_count == 1, "E should execute once"
    assert module_f.execution_count == 1, "F should execute once"
    
    # Verify: S1(10) -> A(11), B(11) -> E(22)
    #         S2(20) -> C(21), D(21) -> F(42)
    assert result["s1_direct"][0] == 10.0
    assert result["s2_direct"][0] == 20.0
    assert result["e_result"][0] == 22.0
    assert result["f_result"][0] == 42.0


def test_output_layer_as_source_for_connected_module():
    """Test that OutputLayer can be used as source and caching still works."""
    CountingModule.reset_counts()
    
    source = SourceModule("source", 5.0)
    module_a = CountingModule("A")
    module_b = CountingModule("B")
    
    conn_a = module_a.connect({"input": source.output("output")})
    conn_b = module_b.connect({"input": source.output("output")})
    
    # Create OutputLayer
    output_layer = OutputLayer({
        "val_a": conn_a.output("output"),
        "val_b": conn_b.output("output")
    }, name="output_layer")
    
    # Use OutputLayer as source for another module
    module_c = SumModule("C")
    final = module_c.connect({
        "input1": output_layer.output("val_a"),
        "input2": output_layer.output("val_b")
    })
    
    result = final()
    
    # Source should execute once even though OutputLayer is used downstream
    assert source.execution_count == 1, "Source should execute once"
    assert CountingModule.execution_counts["A"] == 1, "A should execute once"
    assert CountingModule.execution_counts["B"] == 1, "B should execute once"
    assert module_c.execution_count == 1, "C should execute once"
    
    # Verify: source(5) -> A(6), B(6) -> C(12)
    assert result["output"][0] == 12.0


# ============================================================================
# OutputLayer as Input Examples with Caching Verification
# ============================================================================

def test_example_output_layer_reuses_computation():
    """
    Example: OutputLayer as intermediate layer that enables computation reuse.
    
    Pattern: Multiple downstream modules consume OutputLayer outputs, but the
    expensive computations only run once thanks to caching.
    """
    CountingModule.reset_counts()
    
    # Expensive data source
    expensive_source = SourceModule("expensive_computation", 10.0)
    
    # Multiple expensive processors
    processor_a = CountingModule("processor_a")
    processor_b = CountingModule("processor_b")
    processor_c = CountingModule("processor_c")
    
    proc_a = processor_a.connect({"input": expensive_source.output("output")})
    proc_b = processor_b.connect({"input": expensive_source.output("output")})
    proc_c = processor_c.connect({"input": expensive_source.output("output")})
    
    # OutputLayer gathers all processed results
    processed_data = OutputLayer({
        "result_a": proc_a.output("output"),
        "result_b": proc_b.output("output"),
        "result_c": proc_c.output("output")
    }, name="processed_data")
    
    # Multiple consumers use the same OutputLayer
    consumer1 = SumModule("consumer1")
    consumer2 = SumModule("consumer2")
    
    # Each consumer picks different combinations
    pipeline1 = consumer1.connect({
        "input1": processed_data.output("result_a"),
        "input2": processed_data.output("result_b")
    })
    
    pipeline2 = consumer2.connect({
        "input1": processed_data.output("result_b"),
        "input2": processed_data.output("result_c")
    })
    
    # Execute both pipelines - all computation is shared!
    result1 = pipeline1()
    result2 = pipeline2()
    
    # Despite complex graph, each module executes only once per call
    assert expensive_source.execution_count == 2  # Once per pipeline call
    assert CountingModule.execution_counts["processor_a"] == 2
    assert CountingModule.execution_counts["processor_b"] == 2
    assert CountingModule.execution_counts["processor_c"] == 2
    
    # Verify results: 10 -> 11, 11, 11 -> sums
    assert result1["output"][0] == 22.0  # 11 + 11
    assert result2["output"][0] == 22.0  # 11 + 11


def test_example_output_layer_in_nested_structure():
    """
    Example: OutputLayer within nested processing structure maintains caching.
    
    Demonstrates that even in complex nested structures, OutputLayer properly
    participates in the execution context for optimal performance.
    """
    CountingModule.reset_counts()
    
    # Create a processing tree
    root = SourceModule("root", 100.0)
    
    # First level processing
    left_branch = CountingModule("left")
    right_branch = CountingModule("right")
    
    left_result = left_branch.connect({"input": root.output("output")})
    right_result = right_branch.connect({"input": root.output("output")})
    
    # Gather first level with OutputLayer
    first_level = OutputLayer({
        "left_data": left_result.output("output"),
        "right_data": right_result.output("output")
    }, name="first_level")
    
    # Second level uses OutputLayer outputs
    merge_left = CountingModule("merge_left")
    merge_right = CountingModule("merge_right")
    
    merged_left = merge_left.connect({"input": first_level.output("left_data")})
    merged_right = merge_right.connect({"input": first_level.output("right_data")})
    
    # Final layer gathers everything
    final_output = OutputLayer({
        "branch_left": merged_left.output("output"),
        "branch_right": merged_right.output("output")
    }, name="final_output")
    
    # Execute
    result = final_output()
    
    # Verify caching worked: root executed once, each processor once
    assert root.execution_count == 1
    assert CountingModule.execution_counts["left"] == 1
    assert CountingModule.execution_counts["right"] == 1
    assert CountingModule.execution_counts["merge_left"] == 1
    assert CountingModule.execution_counts["merge_right"] == 1
    
    # Verify data flow: 100 -> 101, 101 -> 102, 102
    assert result["branch_left"][0] == 102.0
    assert result["branch_right"][0] == 102.0


def test_example_output_layer_selective_output_usage():
    """
    Example: OutputLayer provides many outputs but downstream only uses some.
    
    Shows that even though OutputLayer gathers many outputs, only the ones
    actually used by downstream modules are computed (lazy evaluation isn't
    implemented, but this shows the pattern).
    """
    CountingModule.reset_counts()
    
    # Multiple data sources
    source1 = SourceModule("source1", 1.0)
    source2 = SourceModule("source2", 2.0)
    source3 = SourceModule("source3", 3.0)
    source4 = SourceModule("source4", 4.0)
    
    processor1 = CountingModule("proc1")
    processor2 = CountingModule("proc2")
    processor3 = CountingModule("proc3")
    processor4 = CountingModule("proc4")
    
    proc1 = processor1.connect({"input": source1.output("output")})
    proc2 = processor2.connect({"input": source2.output("output")})
    proc3 = processor3.connect({"input": source3.output("output")})
    proc4 = processor4.connect({"input": source4.output("output")})
    
    # OutputLayer offers many outputs
    data_hub = OutputLayer({
        "channel_1": proc1.output("output"),
        "channel_2": proc2.output("output"),
        "channel_3": proc3.output("output"),
        "channel_4": proc4.output("output")
    }, name="data_hub")
    
    # Downstream module only uses two channels
    consumer = SumModule("consumer")
    final = consumer.connect({
        "input1": data_hub.output("channel_1"),
        "input2": data_hub.output("channel_3")
    })
    
    result = final()
    
    # All processors execute because OutputLayer evaluates all its sources
    # This is expected behavior - OutputLayer is eager, not lazy
    assert source1.execution_count == 1
    assert source2.execution_count == 1
    assert source3.execution_count == 1
    assert source4.execution_count == 1
    
    # Result uses only channels 1 and 3: (1+1) + (3+1) = 6
    assert result["output"][0] == 6.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
