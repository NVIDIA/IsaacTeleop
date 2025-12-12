"""
Performance comparison tests: Direct PyTorch vs Executor Engine.

Compares execution time of complex math operations when run:
1. Directly with PyTorch
2. Through the RetargeterExecutor engine

This helps quantify the overhead of the executor abstraction.
"""

import pytest
import time
import numpy as np
import torch
from typing import List, Optional, Tuple
from dataclasses import dataclass
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
# Performance Test Configuration
# ============================================================================

@dataclass
class PerfTestConfig:
    """Configuration for performance tests."""
    warmup_iterations: int = 10
    benchmark_iterations: int = 100
    matrix_sizes: Tuple[int, ...] = (64, 128, 256, 512)


# ============================================================================
# Complex Math Operations (Direct PyTorch)
# ============================================================================

def direct_pytorch_mlp_forward(
    x: torch.Tensor,
    w1: torch.Tensor,
    b1: torch.Tensor,
    w2: torch.Tensor,
    b2: torch.Tensor,
    w3: torch.Tensor,
    b3: torch.Tensor,
) -> torch.Tensor:
    """
    Direct PyTorch MLP forward pass: 3-layer neural network.
    
    Operations: Linear -> ReLU -> Linear -> ReLU -> Linear -> Sigmoid
    """
    # Layer 1
    h1 = torch.matmul(x, w1) + b1
    h1 = torch.relu(h1)
    
    # Layer 2
    h2 = torch.matmul(h1, w2) + b2
    h2 = torch.relu(h2)
    
    # Layer 3
    out = torch.matmul(h2, w3) + b3
    out = torch.sigmoid(out)
    
    return out


def direct_pytorch_attention(
    q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    scale: float,
) -> torch.Tensor:
    """
    Direct PyTorch scaled dot-product attention.
    
    Operations: Q @ K^T -> Scale -> Softmax -> @ V
    """
    # Compute attention scores
    scores = torch.matmul(q, k.transpose(-2, -1)) * scale
    
    # Apply softmax
    attention_weights = torch.softmax(scores, dim=-1)
    
    # Apply attention to values
    output = torch.matmul(attention_weights, v)
    
    return output


def direct_pytorch_complex_transform(
    x: torch.Tensor,
    rotation: torch.Tensor,
    scale: torch.Tensor,
    translation: torch.Tensor,
) -> torch.Tensor:
    """
    Direct PyTorch complex geometric transformation.
    
    Operations: Normalize -> Rotate -> Scale -> Translate -> Activate
    """
    # Normalize input
    mean = x.mean(dim=-1, keepdim=True)
    std = x.std(dim=-1, keepdim=True) + 1e-6
    x_norm = (x - mean) / std
    
    # Apply rotation
    x_rot = torch.matmul(x_norm, rotation)
    
    # Apply scale
    x_scaled = x_rot * scale
    
    # Apply translation
    x_trans = x_scaled + translation
    
    # Apply activation (tanh)
    output = torch.tanh(x_trans)
    
    return output


# ============================================================================
# Executor-based Implementations (Retargeter Nodes)
# ============================================================================

class TensorInputNode(InputNode):
    """Generic tensor input node for performance tests."""
    
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


class LinearLayerRetargeter(RetargeterNode):
    """Linear layer: out = x @ w + b, followed by optional activation."""
    
    def __init__(self, name: str, batch_size: int, in_features: int, out_features: int, 
                 activation: str = 'none', device: str = 'cpu'):
        self._batch_size = batch_size
        self._in_features = in_features
        self._out_features = out_features
        self._activation = activation
        self._device = device
        super().__init__(name=name)
    
    def _define_inputs(self) -> List[TensorCollection]:
        return [
            TensorCollection("input", [
                PyTorchTensorType("x", dtype=torch.float32, shape=(self._batch_size, self._in_features), device=self._device)
            ]),
            TensorCollection("weight", [
                PyTorchTensorType("w", dtype=torch.float32, shape=(self._in_features, self._out_features), device=self._device)
            ]),
            TensorCollection("bias", [
                PyTorchTensorType("b", dtype=torch.float32, shape=(self._out_features,), device=self._device)
            ]),
        ]
    
    def _define_outputs(self) -> List[TensorCollection]:
        return [TensorCollection("output", [
            PyTorchTensorType("out", dtype=torch.float32, shape=(self._batch_size, self._out_features), device=self._device)
        ])]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup], 
                output_mask: Optional[List[bool]] = None) -> None:
        x = inputs[0][0]
        w = inputs[1][0]
        b = inputs[2][0]
        
        out = torch.matmul(x, w) + b
        
        if self._activation == 'relu':
            out = torch.relu(out)
        elif self._activation == 'sigmoid':
            out = torch.sigmoid(out)
        elif self._activation == 'tanh':
            out = torch.tanh(out)
        
        outputs[0][0] = out


