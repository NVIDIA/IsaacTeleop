"""
Test for RetargeterExecutor with PyTorch and NumPy tensor types.

Tests compute graphs with:
- PyTorch tensors on CPU and GPU
- NumPy arrays
- Mixed tensor types in the same graph
"""

import pytest
import numpy as np
import torch
from typing import List, Optional
from .. import (
    InputNode,
    RetargeterNode,
    TensorCollection,
    TensorGroup,
    NumpyArrayType,
    PyTorchTensorType,
    RetargeterExecutor,
    OutputSelector,
)


# ============================================================================
# PyTorch Input Nodes
# ============================================================================

class PyTorchTensorInputNode(InputNode):
    """Input node that produces a PyTorch tensor."""
    
    def __init__(self, name: str, shape: tuple, device: str = 'cpu', dtype: torch.dtype = torch.float32):
        self._shape = shape
        self._device = device
        self._dtype = dtype
        self._tensor = torch.zeros(shape, dtype=dtype, device=device)
        super().__init__(name)
    
    def _define_outputs(self) -> List[TensorCollection]:
        return [TensorCollection(f"{self._name}_output", [
            PyTorchTensorType(f"{self._name}_tensor", dtype=self._dtype, shape=self._shape, device=self._device)
        ])]
    
    def output(self) -> OutputSelector:
        return OutputSelector(self, 0)
    
    def set_tensor(self, tensor: torch.Tensor) -> None:
        """Set the tensor value."""
        self._tensor = tensor.to(self._device)
    
    def update(self, outputs: List[TensorGroup]) -> None:
        outputs[0][0] = self._tensor


class NumpyArrayInputNode(InputNode):
    """Input node that produces a NumPy array."""
    
    def __init__(self, name: str, shape: tuple, dtype: np.dtype = np.float32):
        self._shape = shape
        self._dtype = dtype
        self._array = np.zeros(shape, dtype=dtype)
        super().__init__(name)
    
    def _define_outputs(self) -> List[TensorCollection]:
        return [TensorCollection(f"{self._name}_output", [
            NumpyArrayType(f"{self._name}_array", dtype=np.dtype(self._dtype), shape=self._shape)
        ])]
    
    def output(self) -> OutputSelector:
        return OutputSelector(self, 0)
    
    def set_array(self, array: np.ndarray) -> None:
        """Set the array value."""
        self._array = array.astype(self._dtype)
    
    def update(self, outputs: List[TensorGroup]) -> None:
        outputs[0][0] = self._array


# ============================================================================
# PyTorch Retargeters
# ============================================================================

class PyTorchMatMulRetargeter(RetargeterNode):
    """Matrix multiplication retargeter using PyTorch: result = a @ b."""
    
    def __init__(self, name: str, shape_a: tuple, shape_b: tuple, device: str = 'cpu'):
        self._shape_a = shape_a
        self._shape_b = shape_b
        self._device = device
        self._output_shape = (shape_a[0], shape_b[1])
        super().__init__(name=name)
    
    def _define_inputs(self) -> List[TensorCollection]:
        return [
            TensorCollection("input_a", [
                PyTorchTensorType("matrix_a", dtype=torch.float32, shape=self._shape_a, device=self._device)
            ]),
            TensorCollection("input_b", [
                PyTorchTensorType("matrix_b", dtype=torch.float32, shape=self._shape_b, device=self._device)
            ]),
        ]
    
    def _define_outputs(self) -> List[TensorCollection]:
        return [TensorCollection("output", [
            PyTorchTensorType("matmul_result", dtype=torch.float32, shape=self._output_shape, device=self._device)
        ])]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup], output_mask: Optional[List[bool]] = None) -> None:
        a = inputs[0][0]
        b = inputs[1][0]
        outputs[0][0] = torch.matmul(a, b)


class PyTorchAddRetargeter(RetargeterNode):
    """Element-wise addition retargeter using PyTorch: result = a + b."""
    
    def __init__(self, name: str, shape: tuple, device: str = 'cpu'):
        self._shape = shape
        self._device = device
        super().__init__(name=name)
    
    def _define_inputs(self) -> List[TensorCollection]:
        return [
            TensorCollection("input_a", [
                PyTorchTensorType("tensor_a", dtype=torch.float32, shape=self._shape, device=self._device)
            ]),
            TensorCollection("input_b", [
                PyTorchTensorType("tensor_b", dtype=torch.float32, shape=self._shape, device=self._device)
            ]),
        ]
    
    def _define_outputs(self) -> List[TensorCollection]:
        return [TensorCollection("output", [
            PyTorchTensorType("add_result", dtype=torch.float32, shape=self._shape, device=self._device)
        ])]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup], output_mask: Optional[List[bool]] = None) -> None:
        a = inputs[0][0]
        b = inputs[1][0]
        outputs[0][0] = a + b


