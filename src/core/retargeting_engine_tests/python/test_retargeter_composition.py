# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for retargeter composition - connecting retargeters together.

Tests the .connect() method and RetargeterSubgraph functionality.
"""

import pytest
from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    TensorGroupType,
    TensorGroup,
    RetargeterSubgraph,
    OutputCombiner,
)
from isaacteleop.retargeting_engine.tensor_types import (
    FloatType,
    IntType,
)


# ============================================================================
# Simple Retargeter Implementations for Testing
# ============================================================================


class SourceRetargeter(BaseRetargeter):
    """A source retargeter that produces constant outputs."""

    def __init__(self, name: str) -> None:
        super().__init__(name)

    def input_spec(self):
        return {
            "dummy": TensorGroupType("dummy_input", [FloatType("unused")]),
        }

    def output_spec(self):
        return {
            "value": TensorGroupType("output_value", [FloatType("v")]),
        }

    def compute(self, inputs, outputs):
        # Always output 10.0
        outputs["value"][0] = 10.0


class AddRetargeter(BaseRetargeter):
    """Add two float inputs."""

    def __init__(self, name: str) -> None:
        super().__init__(name)

    def input_spec(self):
        return {
            "a": TensorGroupType("input_a", [FloatType("value")]),
            "b": TensorGroupType("input_b", [FloatType("value")]),
        }

    def output_spec(self):
        return {
            "sum": TensorGroupType("output_sum", [FloatType("result")]),
        }

    def compute(self, inputs, outputs):
        a = inputs["a"][0]
        b = inputs["b"][0]
        outputs["sum"][0] = a + b


class DoubleRetargeter(BaseRetargeter):
    """Double a float input."""

    def __init__(self, name: str) -> None:
        super().__init__(name)

    def input_spec(self):
        return {
            "x": TensorGroupType("input_x", [FloatType("value")]),
        }

    def output_spec(self):
        return {
            "result": TensorGroupType("output_result", [FloatType("doubled")]),
        }

    def compute(self, inputs, outputs):
        x = inputs["x"][0]
        outputs["result"][0] = x * 2.0


class TripleRetargeter(BaseRetargeter):
    """Triple a float input."""

    def __init__(self, name: str) -> None:
        super().__init__(name)

    def input_spec(self):
        return {
            "x": TensorGroupType("input_x", [FloatType("value")]),
        }

    def output_spec(self):
        return {
            "result": TensorGroupType("output_result", [FloatType("tripled")]),
        }

    def compute(self, inputs, outputs):
        x = inputs["x"][0]
        outputs["result"][0] = x * 3.0


class MultiOutputRetargeter(BaseRetargeter):
    """Retargeter with multiple outputs."""

    def __init__(self, name: str) -> None:
        super().__init__(name)

    def input_spec(self):
        return {
            "x": TensorGroupType("input_x", [FloatType("value")]),
        }

    def output_spec(self):
        return {
            "doubled": TensorGroupType("output_doubled", [FloatType("x2")]),
            "tripled": TensorGroupType("output_tripled", [FloatType("x3")]),
        }

    def compute(self, inputs, outputs):
        x = inputs["x"][0]
        outputs["doubled"][0] = x * 2.0
        outputs["tripled"][0] = x * 3.0


class CountingRetargeter(BaseRetargeter):
    """Retargeter that counts how many times compute() is called."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.compute_count = 0

    def input_spec(self):
        return {
            "x": TensorGroupType("input_x", [FloatType("value")]),
        }

    def output_spec(self):
        return {
            "result": TensorGroupType("output_result", [FloatType("value")]),
        }

    def compute(self, inputs, outputs):
        self.compute_count += 1
        x = inputs["x"][0]
        outputs["result"][0] = x + 1.0


# ============================================================================
# Test Classes
# ============================================================================