class AttentionRetargeter(RetargeterNode):
    """Scaled dot-product attention."""
    
    def __init__(self, name: str, seq_len: int, d_model: int, device: str = 'cpu'):
        self._seq_len = seq_len
        self._d_model = d_model
        self._device = device
        self._scale = 1.0 / (d_model ** 0.5)
        super().__init__(name=name)
    
    def _define_inputs(self) -> List[TensorCollection]:
        shape = (self._seq_len, self._d_model)
        return [
            TensorCollection("query", [PyTorchTensorType("q", dtype=torch.float32, shape=shape, device=self._device)]),
            TensorCollection("key", [PyTorchTensorType("k", dtype=torch.float32, shape=shape, device=self._device)]),
            TensorCollection("value", [PyTorchTensorType("v", dtype=torch.float32, shape=shape, device=self._device)]),
        ]
    
    def _define_outputs(self) -> List[TensorCollection]:
        return [TensorCollection("output", [
            PyTorchTensorType("attention_out", dtype=torch.float32, 
                            shape=(self._seq_len, self._d_model), device=self._device)
        ])]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup],
                output_mask: Optional[List[bool]] = None) -> None:
        q = inputs[0][0]
        k = inputs[1][0]
        v = inputs[2][0]
        
        scores = torch.matmul(q, k.transpose(-2, -1)) * self._scale
        attention_weights = torch.softmax(scores, dim=-1)
        output = torch.matmul(attention_weights, v)
        
        outputs[0][0] = output


class NormalizeRetargeter(RetargeterNode):
    """Layer normalization."""
    
    def __init__(self, name: str, shape: tuple, device: str = 'cpu'):
        self._shape = shape
        self._device = device
        super().__init__(name=name)
    
    def _define_inputs(self) -> List[TensorCollection]:
        return [TensorCollection("input", [
            PyTorchTensorType("x", dtype=torch.float32, shape=self._shape, device=self._device)
        ])]
    
    def _define_outputs(self) -> List[TensorCollection]:
        return [TensorCollection("output", [
            PyTorchTensorType("normalized", dtype=torch.float32, shape=self._shape, device=self._device)
        ])]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup],
                output_mask: Optional[List[bool]] = None) -> None:
        x = inputs[0][0]
        mean = x.mean(dim=-1, keepdim=True)
        std = x.std(dim=-1, keepdim=True) + 1e-6
        outputs[0][0] = (x - mean) / std


class TransformRetargeter(RetargeterNode):
    """Geometric transformation: rotate, scale, translate."""
    
    def __init__(self, name: str, shape: tuple, device: str = 'cpu'):
        self._shape = shape
        self._device = device
        super().__init__(name=name)
    
    def _define_inputs(self) -> List[TensorCollection]:
        dim = self._shape[-1]
        return [
            TensorCollection("input", [PyTorchTensorType("x", dtype=torch.float32, shape=self._shape, device=self._device)]),
            TensorCollection("rotation", [PyTorchTensorType("rot", dtype=torch.float32, shape=(dim, dim), device=self._device)]),
            TensorCollection("scale", [PyTorchTensorType("scl", dtype=torch.float32, shape=(dim,), device=self._device)]),
            TensorCollection("translation", [PyTorchTensorType("trans", dtype=torch.float32, shape=(dim,), device=self._device)]),
        ]
    
    def _define_outputs(self) -> List[TensorCollection]:
        return [TensorCollection("output", [
            PyTorchTensorType("transformed", dtype=torch.float32, shape=self._shape, device=self._device)
        ])]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup],
                output_mask: Optional[List[bool]] = None) -> None:
        x = inputs[0][0]
        rotation = inputs[1][0]
        scale = inputs[2][0]
        translation = inputs[3][0]
        
        x_rot = torch.matmul(x, rotation)
        x_scaled = x_rot * scale
        x_trans = x_scaled + translation
        outputs[0][0] = torch.tanh(x_trans)


