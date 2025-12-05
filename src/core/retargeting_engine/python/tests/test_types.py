"""
Tests for tensor types.
"""

import pytest
import numpy as np
import torch
from .. import (
    BoolType,
    IntType,
    FloatType,
    NumpyArrayType,
    PyTorchTensorType,
)


def test_bool_type():
    """Test BoolType."""
    bool_type = BoolType("test_bool")
    
    # Check name
    assert bool_type.name == "test_bool"
    
    # Check default allocation
    default_value = bool_type.allocate_default()
    assert default_value is False
    assert isinstance(default_value, bool)


def test_int_type():
    """Test IntType."""
    int_type = IntType("test_int")
    
    # Check name
    assert int_type.name == "test_int"
    
    # Check default allocation
    default_value = int_type.allocate_default()
    assert default_value == 0
    assert isinstance(default_value, int)


def test_float_type():
    """Test FloatType."""
    float_type = FloatType("test_float")
    
    # Check name
    assert float_type.name == "test_float"
    
    # Check default allocation
    default_value = float_type.allocate_default()
    assert default_value == 0.0
    assert isinstance(default_value, (int, float))


def test_numpy_array_type():
    """Test NumpyArrayType."""
    array_type = NumpyArrayType(
        "test_array",
        dtype=np.dtype('float32'),
        shape=(3, 4)
    )
    
    # Check name
    assert array_type.name == "test_array"
    
    # Check default allocation
    default_value = array_type.allocate_default()
    assert isinstance(default_value, np.ndarray)
    assert default_value.shape == (3, 4)
    assert default_value.dtype == np.float32
    assert np.all(default_value == 0)


def test_scalar_type_compatibility():
    """Test that scalar types are compatible with same dtype."""
    int_type1 = IntType("int1")
    int_type2 = IntType("int2")
    float_type = FloatType("float1")
    
    # Same type should be compatible
    assert int_type1.is_compatible_with(int_type2)
    
    # Different types should not be compatible
    assert not int_type1.is_compatible_with(float_type)


def test_numpy_array_type_compatibility():
    """Test NumpyArrayType compatibility."""
    array_type1 = NumpyArrayType("arr1", dtype=np.dtype('float32'), shape=(3, 4))
    array_type2 = NumpyArrayType("arr2", dtype=np.dtype('float32'), shape=(3, 4))
    array_type3 = NumpyArrayType("arr3", dtype=np.dtype('float64'), shape=(3, 4))
    array_type4 = NumpyArrayType("arr4", dtype=np.dtype('float32'), shape=(4, 3))
    
    # Same dtype and shape should be compatible
    assert array_type1.is_compatible_with(array_type2)
    
    # Different dtype should not be compatible
    assert not array_type1.is_compatible_with(array_type3)
    
    # Different shape should not be compatible
    assert not array_type1.is_compatible_with(array_type4)


# ============================================================================
# PyTorch Tensor Type Tests
# ============================================================================

def test_pytorch_tensor_type():
    """Test PyTorchTensorType basic functionality."""
    tensor_type = PyTorchTensorType(
        "test_tensor",
        dtype=torch.float32,
        shape=(3, 4)
    )
    
    # Check name
    assert tensor_type.name == "test_tensor"
    
    # Check properties
    assert tensor_type.dtype == torch.float32
    assert tensor_type.shape == (3, 4)
    assert tensor_type.device == torch.device('cpu')
    
    # Check default allocation
    default_value = tensor_type.allocate_default()
    assert isinstance(default_value, torch.Tensor)
    assert default_value.shape == (3, 4)
    assert default_value.dtype == torch.float32
    assert default_value.device == torch.device('cpu')
    assert torch.all(default_value == 0)


def test_pytorch_tensor_type_with_device():
    """Test PyTorchTensorType with explicit device specification."""
    tensor_type_cpu = PyTorchTensorType(
        "cpu_tensor",
        dtype=torch.float64,
        shape=(2, 3),
        device='cpu'
    )
    
    default_value = tensor_type_cpu.allocate_default()
    assert default_value.device == torch.device('cpu')
    assert default_value.dtype == torch.float64


def test_pytorch_tensor_type_compatibility():
    """Test PyTorchTensorType compatibility."""
    tensor_type1 = PyTorchTensorType("t1", dtype=torch.float32, shape=(3, 4))
    tensor_type2 = PyTorchTensorType("t2", dtype=torch.float32, shape=(3, 4))
    tensor_type3 = PyTorchTensorType("t3", dtype=torch.float64, shape=(3, 4))
    tensor_type4 = PyTorchTensorType("t4", dtype=torch.float32, shape=(4, 3))
    tensor_type5 = PyTorchTensorType("t5", dtype=torch.float32, shape=(3, 4), device='cpu')
    
    # Same dtype and shape should be compatible (device ignored)
    assert tensor_type1.is_compatible_with(tensor_type2)
    assert tensor_type1.is_compatible_with(tensor_type5)
    
    # Different dtype should not be compatible
    assert not tensor_type1.is_compatible_with(tensor_type3)
    
    # Different shape should not be compatible
    assert not tensor_type1.is_compatible_with(tensor_type4)