class TestSimpleConnection:
    """Test simple retargeter connections."""

    def test_connect_two_retargeters(self):
        """Test connecting two retargeters."""
        source = SourceRetargeter("source")
        double = DoubleRetargeter("double")

        # Connect double's input to source's output
        connected = double.connect({"x": source.output("value")})

        assert connected is not None
        assert isinstance(connected, RetargeterSubgraph)

    def test_execute_connected_retargeters(self):
        """Test executing connected retargeters."""
        source = SourceRetargeter("source")
        double = DoubleRetargeter("double")

        # Connect
        connected = double.connect({"x": source.output("value")})

        # Execute - need to provide leaf inputs
        dummy_input = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
        dummy_input[0] = 0.0

        outputs = connected({"source": {"dummy": dummy_input}})

        # Source outputs 10.0, double should output 20.0
        assert outputs["result"][0] == 20.0

    def test_chain_three_retargeters(self):
        """Test chaining three retargeters."""
        source = SourceRetargeter("source")
        double = DoubleRetargeter("double")
        triple = TripleRetargeter("triple")

        # Chain: source -> double -> triple
        connected_double = double.connect({"x": source.output("value")})

        connected_triple = triple.connect({"x": connected_double.output("result")})

        # Execute
        dummy_input = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
        dummy_input[0] = 0.0

        outputs = connected_triple({"source": {"dummy": dummy_input}})

        # Source: 10.0 -> double: 20.0 -> triple: 60.0
        assert outputs["result"][0] == 60.0


class TestConnectionValidation:
    """Test connection validation."""

    def test_missing_input_connection_raises(self):
        """Test that missing input connection raises error."""
        source = SourceRetargeter("source")
        add = AddRetargeter("add")

        # Only connect one of two required inputs
        with pytest.raises(ValueError, match="Input mismatch"):
            add.connect(
                {
                    "a": source.output("value")
                    # Missing "b"
                }
            )

    def test_extra_input_connection_raises(self):
        """Test that extra input connection raises error."""
        source = SourceRetargeter("source")
        double = DoubleRetargeter("double")

        # Provide extra input connection
        with pytest.raises(ValueError, match="Input mismatch"):
            double.connect(
                {
                    "x": source.output("value"),
                    "y": source.output("value"),  # Extra!
                }
            )

    def test_wrong_type_connection_raises(self):
        """Test that wrong type connection raises error."""

        # Create a retargeter that outputs int
        class IntSourceRetargeter(BaseRetargeter):
            def __init__(self, name: str) -> None:
                super().__init__(name)

            def input_spec(self):
                return {
                    "dummy": TensorGroupType("dummy", [IntType("unused")]),
                }

            def output_spec(self):
                return {
                    "value": TensorGroupType("output_value", [IntType("v")]),
                }

            def compute(self, inputs, outputs):
                outputs["value"][0] = 10

        int_source = IntSourceRetargeter("int_source")
        double = DoubleRetargeter("double")  # Expects float

        # Try to connect int output to float input
        with pytest.raises(ValueError):
            double.connect({"x": int_source.output("value")})


class TestMultipleInputConnections:
    """Test connecting retargeters with multiple inputs."""

    def test_connect_add_with_two_sources(self):
        """Test connecting AddRetargeter with two separate sources."""
        source1 = SourceRetargeter("source1")
        source2 = SourceRetargeter("source2")
        add = AddRetargeter("add")

        # Connect add's two inputs to two different sources
        connected = add.connect(
            {
                "a": source1.output("value"),
                "b": source2.output("value"),
            }
        )

        # Execute
        dummy_input1 = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
        dummy_input2 = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
        dummy_input1[0] = 0.0
        dummy_input2[0] = 0.0

        outputs = connected(
            {"source1": {"dummy": dummy_input1}, "source2": {"dummy": dummy_input2}}
        )

        # Both sources output 10.0, so sum should be 20.0
        assert outputs["sum"][0] == 20.0

    def test_connect_add_with_same_source(self):
        """Test connecting both inputs of AddRetargeter to same source."""
        source = SourceRetargeter("source")
        add = AddRetargeter("add")

        # Connect both inputs to same source
        connected = add.connect(
            {
                "a": source.output("value"),
                "b": source.output("value"),
            }
        )

        # Execute
        dummy_input = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
        dummy_input[0] = 0.0

        outputs = connected({"source": {"dummy": dummy_input}})

        # Source outputs 10.0, so 10.0 + 10.0 = 20.0
        assert outputs["sum"][0] == 20.0

    def test_connect_add_with_different_retargeters(self):
        """Test connecting AddRetargeter to different processing retargeters."""
        source = SourceRetargeter("source")
        double = DoubleRetargeter("double")
        triple = TripleRetargeter("triple")
        add = AddRetargeter("add")

        # Chain source -> double and source -> triple, then add results
        connected_double = double.connect({"x": source.output("value")})

        connected_triple = triple.connect({"x": source.output("value")})

        connected_add = add.connect(
            {
                "a": connected_double.output("result"),
                "b": connected_triple.output("result"),
            }
        )

        # Execute
        dummy_input = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
        dummy_input[0] = 0.0

        outputs = connected_add({"source": {"dummy": dummy_input}})

        # Source: 10.0, double: 20.0, triple: 30.0, add: 50.0
        assert outputs["sum"][0] == 50.0


