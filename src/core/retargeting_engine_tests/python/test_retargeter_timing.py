# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for retargeter timing — GraphTime and ComputeContext.

Covers:
  - GraphTime / ComputeContext dataclasses
  - Standalone retargeters: compute() auto-generates a ComputeContext, or
    accepts an explicit one; __call__ mirrors the same behaviour
  - Monotonicity of successive __call__ timestamps
  - Propagation of GraphTime to ALL nodes in connected subgraphs (both leaf
    sources and downstream target nodes)
"""

import time
from typing import Optional

import pytest

from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    ComputeContext,
    GraphTime,
    TensorGroup,
    TensorGroupType,
    ValueInput,
)
from isaacteleop.retargeting_engine.tensor_types import FloatType


# ============================================================================
# Timing-Aware Retargeters for Testing
# ============================================================================


class TimingCaptureRetargeter(BaseRetargeter):
    """Pass-through retargeter that records the ComputeContext on every _compute_fn
    call for later inspection by tests."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.last_context: Optional[ComputeContext] = None

    def input_spec(self):
        return {"x": TensorGroupType("input_x", [FloatType("value")])}

    def output_spec(self):
        return {"result": TensorGroupType("output_result", [FloatType("value")])}

    def _compute_fn(self, inputs, outputs, context):
        self.last_context = context
        outputs["result"][0] = inputs["x"][0]