# ============================================================================
# Benchmark Utilities
# ============================================================================

@dataclass
class BenchmarkResult:
    """Results from a benchmark run."""
    name: str
    direct_time_ms: float
    executor_time_ms: float
    overhead_ms: float
    overhead_percent: float
    iterations: int
    
    def __str__(self) -> str:
        return (f"{self.name}: Direct={self.direct_time_ms:.3f}ms, "
                f"Executor={self.executor_time_ms:.3f}ms, "
                f"Overhead={self.overhead_ms:.3f}ms ({self.overhead_percent:.1f}%)")


def benchmark_operation(
    direct_fn,
    executor: RetargeterExecutor,
    output_node: RetargeterNode,
    warmup: int = 10,
    iterations: int = 100,
    device: str = 'cpu',
) -> Tuple[float, float]:
    """
    Benchmark direct PyTorch vs executor execution.
    
    Returns:
        Tuple of (direct_time_ms, executor_time_ms) per iteration
    """
    # Warmup
    for _ in range(warmup):
        direct_fn()
        executor.execute()
    
    # Sync for GPU
    if device == 'cuda':
        torch.cuda.synchronize()
    
    # Benchmark direct
    start = time.perf_counter()
    for _ in range(iterations):
        direct_fn()
    if device == 'cuda':
        torch.cuda.synchronize()
    direct_total = time.perf_counter() - start
    
    # Benchmark executor
    start = time.perf_counter()
    for _ in range(iterations):
        executor.execute()
    if device == 'cuda':
        torch.cuda.synchronize()
    executor_total = time.perf_counter() - start
    
    direct_per_iter_ms = (direct_total / iterations) * 1000
    executor_per_iter_ms = (executor_total / iterations) * 1000
    
    return direct_per_iter_ms, executor_per_iter_ms


# ============================================================================
# Performance Comparison Tests
# ============================================================================

def test_perf_mlp_forward_cpu():
    """
    Performance comparison: 3-layer MLP forward pass on CPU.
    
    Tests a typical neural network forward pass pattern.
    """
    batch_size = 64
    input_dim = 256
    hidden_dim = 512
    output_dim = 128
    device = 'cpu'
    config = PerfTestConfig()
    
    # Create weights and biases
    torch.manual_seed(42)
    x = torch.randn(batch_size, input_dim, device=device)
    w1 = torch.randn(input_dim, hidden_dim, device=device)
    b1 = torch.randn(hidden_dim, device=device)
    w2 = torch.randn(hidden_dim, hidden_dim, device=device)
    b2 = torch.randn(hidden_dim, device=device)
    w3 = torch.randn(hidden_dim, output_dim, device=device)
    b3 = torch.randn(output_dim, device=device)
    
    # Direct PyTorch function
    def direct_fn():
        return direct_pytorch_mlp_forward(x, w1, b1, w2, b2, w3, b3)
    
    # Build executor graph
    input_x = TensorInputNode("x", (batch_size, input_dim), device)
    input_w1 = TensorInputNode("w1", (input_dim, hidden_dim), device)
    input_b1 = TensorInputNode("b1", (hidden_dim,), device)
    input_w2 = TensorInputNode("w2", (hidden_dim, hidden_dim), device)
    input_b2 = TensorInputNode("b2", (hidden_dim,), device)
    input_w3 = TensorInputNode("w3", (hidden_dim, output_dim), device)
    input_b3 = TensorInputNode("b3", (output_dim,), device)
    
    input_x.set_tensor(x)
    input_w1.set_tensor(w1)
    input_b1.set_tensor(b1)
    input_w2.set_tensor(w2)
    input_b2.set_tensor(b2)
    input_w3.set_tensor(w3)
    input_b3.set_tensor(b3)
    
    # Layer 1
    layer1 = LinearLayerRetargeter("layer1", batch_size, input_dim, hidden_dim, 'relu', device)
    layer1.connect([input_x.output(), input_w1.output(), input_b1.output()])
    
    # Layer 2
    layer2 = LinearLayerRetargeter("layer2", batch_size, hidden_dim, hidden_dim, 'relu', device)
    layer2.connect([layer1.output(0), input_w2.output(), input_b2.output()])
    
    # Layer 3
    layer3 = LinearLayerRetargeter("layer3", batch_size, hidden_dim, output_dim, 'sigmoid', device)
    layer3.connect([layer2.output(0), input_w3.output(), input_b3.output()])
    
    executor = RetargeterExecutor([layer3])
    
    # Verify correctness first
    direct_result = direct_fn()
    executor.execute()
    executor_result = executor.get_output(layer3, 0)[0]
    assert torch.allclose(direct_result, executor_result, rtol=1e-4, atol=1e-4), \
        "Results don't match between direct and executor!"
    
    # Benchmark
    direct_ms, executor_ms = benchmark_operation(
        direct_fn, executor, layer3,
        warmup=config.warmup_iterations,
        iterations=config.benchmark_iterations,
        device=device
    )
    
    overhead_ms = executor_ms - direct_ms
    overhead_pct = (overhead_ms / direct_ms) * 100 if direct_ms > 0 else 0
    
    result = BenchmarkResult(
        name="MLP Forward (CPU)",
        direct_time_ms=direct_ms,
        executor_time_ms=executor_ms,
        overhead_ms=overhead_ms,
        overhead_percent=overhead_pct,
        iterations=config.benchmark_iterations
    )
    
    print(f"\n{result}")
    
    # Performance tests are informational - we verify correctness above
    # The overhead shows the cost of the executor abstraction