class PyTorchActivationRetargeter(RetargeterNode):
    """Applies ReLU activation using PyTorch."""
    
    def __init__(self, name: str, shape: tuple, device: str = 'cpu'):
        self._shape = shape
        self._device = device
        super().__init__(name=name)
    
    def _define_inputs(self) -> List[TensorCollection]:
        return [
            TensorCollection("input", [
                PyTorchTensorType("tensor", dtype=torch.float32, shape=self._shape, device=self._device)
            ]),
        ]
    
    def _define_outputs(self) -> List[TensorCollection]:
        return [TensorCollection("output", [
            PyTorchTensorType("relu_result", dtype=torch.float32, shape=self._shape, device=self._device)
        ])]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup], output_mask: Optional[List[bool]] = None) -> None:
        x = inputs[0][0]
        outputs[0][0] = torch.relu(x)


# ============================================================================
# NumPy Retargeters
# ============================================================================

class NumpyMatMulRetargeter(RetargeterNode):
    """Matrix multiplication retargeter using NumPy: result = a @ b."""
    
    def __init__(self, name: str, shape_a: tuple, shape_b: tuple):
        self._shape_a = shape_a
        self._shape_b = shape_b
        self._output_shape = (shape_a[0], shape_b[1])
        super().__init__(name=name)
    
    def _define_inputs(self) -> List[TensorCollection]:
        return [
            TensorCollection("input_a", [
                NumpyArrayType("matrix_a", dtype=np.dtype('float32'), shape=self._shape_a)
            ]),
            TensorCollection("input_b", [
                NumpyArrayType("matrix_b", dtype=np.dtype('float32'), shape=self._shape_b)
            ]),
        ]
    
    def _define_outputs(self) -> List[TensorCollection]:
        return [TensorCollection("output", [
            NumpyArrayType("matmul_result", dtype=np.dtype('float32'), shape=self._output_shape)
        ])]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup], output_mask: Optional[List[bool]] = None) -> None:
        a = inputs[0][0]
        b = inputs[1][0]
        outputs[0][0] = np.matmul(a, b)


class NumpyAddRetargeter(RetargeterNode):
    """Element-wise addition retargeter using NumPy: result = a + b."""
    
    def __init__(self, name: str, shape: tuple):
        self._shape = shape
        super().__init__(name=name)
    
    def _define_inputs(self) -> List[TensorCollection]:
        return [
            TensorCollection("input_a", [
                NumpyArrayType("array_a", dtype=np.dtype('float32'), shape=self._shape)
            ]),
            TensorCollection("input_b", [
                NumpyArrayType("array_b", dtype=np.dtype('float32'), shape=self._shape)
            ]),
        ]
    
    def _define_outputs(self) -> List[TensorCollection]:
        return [TensorCollection("output", [
            NumpyArrayType("add_result", dtype=np.dtype('float32'), shape=self._shape)
        ])]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup], output_mask: Optional[List[bool]] = None) -> None:
        a = inputs[0][0]
        b = inputs[1][0]
        outputs[0][0] = a + b


# ============================================================================
# Mixed Type Retargeters (NumPy <-> PyTorch conversion)
# ============================================================================

class NumpyToPyTorchRetargeter(RetargeterNode):
    """Converts NumPy array to PyTorch tensor."""
    
    def __init__(self, name: str, shape: tuple, device: str = 'cpu'):
        self._shape = shape
        self._device = device
        super().__init__(name=name)
    
    def _define_inputs(self) -> List[TensorCollection]:
        return [
            TensorCollection("input", [
                NumpyArrayType("numpy_array", dtype=np.dtype('float32'), shape=self._shape)
            ]),
        ]
    
    def _define_outputs(self) -> List[TensorCollection]:
        return [TensorCollection("output", [
            PyTorchTensorType("torch_tensor", dtype=torch.float32, shape=self._shape, device=self._device)
        ])]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup], output_mask: Optional[List[bool]] = None) -> None:
        np_array = inputs[0][0]
        outputs[0][0] = torch.from_numpy(np_array).to(self._device)