class NoInputTimingRetargeter(BaseRetargeter):
    """Source retargeter (no inputs) that records its ComputeContext."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.last_context: Optional[ComputeContext] = None

    def input_spec(self):
        return {}

    def output_spec(self):
        return {"value": TensorGroupType("output_value", [FloatType("v")])}

    def _compute_fn(self, inputs, outputs, context):
        self.last_context = context
        outputs["value"][0] = 1.0


# ============================================================================
# Helpers
# ============================================================================


def _make_float_input(value: float = 1.0) -> dict:
    """Create a minimal {"x": TensorGroup} dict for TimingCaptureRetargeter."""
    tg = TensorGroup(TensorGroupType("x", [FloatType("value")]))
    tg[0] = value
    return {"x": tg}


def _make_float_output() -> dict:
    """Pre-allocate the {"result": TensorGroup} outputs for TimingCaptureRetargeter."""
    return {
        "result": TensorGroup(TensorGroupType("output_result", [FloatType("value")]))
    }


def _make_no_input_output() -> dict:
    """Pre-allocate the {"value": TensorGroup} outputs for NoInputTimingRetargeter."""
    return {"value": TensorGroup(TensorGroupType("output_value", [FloatType("v")]))}


def _trigger(r: "TimingCaptureRetargeter", graph_time: GraphTime) -> None:
    """Call compute with an explicit ComputeContext on a TimingCaptureRetargeter."""
    r.compute(
        _make_float_input(), _make_float_output(), ComputeContext(graph_time=graph_time)
    )


# ============================================================================
# GraphTime Dataclass Tests
# ============================================================================


class TestGraphTime:
    """Unit tests for the GraphTime dataclass."""

    def test_stores_sim_and_real_time(self):
        gt = GraphTime(sim_time_ns=1_000, real_time_ns=2_000)
        assert gt.sim_time_ns == 1_000
        assert gt.real_time_ns == 2_000

    def test_sim_and_real_time_can_differ(self):
        gt = GraphTime(sim_time_ns=0, real_time_ns=999_999_999_999)
        assert gt.sim_time_ns != gt.real_time_ns

    def test_is_immutable(self):
        """GraphTime is a frozen dataclass — field assignment must raise."""
        gt = GraphTime(sim_time_ns=1_000, real_time_ns=2_000)
        with pytest.raises((AttributeError, TypeError)):
            gt.sim_time_ns = 9_999  # type: ignore[misc]

    def test_equality(self):
        gt1 = GraphTime(sim_time_ns=500, real_time_ns=600)
        gt2 = GraphTime(sim_time_ns=500, real_time_ns=600)
        assert gt1 == gt2

    def test_inequality_on_sim_time(self):
        gt1 = GraphTime(sim_time_ns=500, real_time_ns=600)
        gt2 = GraphTime(sim_time_ns=501, real_time_ns=600)
        assert gt1 != gt2

    def test_inequality_on_real_time(self):
        gt1 = GraphTime(sim_time_ns=500, real_time_ns=600)
        gt2 = GraphTime(sim_time_ns=500, real_time_ns=601)
        assert gt1 != gt2

    def test_accepts_zero_timestamps(self):
        gt = GraphTime(sim_time_ns=0, real_time_ns=0)
        assert gt.sim_time_ns == 0
        assert gt.real_time_ns == 0

    def test_accepts_large_timestamps(self):
        large = 10**18  # ~31 years in nanoseconds
        gt = GraphTime(sim_time_ns=large, real_time_ns=large)
        assert gt.sim_time_ns == large
        assert gt.real_time_ns == large


# ============================================================================
# ComputeContext Dataclass Tests
# ============================================================================


class TestComputeContext:
    """Unit tests for the ComputeContext dataclass."""

    def test_stores_graph_time(self):
        gt = GraphTime(sim_time_ns=42, real_time_ns=99)
        ctx = ComputeContext(graph_time=gt)
        assert ctx.graph_time is gt

    def test_graph_time_fields_accessible(self):
        gt = GraphTime(sim_time_ns=42, real_time_ns=99)
        ctx = ComputeContext(graph_time=gt)
        assert ctx.graph_time.sim_time_ns == 42
        assert ctx.graph_time.real_time_ns == 99


# ============================================================================
# Standalone Retargeter Timing Tests
# ============================================================================


class TestStandaloneComputeTiming:
    """Tests for timing behaviour of retargeters called standalone (not in a graph)."""

    def test_compute_delivers_non_none_context(self):
        """compute() must pass a ComputeContext (not None) to _compute_fn."""
        r = TimingCaptureRetargeter("r")
        r(_make_float_input())
        assert r.last_context is not None

    def test_compute_delivers_non_none_graph_time(self):
        """The GraphTime inside the context must be non-None after compute()."""
        r = TimingCaptureRetargeter("r")
        r(_make_float_input())
        assert r.last_context.graph_time is not None

    def test_compute_graph_time_real_time_is_recent(self):
        """real_time_ns from compute() should fall within the wall-clock window
        bracketing the call."""
        before_ns = time.monotonic_ns()
        r = TimingCaptureRetargeter("r")
        r(_make_float_input())
        after_ns = time.monotonic_ns()

        rt = r.last_context.graph_time.real_time_ns
        assert before_ns <= rt <= after_ns, (
            f"real_time_ns {rt} not in [{before_ns}, {after_ns}]"
        )

    def test_compute_graph_time_sim_time_equals_real_time(self):
        """compute() sets sim_time_ns == real_time_ns (both from monotonic clock)."""
        r = TimingCaptureRetargeter("r")
        r(_make_float_input())
        gt = r.last_context.graph_time
        assert gt.sim_time_ns == gt.real_time_ns

    def test_compute_with_explicit_context_passes_graph_time(self):
        """compute() with an explicit ComputeContext must forward GraphTime unchanged."""
        r = TimingCaptureRetargeter("r")
        explicit = GraphTime(sim_time_ns=12_345, real_time_ns=67_890)
        _trigger(r, explicit)

        assert r.last_context.graph_time == explicit
        assert r.last_context.graph_time.sim_time_ns == 12_345
        assert r.last_context.graph_time.real_time_ns == 67_890

    def test_compute_sim_and_real_time_independent(self):
        """sim_time_ns and real_time_ns in the context can hold different values."""
        r = TimingCaptureRetargeter("r")
        gt = GraphTime(sim_time_ns=0, real_time_ns=1_000_000_000_000)
        _trigger(r, gt)

        ctx_gt = r.last_context.graph_time
        assert ctx_gt.sim_time_ns == 0
        assert ctx_gt.real_time_ns == 1_000_000_000_000

    def test_compute_with_successive_contexts_updates_correctly(self):
        """Successive compute() calls with different contexts each deliver the right time."""
        r = TimingCaptureRetargeter("r")
        gt1 = GraphTime(sim_time_ns=100, real_time_ns=200)
        gt2 = GraphTime(sim_time_ns=300, real_time_ns=400)

        _trigger(r, gt1)
        assert r.last_context.graph_time == gt1

        _trigger(r, gt2)
        assert r.last_context.graph_time == gt2

    def test_consecutive_compute_calls_monotonically_non_decreasing(self):
        """Successive __call__ invocations must produce non-decreasing real_time_ns."""
        r = TimingCaptureRetargeter("r")
        times = []
        for _ in range(6):
            r(_make_float_input())
            times.append(r.last_context.graph_time.real_time_ns)

        for i in range(1, len(times)):
            assert times[i] >= times[i - 1], (
                f"real_time_ns decreased at step {i}: {times[i - 1]} -> {times[i]}"
            )

    def test_no_input_retargeter_receives_graph_time(self):
        """Source retargeters with no inputs also receive GraphTime via an explicit context."""
        r = NoInputTimingRetargeter("source")
        explicit = GraphTime(sim_time_ns=999, real_time_ns=888)
        r.compute({}, _make_no_input_output(), ComputeContext(graph_time=explicit))

        assert r.last_context is not None
        assert r.last_context.graph_time == explicit

    def test_callable_shorthand_behaves_like_compute(self):
        """__call__ (r(inputs)) should produce the same timing behaviour as compute()."""
        r = TimingCaptureRetargeter("r")
        before_ns = time.monotonic_ns()
        r(_make_float_input())
        after_ns = time.monotonic_ns()

        rt = r.last_context.graph_time.real_time_ns
        assert before_ns <= rt <= after_ns


# ============================================================================
# Connected Subgraph Timing Tests
# ============================================================================


class TestSubgraphTiming:
    """Tests that GraphTime propagates correctly to ALL nodes in connected graphs.

    Both leaf (source) nodes and downstream (target) nodes receive the same
    ComputeContext — forwarded through ExecutionCache into _compute_with_cache
    and then into ``compute`` by RetargeterSubgraph._compute_with_cache.
    """

    def _build_chain(self):
        """Build: source (leaf) --[result]--> downstream (target), return both and the subgraph."""
        source = TimingCaptureRetargeter("source")
        downstream = TimingCaptureRetargeter("downstream")
        connected = downstream.connect({"x": source.output("result")})
        return source, downstream, connected

    def _make_source_input(self, value: float = 5.0) -> dict:
        tg = TensorGroup(TensorGroupType("x", [FloatType("value")]))
        tg[0] = value
        return {"source": {"x": tg}}

    def test_subgraph_call_with_context_propagates_graph_time_to_leaf(self):
        """__call__ with an explicit ComputeContext propagates GraphTime to both nodes."""
        source, downstream, connected = self._build_chain()

        explicit = GraphTime(sim_time_ns=5_000, real_time_ns=6_000)
        connected(self._make_source_input(), ComputeContext(graph_time=explicit))

        assert source.last_context is not None
        assert source.last_context.graph_time == explicit
        assert downstream.last_context is not None
        assert downstream.last_context.graph_time == explicit

    def test_subgraph_call_with_context_sim_and_real_time(self):
        """Both sim_time_ns and real_time_ns reach every node unchanged."""
        source, downstream, connected = self._build_chain()

        gt = GraphTime(sim_time_ns=111_111, real_time_ns=222_222)
        connected(self._make_source_input(), ComputeContext(graph_time=gt))

        for node in (source, downstream):
            node_gt = node.last_context.graph_time
            assert node_gt.sim_time_ns == 111_111
            assert node_gt.real_time_ns == 222_222

    def test_subgraph_compute_generates_graph_time_for_all_nodes(self):
        """compute() auto-generates a recent GraphTime delivered to every node."""
        source, downstream, connected = self._build_chain()

        before_ns = time.monotonic_ns()
        connected(self._make_source_input())
        after_ns = time.monotonic_ns()

        for node in (source, downstream):
            node_gt = node.last_context.graph_time
            assert before_ns <= node_gt.real_time_ns <= after_ns

    def test_subgraph_successive_contexts_update_all_nodes(self):
        """Two consecutive __call__ with different contexts update GraphTime on every node."""
        source, downstream, connected = self._build_chain()

        gt1 = GraphTime(sim_time_ns=1, real_time_ns=10)
        connected(self._make_source_input(), ComputeContext(graph_time=gt1))
        assert source.last_context.graph_time == gt1
        assert downstream.last_context.graph_time == gt1

        gt2 = GraphTime(sim_time_ns=2, real_time_ns=20)
        connected(self._make_source_input(), ComputeContext(graph_time=gt2))
        assert source.last_context.graph_time == gt2
        assert downstream.last_context.graph_time == gt2

    def test_subgraph_value_input_leaf_receives_graph_time(self):
        """ValueInput leaf (the standard external-input pattern) gets GraphTime."""
        val_type = TensorGroupType("val", [FloatType("x")])
        vi = ValueInput("vi", val_type)

        downstream = TimingCaptureRetargeter("downstream")
        connected = downstream.connect({"x": vi.output("value")})

        explicit = GraphTime(sim_time_ns=7_777, real_time_ns=8_888)

        inp = TensorGroup(val_type)
        inp[0] = 3.0
        connected({"vi": {"value": inp}}, ComputeContext(graph_time=explicit))

        assert downstream.last_context is not None
        assert downstream.last_context.graph_time == explicit

    def test_three_node_chain_all_nodes_receive_graph_time(self):
        """GraphTime propagates to every node in a three-node chain: leaf, mid, and tip."""
        leaf = TimingCaptureRetargeter("leaf")
        mid = TimingCaptureRetargeter("mid")
        tip = TimingCaptureRetargeter("tip")

        chain_mid = mid.connect({"x": leaf.output("result")})
        chain_tip = tip.connect({"x": chain_mid.output("result")})

        explicit = GraphTime(sim_time_ns=99_000, real_time_ns=88_000)

        tg = TensorGroup(TensorGroupType("x", [FloatType("value")]))
        tg[0] = 1.0
        chain_tip({"leaf": {"x": tg}}, ComputeContext(graph_time=explicit))

        for node in (leaf, mid, tip):
            assert node.last_context is not None, f"{node.name} did not run"
            assert node.last_context.graph_time == explicit, (
                f"{node.name}.graph_time {node.last_context.graph_time} != {explicit}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