def test_perf_attention_cpu():
    """
    Performance comparison: Scaled dot-product attention on CPU.
    
    Tests the core attention mechanism used in transformers.
    """
    seq_len = 64
    d_model = 128
    device = 'cpu'
    config = PerfTestConfig()
    
    torch.manual_seed(42)
    q = torch.randn(seq_len, d_model, device=device)
    k = torch.randn(seq_len, d_model, device=device)
    v = torch.randn(seq_len, d_model, device=device)
    scale = 1.0 / (d_model ** 0.5)
    
    # Direct function
    def direct_fn():
        return direct_pytorch_attention(q, k, v, scale)
    
    # Executor graph
    input_q = TensorInputNode("q", (seq_len, d_model), device)
    input_k = TensorInputNode("k", (seq_len, d_model), device)
    input_v = TensorInputNode("v", (seq_len, d_model), device)
    input_q.set_tensor(q)
    input_k.set_tensor(k)
    input_v.set_tensor(v)
    
    attention = AttentionRetargeter("attention", seq_len, d_model, device)
    attention.connect([input_q.output(), input_k.output(), input_v.output()])
    
    executor = RetargeterExecutor([attention])
    
    # Verify correctness
    direct_result = direct_fn()
    executor.execute()
    executor_result = executor.get_output(attention, 0)[0]
    assert torch.allclose(direct_result, executor_result, rtol=1e-4, atol=1e-4)
    
    # Benchmark
    direct_ms, executor_ms = benchmark_operation(
        direct_fn, executor, attention,
        warmup=config.warmup_iterations,
        iterations=config.benchmark_iterations,
        device=device
    )
    
    overhead_ms = executor_ms - direct_ms
    overhead_pct = (overhead_ms / direct_ms) * 100 if direct_ms > 0 else 0
    
    result = BenchmarkResult(
        name="Attention (CPU)",
        direct_time_ms=direct_ms,
        executor_time_ms=executor_ms,
        overhead_ms=overhead_ms,
        overhead_percent=overhead_pct,
        iterations=config.benchmark_iterations
    )
    
    print(f"\n{result}")