class PyTorchToNumpyRetargeter(RetargeterNode):
    """Converts PyTorch tensor to NumPy array."""
    
    def __init__(self, name: str, shape: tuple, device: str = 'cpu'):
        self._shape = shape
        self._device = device
        super().__init__(name=name)
    
    def _define_inputs(self) -> List[TensorCollection]:
        return [
            TensorCollection("input", [
                PyTorchTensorType("torch_tensor", dtype=torch.float32, shape=self._shape, device=self._device)
            ]),
        ]
    
    def _define_outputs(self) -> List[TensorCollection]:
        return [TensorCollection("output", [
            NumpyArrayType("numpy_array", dtype=np.dtype('float32'), shape=self._shape)
        ])]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup], output_mask: Optional[List[bool]] = None) -> None:
        torch_tensor = inputs[0][0]
        outputs[0][0] = torch_tensor.cpu().numpy()


class PyTorchDeviceTransferRetargeter(RetargeterNode):
    """Transfers PyTorch tensor between CPU and GPU."""
    
    def __init__(self, name: str, shape: tuple, source_device: str, target_device: str):
        self._shape = shape
        self._source_device = source_device
        self._target_device = target_device
        super().__init__(name=name)
    
    def _define_inputs(self) -> List[TensorCollection]:
        return [
            TensorCollection("input", [
                PyTorchTensorType("source_tensor", dtype=torch.float32, shape=self._shape, device=self._source_device)
            ]),
        ]
    
    def _define_outputs(self) -> List[TensorCollection]:
        return [TensorCollection("output", [
            PyTorchTensorType("target_tensor", dtype=torch.float32, shape=self._shape, device=self._target_device)
        ])]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup], output_mask: Optional[List[bool]] = None) -> None:
        source_tensor = inputs[0][0]
        outputs[0][0] = source_tensor.to(self._target_device)


# ============================================================================
# PyTorch CPU Tests
# ============================================================================

def test_pytorch_matmul_cpu():
    """Test PyTorch matrix multiplication on CPU."""
    shape_a = (4, 8)
    shape_b = (8, 3)
    
    # Create inputs
    input_a = PyTorchTensorInputNode("a", shape_a, device='cpu')
    input_b = PyTorchTensorInputNode("b", shape_b, device='cpu')
    
    # Set values
    tensor_a = torch.ones(shape_a)
    tensor_b = torch.full(shape_b, 2.0)
    input_a.set_tensor(tensor_a)
    input_b.set_tensor(tensor_b)
    
    # Build graph
    matmul = PyTorchMatMulRetargeter("matmul", shape_a, shape_b, device='cpu')
    matmul.connect([input_a.output(), input_b.output()])
    
    # Create executor
    executor = RetargeterExecutor([matmul])
    
    # Execute
    executor.execute()
    
    # Check result: ones(4,8) @ full(8,3, 2.0) = full(4,3, 16.0)
    result = executor.get_output(matmul, 0)[0]
    expected = torch.full((4, 3), 16.0)  # 8 * 2.0 = 16.0
    assert torch.allclose(result, expected)
    assert result.device == torch.device('cpu')


def test_pytorch_chained_operations_cpu():
    """Test chained PyTorch operations on CPU: (A @ B) + C."""
    shape = (4, 4)
    
    # Create inputs
    input_a = PyTorchTensorInputNode("a", shape, device='cpu')
    input_b = PyTorchTensorInputNode("b", shape, device='cpu')
    input_c = PyTorchTensorInputNode("c", shape, device='cpu')
    
    # Set values
    input_a.set_tensor(torch.eye(4))  # Identity matrix
    input_b.set_tensor(torch.full(shape, 3.0))
    input_c.set_tensor(torch.full(shape, 1.0))
    
    # Build graph: matmul then add
    matmul = PyTorchMatMulRetargeter("matmul", shape, shape, device='cpu')
    matmul.connect([input_a.output(), input_b.output()])
    
    add = PyTorchAddRetargeter("add", shape, device='cpu')
    add.connect([matmul.output(0), input_c.output()])
    
    # Create executor
    executor = RetargeterExecutor([add])
    
    # Execute
    executor.execute()
    
    # Check: I @ full(3) = full(3), full(3) + full(1) = full(4)
    result = executor.get_output(add, 0)[0]
    expected = torch.full(shape, 4.0)
    assert torch.allclose(result, expected)


