"""
Test comparing PyTorch's implicit parallelism vs Executor's sequential execution.

PyTorch can automatically parallelize independent operations:
- On GPU: CUDA streams can run multiple kernels concurrently
- On CPU: BLAS libraries (MKL/OpenBLAS) can parallelize across cores

Our RetargeterExecutor runs nodes sequentially even when they're independent.
This test quantifies the performance difference.
"""

import pytest
import time
import torch
from typing import List, Optional, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from .. import (
    InputNode,
    RetargeterNode,
    TensorCollection,
    TensorGroup,
    PyTorchTensorType,
    RetargeterExecutor,
    OutputSelector,
)


# ============================================================================
# Test Configuration
# ============================================================================

@dataclass
class ParallelTestConfig:
    """Configuration for parallel execution tests."""
    warmup_iterations: int = 5
    benchmark_iterations: int = 50
    num_parallel_branches: int = 4
    matrix_size: int = 512


# ============================================================================
# Helper Nodes
# ============================================================================

class TensorInputNode(InputNode):
    """Generic tensor input node."""
    
    def __init__(self, name: str, shape: tuple, device: str = 'cpu'):
        self._shape = shape
        self._device = device
        self._tensor = torch.zeros(shape, device=device)
        super().__init__(name)
    
    def _define_outputs(self) -> List[TensorCollection]:
        return [TensorCollection(f"{self._name}_out", [
            PyTorchTensorType(f"{self._name}", dtype=torch.float32, shape=self._shape, device=self._device)
        ])]
    
    def output(self) -> OutputSelector:
        return OutputSelector(self, 0)
    
    def set_tensor(self, tensor: torch.Tensor) -> None:
        self._tensor = tensor.to(self._device)
    
    def update(self, outputs: List[TensorGroup]) -> None:
        outputs[0][0] = self._tensor


class HeavyComputeRetargeter(RetargeterNode):
    """
    A retargeter that does heavy computation (multiple matmuls + activations).
    
    Simulates a realistic workload that takes measurable time.
    """
    
    def __init__(self, name: str, size: int, num_ops: int = 3, device: str = 'cpu'):
        self._size = size
        self._num_ops = num_ops
        self._device = device
        super().__init__(name=name)
    
    def _define_inputs(self) -> List[TensorCollection]:
        return [
            TensorCollection("input", [
                PyTorchTensorType("x", dtype=torch.float32, shape=(self._size, self._size), device=self._device)
            ]),
        ]
    
    def _define_outputs(self) -> List[TensorCollection]:
        return [TensorCollection("output", [
            PyTorchTensorType("result", dtype=torch.float32, shape=(self._size, self._size), device=self._device)
        ])]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup],
                output_mask: Optional[List[bool]] = None) -> None:
        x = inputs[0][0]
        result = x
        for _ in range(self._num_ops):
            result = torch.matmul(result, result.t())
            result = torch.relu(result)
            result = result / (result.norm() + 1e-6)  # Normalize to prevent overflow
        outputs[0][0] = result


class AggregatorRetargeter(RetargeterNode):
    """Aggregates multiple inputs by summing them."""
    
    def __init__(self, name: str, size: int, num_inputs: int, device: str = 'cpu'):
        self._size = size
        self._num_inputs = num_inputs
        self._device = device
        super().__init__(name=name)
    
    def _define_inputs(self) -> List[TensorCollection]:
        return [
            TensorCollection(f"input_{i}", [
                PyTorchTensorType(f"x_{i}", dtype=torch.float32, shape=(self._size, self._size), device=self._device)
            ])
            for i in range(self._num_inputs)
        ]
    
    def _define_outputs(self) -> List[TensorCollection]:
        return [TensorCollection("output", [
            PyTorchTensorType("sum_result", dtype=torch.float32, shape=(self._size, self._size), device=self._device)
        ])]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup],
                output_mask: Optional[List[bool]] = None) -> None:
        result = inputs[0][0].clone()
        for i in range(1, len(inputs)):
            result = result + inputs[i][0]
        outputs[0][0] = result


# ============================================================================
# Benchmark Utilities
# ============================================================================

def benchmark_fn(fn, warmup: int = 5, iterations: int = 50, device: str = 'cpu') -> float:
    """Benchmark a function, returns time per iteration in ms."""
    # Warmup
    for _ in range(warmup):
        fn()
    
    if device == 'cuda':
        torch.cuda.synchronize()
    
    start = time.perf_counter()
    for _ in range(iterations):
        fn()
    if device == 'cuda':
        torch.cuda.synchronize()
    total = time.perf_counter() - start
    
    return (total / iterations) * 1000