def test_pytorch_tensor_type_to_device():
    """Test PyTorchTensorType device switching with .to() method."""
    tensor_type_cpu = PyTorchTensorType(
        "tensor",
        dtype=torch.float32,
        shape=(3, 4),
        device='cpu'
    )
    
    # Create a new type with different device
    tensor_type_new = tensor_type_cpu.to('cpu')
    
    # Should have same properties but different instance
    assert tensor_type_new.dtype == tensor_type_cpu.dtype
    assert tensor_type_new.shape == tensor_type_cpu.shape
    assert tensor_type_new.device == torch.device('cpu')


def test_pytorch_numpy_incompatibility():
    """Test that PyTorch and NumPy types are not compatible."""
    pytorch_type = PyTorchTensorType("pt", dtype=torch.float32, shape=(3, 4))
    numpy_type = NumpyArrayType("np", dtype=np.dtype('float32'), shape=(3, 4))
    
    assert not pytorch_type.is_compatible_with(numpy_type)
    assert not numpy_type.is_compatible_with(pytorch_type)


# ============================================================================
# Sample Computation Tests (CPU and GPU)
# ============================================================================

def _run_sample_computation(device: torch.device):
    """
    Run a sample computation on the specified device.
    
    This demonstrates using PyTorchTensorType for GPU-accelerated operations.
    """
    # Define tensor types for our computation
    input_type = PyTorchTensorType("input", dtype=torch.float32, shape=(100, 100), device=device)
    weight_type = PyTorchTensorType("weight", dtype=torch.float32, shape=(100, 50), device=device)
    output_type = PyTorchTensorType("output", dtype=torch.float32, shape=(100, 50), device=device)
    
    # Allocate tensors
    input_tensor = input_type.allocate_default()
    weight_tensor = weight_type.allocate_default()
    output_tensor = output_type.allocate_default()
    
    # Verify device placement (compare device type, not exact device object)
    assert input_tensor.device.type == device.type
    assert weight_tensor.device.type == device.type
    assert output_tensor.device.type == device.type
    
    # Initialize with some values
    input_tensor.fill_(1.0)
    weight_tensor.fill_(0.5)
    
    # Perform sample computation: matrix multiplication + activation
    result = torch.matmul(input_tensor, weight_tensor)
    result = torch.relu(result)
    result = result + 1.0  # Bias
    
    # Verify result
    assert result.shape == (100, 50)
    assert result.device.type == device.type
    # After matmul of 100x100 ones @ 100x50 halves = 100x50 of 50s (100 * 0.5)
    # ReLU doesn't change positive values, + 1.0 bias = 51.0
    expected_value = 100 * 0.5 + 1.0  # 51.0
    assert torch.allclose(result, torch.full((100, 50), expected_value, device=device))
    
    return result


def test_sample_computation_cpu():
    """Test sample computation on CPU."""
    device = torch.device('cpu')
    result = _run_sample_computation(device)
    
    assert result.device == device
    assert result.shape == (100, 50)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
def test_sample_computation_gpu():
    """Test sample computation on GPU."""
    device = torch.device('cuda')
    result = _run_sample_computation(device)
    
    assert result.device.type == 'cuda'
    assert result.shape == (100, 50)


def test_cpu_gpu_computation_equivalence():
    """
    Test that CPU and GPU computations produce equivalent results.
    
    This verifies that the same computation yields the same output
    regardless of device, which is important for testing and debugging.
    """
    # Define tensor types
    input_shape = (32, 64)
    weight_shape = (64, 16)
    
    # CPU computation
    cpu_input_type = PyTorchTensorType("cpu_input", dtype=torch.float32, shape=input_shape, device='cpu')
    cpu_weight_type = PyTorchTensorType("cpu_weight", dtype=torch.float32, shape=weight_shape, device='cpu')
    
    cpu_input = cpu_input_type.allocate_default()
    cpu_weight = cpu_weight_type.allocate_default()
    
    # Use deterministic values for reproducibility
    torch.manual_seed(42)
    cpu_input.normal_()
    cpu_weight.normal_()
    
    # Compute on CPU
    cpu_result = torch.matmul(cpu_input, cpu_weight)
    cpu_result = torch.sigmoid(cpu_result)
    
    if torch.cuda.is_available():
        # GPU computation with same inputs
        gpu_input = cpu_input.cuda()
        gpu_weight = cpu_weight.cuda()
        
        gpu_result = torch.matmul(gpu_input, gpu_weight)
        gpu_result = torch.sigmoid(gpu_result)
        
        # Compare results (move GPU result to CPU for comparison)
        assert torch.allclose(cpu_result, gpu_result.cpu(), rtol=1e-5, atol=1e-5)


def test_tensor_type_batch_operations():
    """Test batch operations with PyTorchTensorType."""
    batch_size = 16
    feature_dim = 32
    
    # Define batch tensor type
    batch_type = PyTorchTensorType(
        "batch_features",
        dtype=torch.float32,
        shape=(batch_size, feature_dim),
        device='cpu'
    )
    
    # Allocate and fill with test data
    batch_tensor = batch_type.allocate_default()
    batch_tensor.uniform_(-1, 1)
    
    # Perform batch normalization-like operation
    mean = batch_tensor.mean(dim=0, keepdim=True)
    std = batch_tensor.std(dim=0, keepdim=True)
    normalized = (batch_tensor - mean) / (std + 1e-5)
    
    # Verify shape preserved
    assert normalized.shape == (batch_size, feature_dim)
    
    # Verify normalization (mean should be ~0, std should be ~1)
    assert torch.abs(normalized.mean()) < 0.1
    assert torch.abs(normalized.std() - 1.0) < 0.1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