class TestMultipleOutputConnections:
    """Test connecting from retargeters with multiple outputs."""

    def test_connect_to_specific_output(self):
        """Test connecting to specific output of multi-output retargeter."""
        source = SourceRetargeter("source")
        multi = MultiOutputRetargeter("multi")
        double = DoubleRetargeter("double")

        # Connect multi to source
        connected_multi = multi.connect({"x": source.output("value")})

        # Connect double to multi's "doubled" output
        connected_double = double.connect({"x": connected_multi.output("doubled")})

        # Execute
        dummy_input = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
        dummy_input[0] = 0.0

        outputs = connected_double({"source": {"dummy": dummy_input}})

        # Source: 10.0, multi.doubled: 20.0, double: 40.0
        assert outputs["result"][0] == 40.0

    def test_connect_to_different_outputs(self):
        """Test connecting different retargeters to different outputs."""
        source = SourceRetargeter("source")
        multi = MultiOutputRetargeter("multi")
        double = DoubleRetargeter("double")
        triple = TripleRetargeter("triple")
        add = AddRetargeter("add")

        # Connect multi to source
        connected_multi = multi.connect({"x": source.output("value")})

        # Connect double to multi's "doubled" output
        connected_double = double.connect({"x": connected_multi.output("doubled")})

        # Connect triple to multi's "tripled" output
        connected_triple = triple.connect({"x": connected_multi.output("tripled")})

        # Add the results
        connected_add = add.connect(
            {
                "a": connected_double.output("result"),
                "b": connected_triple.output("result"),
            }
        )

        # Execute
        dummy_input = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
        dummy_input[0] = 0.0

        outputs = connected_add({"source": {"dummy": dummy_input}})

        # Source: 10.0
        # multi.doubled: 20.0, multi.tripled: 30.0
        # double(20.0): 40.0, triple(30.0): 90.0
        # add: 130.0
        assert outputs["sum"][0] == 130.0


class TestComplexGraphs:
    """Test complex retargeter graphs."""

    def test_diamond_graph(self):
        """Test diamond-shaped computation graph."""
        # Create diamond: source -> [double, triple] -> add
        source = SourceRetargeter("source")
        double = DoubleRetargeter("double")
        triple = TripleRetargeter("triple")
        add = AddRetargeter("add")

        # Connect double and triple to source
        connected_double = double.connect({"x": source.output("value")})

        connected_triple = triple.connect({"x": source.output("value")})

        # Connect add to both branches
        connected_add = add.connect(
            {
                "a": connected_double.output("result"),
                "b": connected_triple.output("result"),
            }
        )

        # Execute
        dummy_input = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
        dummy_input[0] = 0.0

        outputs = connected_add({"source": {"dummy": dummy_input}})

        # Source: 10.0, double: 20.0, triple: 30.0, add: 50.0
        assert outputs["sum"][0] == 50.0

    def test_deep_chain(self):
        """Test deep chain of retargeters."""
        source = SourceRetargeter("source")

        # Create chain: source -> double -> double -> double -> double
        retargeters = [source]
        for i in range(4):
            double = DoubleRetargeter(f"double_{i}")
            if i == 0:
                connected = double.connect({"x": retargeters[-1].output("value")})
            else:
                connected = double.connect({"x": retargeters[-1].output("result")})
            retargeters.append(connected)

        # Execute final retargeter
        dummy_input = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
        dummy_input[0] = 0.0

        outputs = retargeters[-1]({"source": {"dummy": dummy_input}})

        # Source: 10.0, then doubled 4 times: 10 * 2^4 = 160.0
        assert outputs["result"][0] == 160.0