# ============================================================================
# PyTorch Parallel Computation Patterns
# ============================================================================

def pytorch_parallel_branches(inputs: List[torch.Tensor], num_ops: int = 3) -> List[torch.Tensor]:
    """
    PyTorch can potentially parallelize these independent computations.
    
    Each branch is independent - no data dependency between them.
    On GPU, these can run as concurrent CUDA kernels.
    """
    results = []
    for x in inputs:
        result = x
        for _ in range(num_ops):
            result = torch.matmul(result, result.t())
            result = torch.relu(result)
            result = result / (result.norm() + 1e-6)
        results.append(result)
    return results


def pytorch_parallel_then_aggregate(inputs: List[torch.Tensor], num_ops: int = 3) -> torch.Tensor:
    """
    Pattern: Multiple parallel branches -> Aggregation.
    
    This is common in neural networks (e.g., multi-head attention, ensemble models).
    """
    # Independent computations (parallelizable)
    branch_results = pytorch_parallel_branches(inputs, num_ops)
    
    # Aggregate (depends on all branches)
    result = branch_results[0]
    for i in range(1, len(branch_results)):
        result = result + branch_results[i]
    
    return result


# ============================================================================
# Tests: Sequential vs Parallel Execution
# ============================================================================

def test_parallel_branches_cpu():
    """
    Compare PyTorch (potentially parallel) vs Executor (sequential) for independent branches.
    
    Graph structure:
        input_0 -> heavy_compute_0 --|
        input_1 -> heavy_compute_1 --|-> aggregator -> output
        input_2 -> heavy_compute_2 --|
        input_3 -> heavy_compute_3 --|
    
    The 4 heavy_compute nodes are independent and could run in parallel.
    """
    config = ParallelTestConfig()
    device = 'cpu'
    size = config.matrix_size
    num_branches = config.num_parallel_branches
    num_ops = 3
    
    # Create inputs
    torch.manual_seed(42)
    input_tensors = [torch.randn(size, size, device=device) for _ in range(num_branches)]
    
    # === Direct PyTorch (potentially parallel) ===
    def pytorch_fn():
        return pytorch_parallel_then_aggregate(input_tensors, num_ops)
    
    # === Executor (sequential) ===
    input_nodes = []
    compute_nodes = []
    
    for i in range(num_branches):
        inp = TensorInputNode(f"input_{i}", (size, size), device)
        inp.set_tensor(input_tensors[i])
        input_nodes.append(inp)
        
        compute = HeavyComputeRetargeter(f"compute_{i}", size, num_ops, device)
        compute.connect([inp.output()])
        compute_nodes.append(compute)
    
    aggregator = AggregatorRetargeter("aggregator", size, num_branches, device)
    aggregator.connect([node.output(0) for node in compute_nodes])
    
    executor = RetargeterExecutor([aggregator])
    
    def executor_fn():
        executor.execute()
        return executor.get_output(aggregator, 0)[0]
    
    # Verify correctness
    pytorch_result = pytorch_fn()
    executor_result = executor_fn()
    assert torch.allclose(pytorch_result, executor_result, rtol=1e-4, atol=1e-4), \
        "Results don't match!"
    
    # Benchmark
    pytorch_ms = benchmark_fn(pytorch_fn, config.warmup_iterations, config.benchmark_iterations, device)
    executor_ms = benchmark_fn(executor_fn, config.warmup_iterations, config.benchmark_iterations, device)
    
    print(f"\n{'='*60}")
    print(f"Parallel Branches Test (CPU)")
    print(f"  Branches: {num_branches}, Matrix: {size}x{size}, Ops/branch: {num_ops}")
    print(f"{'='*60}")
    print(f"  PyTorch (potentially parallel): {pytorch_ms:.3f}ms")
    print(f"  Executor (sequential):          {executor_ms:.3f}ms")
    print(f"  Difference:                     {executor_ms - pytorch_ms:.3f}ms ({((executor_ms/pytorch_ms)-1)*100:.1f}%)")
    
    # Note: On CPU, the difference may be small because:
    # 1. Python loop overhead dominates
    # 2. BLAS libraries may already use all cores for each matmul


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
def test_parallel_branches_gpu():
    """
    Compare PyTorch vs Executor for parallel branches on GPU.
    
    GPU is where parallelism really matters - CUDA can run independent kernels concurrently.
    """
    config = ParallelTestConfig()
    device = 'cuda'
    size = config.matrix_size
    num_branches = config.num_parallel_branches
    num_ops = 3
    
    torch.manual_seed(42)
    input_tensors = [torch.randn(size, size, device=device) for _ in range(num_branches)]
    
    # === Direct PyTorch ===
    def pytorch_fn():
        return pytorch_parallel_then_aggregate(input_tensors, num_ops)
    
    # === Executor ===
    input_nodes = []
    compute_nodes = []
    
    for i in range(num_branches):
        inp = TensorInputNode(f"input_{i}", (size, size), device)
        inp.set_tensor(input_tensors[i])
        input_nodes.append(inp)
        
        compute = HeavyComputeRetargeter(f"compute_{i}", size, num_ops, device)
        compute.connect([inp.output()])
        compute_nodes.append(compute)
    
    aggregator = AggregatorRetargeter("aggregator", size, num_branches, device)
    aggregator.connect([node.output(0) for node in compute_nodes])
    
    executor = RetargeterExecutor([aggregator])
    
    def executor_fn():
        executor.execute()
        return executor.get_output(aggregator, 0)[0]
    
    # Verify correctness
    pytorch_result = pytorch_fn()
    executor_result = executor_fn()
    assert torch.allclose(pytorch_result, executor_result, rtol=1e-4, atol=1e-4)
    
    # Benchmark
    pytorch_ms = benchmark_fn(pytorch_fn, config.warmup_iterations, config.benchmark_iterations, device)
    executor_ms = benchmark_fn(executor_fn, config.warmup_iterations, config.benchmark_iterations, device)
    
    print(f"\n{'='*60}")
    print(f"Parallel Branches Test (GPU)")
    print(f"  Branches: {num_branches}, Matrix: {size}x{size}, Ops/branch: {num_ops}")
    print(f"{'='*60}")
    print(f"  PyTorch (potentially parallel): {pytorch_ms:.3f}ms")
    print(f"  Executor (sequential):          {executor_ms:.3f}ms")
    print(f"  Difference:                     {executor_ms - pytorch_ms:.3f}ms ({((executor_ms/pytorch_ms)-1)*100:.1f}%)")