def test_pytorch_activation_cpu():
    """Test ReLU activation on CPU."""
    shape = (3, 4)
    
    # Create input with negative values
    input_node = PyTorchTensorInputNode("input", shape, device='cpu')
    input_tensor = torch.randn(shape)  # Random values including negatives
    input_node.set_tensor(input_tensor)
    
    # Build graph
    relu = PyTorchActivationRetargeter("relu", shape, device='cpu')
    relu.connect([input_node.output()])
    
    # Create executor
    executor = RetargeterExecutor([relu])
    
    # Execute
    executor.execute()
    
    # Check result
    result = executor.get_output(relu, 0)[0]
    expected = torch.relu(input_tensor)
    assert torch.allclose(result, expected)


# ============================================================================
# PyTorch GPU Tests
# ============================================================================

@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
def test_pytorch_matmul_gpu():
    """Test PyTorch matrix multiplication on GPU."""
    shape_a = (16, 32)
    shape_b = (32, 8)
    
    # Create inputs on GPU
    input_a = PyTorchTensorInputNode("a", shape_a, device='cuda')
    input_b = PyTorchTensorInputNode("b", shape_b, device='cuda')
    
    # Set values
    tensor_a = torch.ones(shape_a, device='cuda')
    tensor_b = torch.full(shape_b, 0.5, device='cuda')
    input_a.set_tensor(tensor_a)
    input_b.set_tensor(tensor_b)
    
    # Build graph
    matmul = PyTorchMatMulRetargeter("matmul", shape_a, shape_b, device='cuda')
    matmul.connect([input_a.output(), input_b.output()])
    
    # Create executor
    executor = RetargeterExecutor([matmul])
    
    # Execute
    executor.execute()
    
    # Check result
    result = executor.get_output(matmul, 0)[0]
    expected = torch.full((16, 8), 16.0, device='cuda')  # 32 * 0.5 = 16.0
    assert torch.allclose(result, expected)
    assert result.device.type == 'cuda'


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
def test_pytorch_chained_operations_gpu():
    """Test chained PyTorch operations on GPU: relu(A @ B + C)."""
    shape = (8, 8)
    
    # Create inputs on GPU
    input_a = PyTorchTensorInputNode("a", shape, device='cuda')
    input_b = PyTorchTensorInputNode("b", shape, device='cuda')
    input_c = PyTorchTensorInputNode("c", shape, device='cuda')
    
    # Set values
    input_a.set_tensor(torch.eye(8, device='cuda'))
    input_b.set_tensor(torch.full(shape, -2.0, device='cuda'))
    input_c.set_tensor(torch.full(shape, 3.0, device='cuda'))
    
    # Build graph: matmul -> add -> relu
    matmul = PyTorchMatMulRetargeter("matmul", shape, shape, device='cuda')
    matmul.connect([input_a.output(), input_b.output()])
    
    add = PyTorchAddRetargeter("add", shape, device='cuda')
    add.connect([matmul.output(0), input_c.output()])
    
    relu = PyTorchActivationRetargeter("relu", shape, device='cuda')
    relu.connect([add.output(0)])
    
    # Create executor
    executor = RetargeterExecutor([relu])
    
    # Execute
    executor.execute()
    
    # Check: I @ full(-2) = full(-2), full(-2) + full(3) = full(1), relu(full(1)) = full(1)
    result = executor.get_output(relu, 0)[0]
    expected = torch.full(shape, 1.0, device='cuda')
    assert torch.allclose(result, expected)
    assert result.device.type == 'cuda'


# ============================================================================
# NumPy Tests
# ============================================================================

def test_numpy_matmul():
    """Test NumPy matrix multiplication."""
    shape_a = (4, 8)
    shape_b = (8, 3)
    
    # Create inputs
    input_a = NumpyArrayInputNode("a", shape_a)
    input_b = NumpyArrayInputNode("b", shape_b)
    
    # Set values
    input_a.set_array(np.ones(shape_a, dtype=np.float32))
    input_b.set_array(np.full(shape_b, 2.0, dtype=np.float32))
    
    # Build graph
    matmul = NumpyMatMulRetargeter("matmul", shape_a, shape_b)
    matmul.connect([input_a.output(), input_b.output()])
    
    # Create executor
    executor = RetargeterExecutor([matmul])
    
    # Execute
    executor.execute()
    
    # Check result
    result = executor.get_output(matmul, 0)[0]
    expected = np.full((4, 3), 16.0, dtype=np.float32)
    assert np.allclose(result, expected)
    assert isinstance(result, np.ndarray)