class TestConnectionReuse:
    """Test that connected retargeters can be reused."""

    def test_connected_retargeter_reuse(self):
        """Test reusing a connected retargeter."""
        source = SourceRetargeter("source")
        double = DoubleRetargeter("double")

        connected = double.connect({"x": source.output("value")})

        # Execute multiple times
        for _ in range(3):
            dummy_input = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
            dummy_input[0] = 0.0

            outputs = connected({"source": {"dummy": dummy_input}})
            assert outputs["result"][0] == 20.0


class TestExecutionCaching:
    """Test that modules are only computed once per execution."""

    def test_diamond_graph_caching(self):
        """Test that a shared source is only computed once in a diamond graph."""
        source = SourceRetargeter("source")
        counter = CountingRetargeter("counter")
        left = DoubleRetargeter("left")
        right = TripleRetargeter("right")
        add = AddRetargeter("add")

        # Create diamond: source -> counter, counter splits to left and right, both feed into add
        connected_counter = counter.connect({"x": source.output("value")})
        connected_left = left.connect({"x": connected_counter.output("result")})
        connected_right = right.connect({"x": connected_counter.output("result")})
        connected_add = add.connect(
            {
                "a": connected_left.output("result"),
                "b": connected_right.output("result"),
            }
        )

        # Reset counter
        counter.compute_count = 0

        # Execute
        dummy_input = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
        dummy_input[0] = 0.0

        outputs = connected_add({"source": {"dummy": dummy_input}})

        # Counter should only compute once despite being referenced twice
        assert counter.compute_count == 1

        # Verify result: source outputs 10.0, counter outputs 11.0, left doubles to 22.0, right triples to 33.0, add sums to 55.0
        assert outputs["sum"][0] == 55.0

    def test_multi_output_caching(self):
        """Test that a module with multiple outputs is only computed once."""
        source = SourceRetargeter("source")
        multi = CountingRetargeter("multi")
        left = DoubleRetargeter("left")
        right = DoubleRetargeter("right")
        add = AddRetargeter("add")

        # Connect multi to source
        connected_multi = multi.connect({"x": source.output("value")})

        # Both left and right use the same output from multi
        connected_left = left.connect({"x": connected_multi.output("result")})
        connected_right = right.connect({"x": connected_multi.output("result")})

        # Add uses both outputs
        connected_add = add.connect(
            {
                "a": connected_left.output("result"),
                "b": connected_right.output("result"),
            }
        )

        # Reset counter
        multi.compute_count = 0

        # Execute
        dummy_input = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
        dummy_input[0] = 0.0

        outputs = connected_add({"source": {"dummy": dummy_input}})

        # Multi should only compute once despite being referenced twice
        assert multi.compute_count == 1

        # Verify result: source=10.0, multi=11.0, left=22.0, right=22.0, add=44.0
        assert outputs["sum"][0] == 44.0

    def test_complex_dag_caching(self):
        """Test caching in a complex DAG with multiple shared nodes."""
        # Create a complex graph:
        #       source
        #       /    \
        #    count1  count2
        #      |  \  /  |
        #      |   \/   |
        #      |   /\   |
        #      |  /  \  |
        #    left    right
        #       \    /
        #        add

        source = SourceRetargeter("source")
        count1 = CountingRetargeter("count1")
        count2 = CountingRetargeter("count2")
        left = DoubleRetargeter("left")
        right = TripleRetargeter("right")
        add = AddRetargeter("add")

        # Build the graph
        connected_count1 = count1.connect({"x": source.output("value")})
        connected_count2 = count2.connect({"x": source.output("value")})

        # Left uses both count1 and count2 (by adding them first)
        add_temp = AddRetargeter("add_temp")
        connected_add_temp = add_temp.connect(
            {
                "a": connected_count1.output("result"),
                "b": connected_count2.output("result"),
            }
        )

        connected_left = left.connect({"x": connected_add_temp.output("sum")})

        # Right also uses count2
        connected_right = right.connect({"x": connected_count2.output("result")})

        # Final add
        connected_final = add.connect(
            {
                "a": connected_left.output("result"),
                "b": connected_right.output("result"),
            }
        )

        # Reset counters
        count1.compute_count = 0
        count2.compute_count = 0

        # Execute
        dummy_input = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
        dummy_input[0] = 0.0

        outputs = connected_final({"source": {"dummy": dummy_input}})

        # Each counter should only compute once despite multiple references
        assert count1.compute_count == 1
        assert count2.compute_count == 1

        # Verify result:
        # source=10.0, count1=11.0, count2=11.0
        # add_temp=22.0, left=44.0, right=33.0, final=77.0
        assert outputs["sum"][0] == 77.0

    def test_subgraph_caching(self):
        """Test that subgraphs themselves are cached."""
        source = SourceRetargeter("source")
        counter = CountingRetargeter("counter")

        # Create a connected subgraph
        connected = counter.connect({"x": source.output("value")})

        # Use the same subgraph output twice in an add
        add = AddRetargeter("add")
        connected_add = add.connect(
            {"a": connected.output("result"), "b": connected.output("result")}
        )

        # Reset counter
        counter.compute_count = 0

        # Execute
        dummy_input = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
        dummy_input[0] = 0.0

        outputs = connected_add({"source": {"dummy": dummy_input}})

        # Counter should only compute once
        assert counter.compute_count == 1

        # Verify result: source=10.0, counter=11.0, add=22.0
        assert outputs["sum"][0] == 22.0