def test_perf_transform_cpu():
    """
    Performance comparison: Complex geometric transformation on CPU.
    
    Tests normalize -> rotate -> scale -> translate -> activate.
    """
    batch_size = 128
    dim = 64
    device = 'cpu'
    config = PerfTestConfig()
    
    torch.manual_seed(42)
    x = torch.randn(batch_size, dim, device=device)
    rotation = torch.randn(dim, dim, device=device)
    scale = torch.randn(dim, device=device)
    translation = torch.randn(dim, device=device)
    
    # Direct function
    def direct_fn():
        return direct_pytorch_complex_transform(x, rotation, scale, translation)
    
    # Executor graph - split into normalize + transform
    input_x = TensorInputNode("x", (batch_size, dim), device)
    input_rot = TensorInputNode("rotation", (dim, dim), device)
    input_scale = TensorInputNode("scale", (dim,), device)
    input_trans = TensorInputNode("translation", (dim,), device)
    
    input_x.set_tensor(x)
    input_rot.set_tensor(rotation)
    input_scale.set_tensor(scale)
    input_trans.set_tensor(translation)
    
    normalize = NormalizeRetargeter("normalize", (batch_size, dim), device)
    normalize.connect([input_x.output()])
    
    transform = TransformRetargeter("transform", (batch_size, dim), device)
    transform.connect([normalize.output(0), input_rot.output(), input_scale.output(), input_trans.output()])
    
    executor = RetargeterExecutor([transform])
    
    # Verify correctness
    direct_result = direct_fn()
    executor.execute()
    executor_result = executor.get_output(transform, 0)[0]
    assert torch.allclose(direct_result, executor_result, rtol=1e-4, atol=1e-4)
    
    # Benchmark
    direct_ms, executor_ms = benchmark_operation(
        direct_fn, executor, transform,
        warmup=config.warmup_iterations,
        iterations=config.benchmark_iterations,
        device=device
    )
    
    overhead_ms = executor_ms - direct_ms
    overhead_pct = (overhead_ms / direct_ms) * 100 if direct_ms > 0 else 0
    
    result = BenchmarkResult(
        name="Transform (CPU)",
        direct_time_ms=direct_ms,
        executor_time_ms=executor_ms,
        overhead_ms=overhead_ms,
        overhead_percent=overhead_pct,
        iterations=config.benchmark_iterations
    )
    
    print(f"\n{result}")


# ============================================================================
# GPU Performance Tests
# ============================================================================