def test_scaling_with_branches_cpu():
    """
    Test how performance scales with number of independent branches.
    
    As branches increase, the gap between parallel and sequential should grow.
    """
    device = 'cpu'
    size = 256  # Smaller for faster test
    num_ops = 2
    branch_counts = [1, 2, 4, 8]
    
    print(f"\n{'='*60}")
    print(f"Scaling with Branch Count (CPU)")
    print(f"  Matrix: {size}x{size}, Ops/branch: {num_ops}")
    print(f"{'='*60}")
    
    results = []
    
    for num_branches in branch_counts:
        torch.manual_seed(42)
        input_tensors = [torch.randn(size, size, device=device) for _ in range(num_branches)]
        
        # PyTorch
        def pytorch_fn():
            return pytorch_parallel_then_aggregate(input_tensors, num_ops)
        
        # Executor
        input_nodes = []
        compute_nodes = []
        
        for i in range(num_branches):
            inp = TensorInputNode(f"input_{i}", (size, size), device)
            inp.set_tensor(input_tensors[i])
            input_nodes.append(inp)
            
            compute = HeavyComputeRetargeter(f"compute_{i}", size, num_ops, device)
            compute.connect([inp.output()])
            compute_nodes.append(compute)
        
        aggregator = AggregatorRetargeter("aggregator", size, num_branches, device)
        aggregator.connect([node.output(0) for node in compute_nodes])
        
        executor = RetargeterExecutor([aggregator])
        
        def executor_fn():
            executor.execute()
        
        pytorch_ms = benchmark_fn(pytorch_fn, 3, 20, device)
        executor_ms = benchmark_fn(executor_fn, 3, 20, device)
        
        diff_pct = ((executor_ms / pytorch_ms) - 1) * 100
        results.append((num_branches, pytorch_ms, executor_ms, diff_pct))
        
        print(f"  {num_branches} branches: PyTorch={pytorch_ms:.2f}ms, Executor={executor_ms:.2f}ms, Diff={diff_pct:+.1f}%")
    
    # Both should scale roughly linearly since CPU BLAS typically uses all cores per op
    print(f"\n  Note: On CPU, both scale similarly because BLAS uses all cores per operation")


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
def test_scaling_with_branches_gpu():
    """
    Test how performance scales with number of independent branches on GPU.
    
    GPU should show more benefit from parallelism as branches increase.
    """
    device = 'cuda'
    size = 512
    num_ops = 3
    branch_counts = [1, 2, 4, 8]
    
    print(f"\n{'='*60}")
    print(f"Scaling with Branch Count (GPU)")
    print(f"  Matrix: {size}x{size}, Ops/branch: {num_ops}")
    print(f"{'='*60}")
    
    for num_branches in branch_counts:
        torch.manual_seed(42)
        input_tensors = [torch.randn(size, size, device=device) for _ in range(num_branches)]
        
        def pytorch_fn():
            return pytorch_parallel_then_aggregate(input_tensors, num_ops)
        
        input_nodes = []
        compute_nodes = []
        
        for i in range(num_branches):
            inp = TensorInputNode(f"input_{i}", (size, size), device)
            inp.set_tensor(input_tensors[i])
            input_nodes.append(inp)
            
            compute = HeavyComputeRetargeter(f"compute_{i}", size, num_ops, device)
            compute.connect([inp.output()])
            compute_nodes.append(compute)
        
        aggregator = AggregatorRetargeter("aggregator", size, num_branches, device)
        aggregator.connect([node.output(0) for node in compute_nodes])
        
        executor = RetargeterExecutor([aggregator])
        
        def executor_fn():
            executor.execute()
        
        pytorch_ms = benchmark_fn(pytorch_fn, 5, 30, device)
        executor_ms = benchmark_fn(executor_fn, 5, 30, device)
        
        diff_pct = ((executor_ms / pytorch_ms) - 1) * 100
        print(f"  {num_branches} branches: PyTorch={pytorch_ms:.2f}ms, Executor={executor_ms:.2f}ms, Diff={diff_pct:+.1f}%")