def test_numpy_chained_operations():
    """Test chained NumPy operations: (A @ B) + C."""
    shape = (4, 4)
    
    # Create inputs
    input_a = NumpyArrayInputNode("a", shape)
    input_b = NumpyArrayInputNode("b", shape)
    input_c = NumpyArrayInputNode("c", shape)
    
    # Set values
    input_a.set_array(np.eye(4, dtype=np.float32))
    input_b.set_array(np.full(shape, 3.0, dtype=np.float32))
    input_c.set_array(np.full(shape, 1.0, dtype=np.float32))
    
    # Build graph
    matmul = NumpyMatMulRetargeter("matmul", shape, shape)
    matmul.connect([input_a.output(), input_b.output()])
    
    add = NumpyAddRetargeter("add", shape)
    add.connect([matmul.output(0), input_c.output()])
    
    # Create executor
    executor = RetargeterExecutor([add])
    
    # Execute
    executor.execute()
    
    # Check result
    result = executor.get_output(add, 0)[0]
    expected = np.full(shape, 4.0, dtype=np.float32)
    assert np.allclose(result, expected)


# ============================================================================
# Mixed NumPy/PyTorch Tests
# ============================================================================

def test_numpy_to_pytorch_conversion():
    """Test converting NumPy array to PyTorch tensor in a graph."""
    shape = (4, 4)
    
    # Create NumPy input
    input_node = NumpyArrayInputNode("np_input", shape)
    input_node.set_array(np.full(shape, 5.0, dtype=np.float32))
    
    # Convert to PyTorch
    converter = NumpyToPyTorchRetargeter("convert", shape, device='cpu')
    converter.connect([input_node.output()])
    
    # Create executor
    executor = RetargeterExecutor([converter])
    
    # Execute
    executor.execute()
    
    # Check result
    result = executor.get_output(converter, 0)[0]
    expected = torch.full(shape, 5.0)
    assert torch.allclose(result, expected)
    assert isinstance(result, torch.Tensor)


def test_pytorch_to_numpy_conversion():
    """Test converting PyTorch tensor to NumPy array in a graph."""
    shape = (4, 4)
    
    # Create PyTorch input
    input_node = PyTorchTensorInputNode("pt_input", shape, device='cpu')
    input_node.set_tensor(torch.full(shape, 7.0))
    
    # Convert to NumPy
    converter = PyTorchToNumpyRetargeter("convert", shape, device='cpu')
    converter.connect([input_node.output()])
    
    # Create executor
    executor = RetargeterExecutor([converter])
    
    # Execute
    executor.execute()
    
    # Check result
    result = executor.get_output(converter, 0)[0]
    expected = np.full(shape, 7.0, dtype=np.float32)
    assert np.allclose(result, expected)
    assert isinstance(result, np.ndarray)


def test_mixed_numpy_pytorch_pipeline():
    """
    Test a pipeline that mixes NumPy and PyTorch operations:
    NumPy input -> Convert to PyTorch -> PyTorch matmul -> Convert back to NumPy
    """
    shape = (4, 4)
    
    # Create NumPy inputs
    input_a = NumpyArrayInputNode("np_a", shape)
    input_b = NumpyArrayInputNode("np_b", shape)
    input_a.set_array(np.eye(4, dtype=np.float32))
    input_b.set_array(np.full(shape, 2.0, dtype=np.float32))
    
    # Convert to PyTorch
    convert_a = NumpyToPyTorchRetargeter("convert_a", shape, device='cpu')
    convert_a.connect([input_a.output()])
    
    convert_b = NumpyToPyTorchRetargeter("convert_b", shape, device='cpu')
    convert_b.connect([input_b.output()])
    
    # PyTorch matmul
    matmul = PyTorchMatMulRetargeter("matmul", shape, shape, device='cpu')
    matmul.connect([convert_a.output(0), convert_b.output(0)])
    
    # Convert back to NumPy
    convert_result = PyTorchToNumpyRetargeter("convert_result", shape, device='cpu')
    convert_result.connect([matmul.output(0)])
    
    # Create executor
    executor = RetargeterExecutor([convert_result])
    
    # Execute
    executor.execute()
    
    # Check result: I @ full(2) = full(2)
    result = executor.get_output(convert_result, 0)[0]
    expected = np.full(shape, 2.0, dtype=np.float32)
    assert np.allclose(result, expected)
    assert isinstance(result, np.ndarray)