@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
def test_perf_mlp_forward_gpu():
    """
    Performance comparison: 3-layer MLP forward pass on GPU.
    
    GPU tests are particularly interesting as the executor overhead
    becomes relatively smaller compared to GPU kernel launch costs.
    """
    batch_size = 256
    input_dim = 512
    hidden_dim = 1024
    output_dim = 256
    device = 'cuda'
    config = PerfTestConfig()
    
    torch.manual_seed(42)
    x = torch.randn(batch_size, input_dim, device=device)
    w1 = torch.randn(input_dim, hidden_dim, device=device)
    b1 = torch.randn(hidden_dim, device=device)
    w2 = torch.randn(hidden_dim, hidden_dim, device=device)
    b2 = torch.randn(hidden_dim, device=device)
    w3 = torch.randn(hidden_dim, output_dim, device=device)
    b3 = torch.randn(output_dim, device=device)
    
    def direct_fn():
        return direct_pytorch_mlp_forward(x, w1, b1, w2, b2, w3, b3)
    
    # Build executor graph
    input_x = TensorInputNode("x", (batch_size, input_dim), device)
    input_w1 = TensorInputNode("w1", (input_dim, hidden_dim), device)
    input_b1 = TensorInputNode("b1", (hidden_dim,), device)
    input_w2 = TensorInputNode("w2", (hidden_dim, hidden_dim), device)
    input_b2 = TensorInputNode("b2", (hidden_dim,), device)
    input_w3 = TensorInputNode("w3", (hidden_dim, output_dim), device)
    input_b3 = TensorInputNode("b3", (output_dim,), device)
    
    input_x.set_tensor(x)
    input_w1.set_tensor(w1)
    input_b1.set_tensor(b1)
    input_w2.set_tensor(w2)
    input_b2.set_tensor(b2)
    input_w3.set_tensor(w3)
    input_b3.set_tensor(b3)
    
    layer1 = LinearLayerRetargeter("layer1", batch_size, input_dim, hidden_dim, 'relu', device)
    layer1.connect([input_x.output(), input_w1.output(), input_b1.output()])
    
    layer2 = LinearLayerRetargeter("layer2", batch_size, hidden_dim, hidden_dim, 'relu', device)
    layer2.connect([layer1.output(0), input_w2.output(), input_b2.output()])
    
    layer3 = LinearLayerRetargeter("layer3", batch_size, hidden_dim, output_dim, 'sigmoid', device)
    layer3.connect([layer2.output(0), input_w3.output(), input_b3.output()])
    
    executor = RetargeterExecutor([layer3])
    
    # Verify correctness
    direct_result = direct_fn()
    executor.execute()
    executor_result = executor.get_output(layer3, 0)[0]
    assert torch.allclose(direct_result, executor_result, rtol=1e-4, atol=1e-4)
    
    # Benchmark
    direct_ms, executor_ms = benchmark_operation(
        direct_fn, executor, layer3,
        warmup=config.warmup_iterations,
        iterations=config.benchmark_iterations,
        device=device
    )
    
    overhead_ms = executor_ms - direct_ms
    overhead_pct = (overhead_ms / direct_ms) * 100 if direct_ms > 0 else 0
    
    result = BenchmarkResult(
        name="MLP Forward (GPU)",
        direct_time_ms=direct_ms,
        executor_time_ms=executor_ms,
        overhead_ms=overhead_ms,
        overhead_percent=overhead_pct,
        iterations=config.benchmark_iterations
    )
    
    print(f"\n{result}")


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
def test_perf_attention_gpu():
    """Performance comparison: Attention mechanism on GPU."""
    seq_len = 128
    d_model = 256
    device = 'cuda'
    config = PerfTestConfig()
    
    torch.manual_seed(42)
    q = torch.randn(seq_len, d_model, device=device)
    k = torch.randn(seq_len, d_model, device=device)
    v = torch.randn(seq_len, d_model, device=device)
    scale = 1.0 / (d_model ** 0.5)
    
    def direct_fn():
        return direct_pytorch_attention(q, k, v, scale)
    
    input_q = TensorInputNode("q", (seq_len, d_model), device)
    input_k = TensorInputNode("k", (seq_len, d_model), device)
    input_v = TensorInputNode("v", (seq_len, d_model), device)
    input_q.set_tensor(q)
    input_k.set_tensor(k)
    input_v.set_tensor(v)
    
    attention = AttentionRetargeter("attention", seq_len, d_model, device)
    attention.connect([input_q.output(), input_k.output(), input_v.output()])
    
    executor = RetargeterExecutor([attention])
    
    # Verify correctness
    direct_result = direct_fn()
    executor.execute()
    executor_result = executor.get_output(attention, 0)[0]
    assert torch.allclose(direct_result, executor_result, rtol=1e-4, atol=1e-4)
    
    # Benchmark
    direct_ms, executor_ms = benchmark_operation(
        direct_fn, executor, attention,
        warmup=config.warmup_iterations,
        iterations=config.benchmark_iterations,
        device=device
    )
    
    overhead_ms = executor_ms - direct_ms
    overhead_pct = (overhead_ms / direct_ms) * 100 if direct_ms > 0 else 0
    
    result = BenchmarkResult(
        name="Attention (GPU)",
        direct_time_ms=direct_ms,
        executor_time_ms=executor_ms,
        overhead_ms=overhead_ms,
        overhead_percent=overhead_pct,
        iterations=config.benchmark_iterations
    )
    
    print(f"\n{result}")


# ============================================================================
# Scaling Tests
# ============================================================================