def test_wide_parallel_layer():
    """
    Test a "wide" layer pattern common in neural networks.
    
    Pattern: Single input -> Many parallel transforms -> Concatenate
    This is like multi-head attention or a wide residual block.
    """
    device = 'cpu'
    size = 256
    num_heads = 8
    num_ops = 2
    
    torch.manual_seed(42)
    shared_input = torch.randn(size, size, device=device)
    
    # === PyTorch: Define computation that could run in parallel ===
    def pytorch_wide_layer():
        heads = []
        for i in range(num_heads):
            # Each head does independent computation
            result = shared_input
            for _ in range(num_ops):
                # Simulate head-specific transform
                result = torch.matmul(result, result.t())
                result = torch.relu(result)
                result = result / (result.norm() + 1e-6)
            heads.append(result)
        
        # Concatenate heads (or sum for simplicity)
        output = sum(heads)
        return output
    
    # === Executor: Sequential execution ===
    input_node = TensorInputNode("shared_input", (size, size), device)
    input_node.set_tensor(shared_input)
    
    head_nodes = []
    for i in range(num_heads):
        head = HeavyComputeRetargeter(f"head_{i}", size, num_ops, device)
        head.connect([input_node.output()])
        head_nodes.append(head)
    
    aggregator = AggregatorRetargeter("concat", size, num_heads, device)
    aggregator.connect([node.output(0) for node in head_nodes])
    
    executor = RetargeterExecutor([aggregator])
    
    def executor_fn():
        executor.execute()
        return executor.get_output(aggregator, 0)[0]
    
    # Verify
    pytorch_result = pytorch_wide_layer()
    executor_result = executor_fn()
    assert torch.allclose(pytorch_result, executor_result, rtol=1e-4, atol=1e-4)
    
    # Benchmark
    pytorch_ms = benchmark_fn(pytorch_wide_layer, 5, 30, device)
    executor_ms = benchmark_fn(executor_fn, 5, 30, device)
    
    print(f"\n{'='*60}")
    print(f"Wide Layer Test (like Multi-Head Attention)")
    print(f"  Heads: {num_heads}, Matrix: {size}x{size}")
    print(f"{'='*60}")
    print(f"  PyTorch:  {pytorch_ms:.3f}ms")
    print(f"  Executor: {executor_ms:.3f}ms")
    print(f"  Difference: {executor_ms - pytorch_ms:.3f}ms ({((executor_ms/pytorch_ms)-1)*100:.1f}%)")


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
def test_cuda_streams_comparison():
    """
    Demonstrate CUDA stream parallelism vs sequential execution.
    
    This explicitly uses CUDA streams to show what true GPU parallelism looks like,
    compared to our executor which doesn't use streams.
    """
    device = 'cuda'
    size = 512
    num_branches = 4
    num_ops = 3
    
    torch.manual_seed(42)
    input_tensors = [torch.randn(size, size, device=device) for _ in range(num_branches)]
    
    # Pre-allocate outputs
    outputs = [torch.empty(size, size, device=device) for _ in range(num_branches)]
    
    def compute_branch(x: torch.Tensor, out: torch.Tensor) -> None:
        """Heavy computation for one branch."""
        result = x
        for _ in range(num_ops):
            result = torch.matmul(result, result.t())
            result = torch.relu(result)
            result = result / (result.norm() + 1e-6)
        out.copy_(result)
    
    # === Sequential (default CUDA stream) ===
    def sequential_cuda():
        for i in range(num_branches):
            compute_branch(input_tensors[i], outputs[i])
        return sum(outputs)
    
    # === Parallel with CUDA streams ===
    streams = [torch.cuda.Stream() for _ in range(num_branches)]
    
    def parallel_cuda_streams():
        # Launch each branch on its own stream
        for i in range(num_branches):
            with torch.cuda.stream(streams[i]):
                compute_branch(input_tensors[i], outputs[i])
        
        # Synchronize all streams
        for stream in streams:
            stream.synchronize()
        
        return sum(outputs)
    
    # Verify correctness
    seq_result = sequential_cuda()
    par_result = parallel_cuda_streams()
    assert torch.allclose(seq_result, par_result, rtol=1e-4, atol=1e-4)
    
    # Benchmark
    seq_ms = benchmark_fn(sequential_cuda, 5, 30, device)
    par_ms = benchmark_fn(parallel_cuda_streams, 5, 30, device)
    
    print(f"\n{'='*60}")
    print(f"CUDA Streams Comparison")
    print(f"  Branches: {num_branches}, Matrix: {size}x{size}")
    print(f"{'='*60}")
    print(f"  Sequential (single stream): {seq_ms:.3f}ms")
    print(f"  Parallel (multi-stream):    {par_ms:.3f}ms")
    print(f"  Speedup:                    {seq_ms/par_ms:.2f}x")
    print(f"\n  Note: Our executor currently uses sequential execution like the 'single stream' case.")
    print(f"  A parallel executor could use CUDA streams to achieve the 'multi-stream' performance.")