class TestOutputCombiner:
    """Test OutputCombiner functionality."""

    def test_combine_two_outputs(self):
        """Test combining outputs from two retargeters."""
        source1 = SourceRetargeter("source1")
        source2 = SourceRetargeter("source2")

        # Combine outputs with custom names
        combiner = OutputCombiner(
            {"first": source1.output("value"), "second": source2.output("value")}
        )

        # Execute
        dummy_input = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
        dummy_input[0] = 0.0

        outputs = combiner(
            {"source1": {"dummy": dummy_input}, "source2": {"dummy": dummy_input}}
        )

        # Check outputs are present with custom names
        assert "first" in outputs
        assert "second" in outputs
        assert outputs["first"][0] == 10.0
        assert outputs["second"][0] == 10.0

    def test_combiner_as_source(self):
        """Test using OutputCombiner as a source in further connections."""
        source = SourceRetargeter("source")
        double = DoubleRetargeter("double")
        triple = TripleRetargeter("triple")

        # Connect double and triple to source
        connected_double = double.connect({"x": source.output("value")})
        connected_triple = triple.connect({"x": source.output("value")})

        # Combine their outputs
        combiner = OutputCombiner(
            {
                "doubled": connected_double.output("result"),
                "tripled": connected_triple.output("result"),
            }
        )

        # Use combiner as source for add
        add = AddRetargeter("add")
        connected_add = add.connect(
            {"a": combiner.output("doubled"), "b": combiner.output("tripled")}
        )

        # Execute
        dummy_input = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
        dummy_input[0] = 0.0

        outputs = connected_add({"source": {"dummy": dummy_input}})

        # source=10.0, doubled=20.0, tripled=30.0, sum=50.0
        assert outputs["sum"][0] == 50.0

    def test_combiner_caching(self):
        """Test that OutputCombiner benefits from execution caching."""
        source = SourceRetargeter("source")
        counter = CountingRetargeter("counter")

        # Connect counter to source
        connected_counter = counter.connect({"x": source.output("value")})

        # Create combiner that references counter multiple times
        combiner = OutputCombiner(
            {
                "result1": connected_counter.output("result"),
                "result2": connected_counter.output("result"),
            }
        )

        # Use combiner outputs in an add
        add = AddRetargeter("add")
        connected_add = add.connect(
            {"a": combiner.output("result1"), "b": combiner.output("result2")}
        )

        # Reset counter
        counter.compute_count = 0

        # Execute
        dummy_input = TensorGroup(TensorGroupType("dummy", [FloatType("unused")]))
        dummy_input[0] = 0.0

        outputs = connected_add({"source": {"dummy": dummy_input}})

        # Counter should only compute once
        assert counter.compute_count == 1

        # Verify result: source=10.0, counter=11.0, add=22.0
        assert outputs["sum"][0] == 22.0

    def test_combiner_validation(self):
        """Test OutputCombiner validation."""
        source = SourceRetargeter("source")

        # Empty mapping should raise
        with pytest.raises(ValueError, match="at least one output"):
            OutputCombiner({})

        # Non-OutputSelector should raise
        with pytest.raises(TypeError, match="Expected OutputSelector"):
            OutputCombiner({"bad": "not_a_selector"})

        # Invalid output name should raise
        with pytest.raises(ValueError, match="not found"):
            OutputCombiner({"bad": source.output("nonexistent")})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