def test_parallel_numpy_pytorch_branches():
    """
    Test parallel branches with NumPy and PyTorch that compute same operation.
    Verifies results match between the two frameworks.
    """
    shape = (4, 4)
    
    # Create shared values
    values_a = np.full(shape, 3.0, dtype=np.float32)
    values_b = np.full(shape, 2.0, dtype=np.float32)
    
    # NumPy branch
    np_input_a = NumpyArrayInputNode("np_a", shape)
    np_input_b = NumpyArrayInputNode("np_b", shape)
    np_input_a.set_array(values_a)
    np_input_b.set_array(values_b)
    np_add = NumpyAddRetargeter("np_add", shape)
    np_add.connect([np_input_a.output(), np_input_b.output()])
    
    # PyTorch branch
    pt_input_a = PyTorchTensorInputNode("pt_a", shape, device='cpu')
    pt_input_b = PyTorchTensorInputNode("pt_b", shape, device='cpu')
    pt_input_a.set_tensor(torch.from_numpy(values_a))
    pt_input_b.set_tensor(torch.from_numpy(values_b))
    pt_add = PyTorchAddRetargeter("pt_add", shape, device='cpu')
    pt_add.connect([pt_input_a.output(), pt_input_b.output()])
    
    # Create executor with both outputs
    executor = RetargeterExecutor([np_add, pt_add])
    
    # Execute
    executor.execute()
    
    # Check results match
    np_result = executor.get_output(np_add, 0)[0]
    pt_result = executor.get_output(pt_add, 0)[0]
    
    expected = np.full(shape, 5.0, dtype=np.float32)
    assert np.allclose(np_result, expected)
    assert torch.allclose(pt_result, torch.from_numpy(expected))


# ============================================================================
# CPU/GPU Transfer Tests
# ============================================================================

@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
def test_cpu_to_gpu_transfer():
    """Test transferring tensor from CPU to GPU in a graph."""
    shape = (8, 8)
    
    # Create CPU input
    input_node = PyTorchTensorInputNode("cpu_input", shape, device='cpu')
    input_node.set_tensor(torch.full(shape, 3.0))
    
    # Transfer to GPU
    transfer = PyTorchDeviceTransferRetargeter("transfer", shape, 'cpu', 'cuda')
    transfer.connect([input_node.output()])
    
    # Create executor
    executor = RetargeterExecutor([transfer])
    
    # Execute
    executor.execute()
    
    # Check result
    result = executor.get_output(transfer, 0)[0]
    expected = torch.full(shape, 3.0, device='cuda')
    assert torch.allclose(result, expected)
    assert result.device.type == 'cuda'


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
def test_gpu_to_cpu_transfer():
    """Test transferring tensor from GPU to CPU in a graph."""
    shape = (8, 8)
    
    # Create GPU input
    input_node = PyTorchTensorInputNode("gpu_input", shape, device='cuda')
    input_node.set_tensor(torch.full(shape, 4.0, device='cuda'))
    
    # Transfer to CPU
    transfer = PyTorchDeviceTransferRetargeter("transfer", shape, 'cuda', 'cpu')
    transfer.connect([input_node.output()])
    
    # Create executor
    executor = RetargeterExecutor([transfer])
    
    # Execute
    executor.execute()
    
    # Check result
    result = executor.get_output(transfer, 0)[0]
    expected = torch.full(shape, 4.0)
    assert torch.allclose(result, expected)
    assert result.device == torch.device('cpu')


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
def test_cpu_gpu_cpu_roundtrip():
    """
    Test a roundtrip: CPU -> GPU (compute) -> CPU.
    Demonstrates a typical pattern for GPU acceleration.
    """
    shape = (16, 16)
    
    # Create CPU input
    cpu_input = PyTorchTensorInputNode("cpu_input", shape, device='cpu')
    cpu_input.set_tensor(torch.randn(shape))
    
    # Transfer to GPU
    to_gpu = PyTorchDeviceTransferRetargeter("to_gpu", shape, 'cpu', 'cuda')
    to_gpu.connect([cpu_input.output()])
    
    # GPU computation (matmul with self)
    gpu_matmul = PyTorchMatMulRetargeter("gpu_matmul", shape, shape, device='cuda')
    gpu_matmul.connect([to_gpu.output(0), to_gpu.output(0)])
    
    # Transfer back to CPU
    to_cpu = PyTorchDeviceTransferRetargeter("to_cpu", shape, 'cuda', 'cpu')
    to_cpu.connect([gpu_matmul.output(0)])
    
    # Create executor
    executor = RetargeterExecutor([to_cpu])
    
    # Execute
    executor.execute()
    
    # Verify result is on CPU
    result = executor.get_output(to_cpu, 0)[0]
    assert result.device == torch.device('cpu')
    
    # Verify computation is correct (compare with CPU-only computation)
    original_tensor = cpu_input._tensor
    expected = torch.matmul(original_tensor, original_tensor)
    assert torch.allclose(result, expected, rtol=1e-4, atol=1e-4)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