def test_executor_identifies_parallel_nodes():
    """
    Verify that our executor's topological sort correctly identifies
    nodes that could run in parallel (same depth level).
    
    This is informational - shows which nodes COULD be parallelized.
    """
    device = 'cpu'
    size = 64
    num_branches = 4
    
    # Create graph
    input_node = TensorInputNode("input", (size, size), device)
    input_node.set_tensor(torch.randn(size, size))
    
    parallel_nodes = []
    for i in range(num_branches):
        node = HeavyComputeRetargeter(f"parallel_{i}", size, 1, device)
        node.connect([input_node.output()])
        parallel_nodes.append(node)
    
    aggregator = AggregatorRetargeter("aggregator", size, num_branches, device)
    aggregator.connect([node.output(0) for node in parallel_nodes])
    
    executor = RetargeterExecutor([aggregator])
    
    # Analyze execution order
    print(f"\n{'='*60}")
    print(f"Executor Node Analysis")
    print(f"{'='*60}")
    print(f"  Total nodes: {executor.num_nodes}")
    print(f"  Execution order:")
    
    for i, node in enumerate(executor._execution_order):
        deps = executor._dependencies.get(node, set())
        dep_names = [d._name if hasattr(d, '_name') else d.__class__.__name__ for d in deps]
        print(f"    {i+1}. {node._name if hasattr(node, '_name') else node.__class__.__name__}")
        print(f"       Dependencies: {dep_names}")
    
    # The parallel_nodes all depend only on input_node
    # They appear consecutively in execution order and could run in parallel
    print(f"\n  Nodes that could run in parallel:")
    parallel_node_names = [n._name for n in parallel_nodes]
    print(f"    {parallel_node_names}")
    print(f"\n  Currently, executor runs these sequentially.")
    print(f"  A parallel executor could run them concurrently.")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