def test_perf_scaling_with_size():
    """
    Test how overhead scales with matrix size.
    
    This helps understand if the executor overhead is constant or scales
    with computation size (it should be roughly constant).
    """
    device = 'cpu'
    sizes = [32, 64, 128, 256]
    results = []
    
    print("\n" + "=" * 60)
    print("Overhead Scaling with Matrix Size (CPU)")
    print("=" * 60)
    
    for size in sizes:
        torch.manual_seed(42)
        x = torch.randn(size, size, device=device)
        w = torch.randn(size, size, device=device)
        
        def direct_fn():
            return torch.matmul(x, w)
        
        # Simple matmul graph
        input_x = TensorInputNode("x", (size, size), device)
        input_w = TensorInputNode("w", (size, size), device)
        input_x.set_tensor(x)
        input_w.set_tensor(w)
        
        # Create a simple matmul retargeter
        class MatMulRetargeter(RetargeterNode):
            def __init__(self, size, device):
                self._size = size
                self._device = device
                super().__init__(name="matmul")
            
            def _define_inputs(self):
                return [
                    TensorCollection("a", [PyTorchTensorType("a", torch.float32, (self._size, self._size), self._device)]),
                    TensorCollection("b", [PyTorchTensorType("b", torch.float32, (self._size, self._size), self._device)]),
                ]
            
            def _define_outputs(self):
                return [TensorCollection("out", [PyTorchTensorType("out", torch.float32, (self._size, self._size), self._device)])]
            
            def execute(self, inputs, outputs, mask=None):
                outputs[0][0] = torch.matmul(inputs[0][0], inputs[1][0])
        
        matmul = MatMulRetargeter(size, device)
        matmul.connect([input_x.output(), input_w.output()])
        executor = RetargeterExecutor([matmul])
        
        direct_ms, executor_ms = benchmark_operation(
            direct_fn, executor, matmul,
            warmup=10, iterations=50, device=device
        )
        
        overhead_ms = executor_ms - direct_ms
        overhead_pct = (overhead_ms / direct_ms) * 100 if direct_ms > 0 else 0
        
        result = BenchmarkResult(
            name=f"MatMul {size}x{size}",
            direct_time_ms=direct_ms,
            executor_time_ms=executor_ms,
            overhead_ms=overhead_ms,
            overhead_percent=overhead_pct,
            iterations=50
        )
        results.append(result)
        print(f"  {result}")
    
    # Note: Overhead may vary due to system noise, caching, and other factors
    # We just report the results; the test passes if all operations complete successfully
    print(f"\n  Summary: Overhead ranged from {min(r.overhead_ms for r in results):.4f}ms "
          f"to {max(r.overhead_ms for r in results):.4f}ms")


def test_perf_deep_graph():
    """
    Test overhead for a deep graph with many nodes.
    
    Measures if the executor handles many nodes efficiently.
    """
    device = 'cpu'
    size = 64
    num_layers = 10
    
    print("\n" + "=" * 60)
    print(f"Deep Graph Performance ({num_layers} layers, {size}x{size})")
    print("=" * 60)
    
    torch.manual_seed(42)
    x = torch.randn(size, size, device=device)
    
    # Direct: chain of matmuls
    def direct_fn():
        result = x
        for _ in range(num_layers):
            result = torch.relu(torch.matmul(result, result.t()))
        return result
    
    # Executor graph
    input_x = TensorInputNode("x", (size, size), device)
    input_x.set_tensor(x)
    
    class SelfMatMulReLU(RetargeterNode):
        def __init__(self, name, size, device):
            self._size = size
            self._device = device
            super().__init__(name=name)
        
        def _define_inputs(self):
            return [TensorCollection("in", [PyTorchTensorType("x", torch.float32, (self._size, self._size), self._device)])]
        
        def _define_outputs(self):
            return [TensorCollection("out", [PyTorchTensorType("y", torch.float32, (self._size, self._size), self._device)])]
        
        def execute(self, inputs, outputs, mask=None):
            x = inputs[0][0]
            outputs[0][0] = torch.relu(torch.matmul(x, x.t()))
    
    # Build chain
    layers = []
    prev_output = input_x.output()
    for i in range(num_layers):
        layer = SelfMatMulReLU(f"layer_{i}", size, device)
        layer.connect([prev_output])
        layers.append(layer)
        prev_output = layer.output(0)
    
    executor = RetargeterExecutor([layers[-1]])
    
    # Verify correctness
    direct_result = direct_fn()
    executor.execute()
    executor_result = executor.get_output(layers[-1], 0)[0]
    assert torch.allclose(direct_result, executor_result, rtol=1e-3, atol=1e-3)
    
    # Benchmark
    direct_ms, executor_ms = benchmark_operation(
        direct_fn, executor, layers[-1],
        warmup=10, iterations=50, device=device
    )
    
    overhead_ms = executor_ms - direct_ms
    overhead_per_layer_ms = overhead_ms / num_layers
    
    print(f"  Direct: {direct_ms:.3f}ms")
    print(f"  Executor: {executor_ms:.3f}ms")
    print(f"  Total Overhead: {overhead_ms:.3f}ms")
    print(f"  Overhead per layer: {overhead_per_layer_ms:.4f}ms")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