def test_mixed_cpu_gpu_graph():
    """
    Test a graph with mixed CPU and GPU nodes.
    
    Graph:
        CPU_A -----> GPU_compute -----> CPU_result
        CPU_B --/
    """
    shape = (8, 8)
    
    # CPU inputs
    input_a = PyTorchTensorInputNode("cpu_a", shape, device='cpu')
    input_b = PyTorchTensorInputNode("cpu_b", shape, device='cpu')
    input_a.set_tensor(torch.full(shape, 2.0))
    input_b.set_tensor(torch.full(shape, 3.0))
    
    # Transfer both to GPU
    to_gpu_a = PyTorchDeviceTransferRetargeter("to_gpu_a", shape, 'cpu', 'cuda')
    to_gpu_a.connect([input_a.output()])
    
    to_gpu_b = PyTorchDeviceTransferRetargeter("to_gpu_b", shape, 'cpu', 'cuda')
    to_gpu_b.connect([input_b.output()])
    
    # GPU add
    gpu_add = PyTorchAddRetargeter("gpu_add", shape, device='cuda')
    gpu_add.connect([to_gpu_a.output(0), to_gpu_b.output(0)])
    
    # Transfer result back to CPU
    to_cpu = PyTorchDeviceTransferRetargeter("to_cpu", shape, 'cuda', 'cpu')
    to_cpu.connect([gpu_add.output(0)])
    
    # Create executor
    executor = RetargeterExecutor([to_cpu])
    
    # Execute
    executor.execute()
    
    # Check result: 2 + 3 = 5
    result = executor.get_output(to_cpu, 0)[0]
    expected = torch.full(shape, 5.0)
    assert torch.allclose(result, expected)
    assert result.device == torch.device('cpu')


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
def test_numpy_to_gpu_pytorch_to_numpy():
    """
    Full pipeline: NumPy -> PyTorch GPU -> NumPy
    Demonstrates using GPU for acceleration with NumPy I/O.
    """
    shape = (8, 8)
    
    # NumPy inputs
    np_input = NumpyArrayInputNode("np_input", shape)
    np_input.set_array(np.full(shape, 2.0, dtype=np.float32))
    
    # Convert to PyTorch CPU
    to_pytorch = NumpyToPyTorchRetargeter("to_pytorch", shape, device='cpu')
    to_pytorch.connect([np_input.output()])
    
    # Transfer to GPU
    to_gpu = PyTorchDeviceTransferRetargeter("to_gpu", shape, 'cpu', 'cuda')
    to_gpu.connect([to_pytorch.output(0)])
    
    # GPU computation
    gpu_activation = PyTorchActivationRetargeter("gpu_relu", shape, device='cuda')
    gpu_activation.connect([to_gpu.output(0)])
    
    # Transfer back to CPU
    to_cpu = PyTorchDeviceTransferRetargeter("to_cpu", shape, 'cuda', 'cpu')
    to_cpu.connect([gpu_activation.output(0)])
    
    # Convert back to NumPy
    to_numpy = PyTorchToNumpyRetargeter("to_numpy", shape, device='cpu')
    to_numpy.connect([to_cpu.output(0)])
    
    # Create executor
    executor = RetargeterExecutor([to_numpy])
    
    # Execute
    executor.execute()
    
    # Check result
    result = executor.get_output(to_numpy, 0)[0]
    expected = np.full(shape, 2.0, dtype=np.float32)  # ReLU of positive values
    assert np.allclose(result, expected)
    assert isinstance(result, np.ndarray)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

