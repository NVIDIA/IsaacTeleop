# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for TensorGroup class - collection of tensors with type validation.
"""

import pytest
import numpy as np
from isaacteleop.retargeting_engine.interface import (
    TensorGroup,
    Tensor,
    TensorGroupType,
    UNSET_VALUE,
)
from isaacteleop.retargeting_engine.tensor_types import (
    FloatType,
    IntType,
    BoolType,
    NDArrayType,
    DLDataType,
)


class TestTensorGroupConstruction:
    """Test tensor group construction."""

    def test_tensor_group_basic_construction(self):
        """Test creating a tensor group from a group type."""
        group_type = TensorGroupType(
            name="position_data",
            tensors=[
                FloatType("x"),
                FloatType("y"),
                FloatType("z"),
            ],
        )

        tensor_group = TensorGroup(group_type)

        assert tensor_group.group_type == group_type
        assert len(tensor_group) == 3

    def test_tensor_group_mixed_types(self):
        """Test tensor group with mixed types."""
        group_type = TensorGroupType(
            name="sensor_data",
            tensors=[
                FloatType("temperature"),
                IntType("count"),
                BoolType("active"),
            ],
        )

        tensor_group = TensorGroup(group_type)

        assert len(tensor_group) == 3
        assert tensor_group.group_type.name == "sensor_data"

    def test_tensor_group_with_ndarray(self):
        """Test tensor group containing numpy arrays."""
        group_type = TensorGroupType(
            name="arrays",
            tensors=[
                NDArrayType(
                    "matrix", shape=(3, 3), dtype=DLDataType.FLOAT, dtype_bits=32
                ),
                NDArrayType(
                    "vector", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32
                ),
            ],
        )

        tensor_group = TensorGroup(group_type)

        assert len(tensor_group) == 2

    def test_tensor_group_empty(self):
        """Test creating an empty tensor group."""
        group_type = TensorGroupType(name="empty", tensors=[])
        tensor_group = TensorGroup(group_type)

        assert len(tensor_group) == 0


class TestTensorGroupIndexAccess:
    """Test indexed access to tensor values."""

    def test_getitem_unset_raises(self):
        """Test that accessing unset tensor value raises."""
        group_type = TensorGroupType(name="data", tensors=[FloatType("value")])
        tensor_group = TensorGroup(group_type)

        with pytest.raises(ValueError, match="value has not been set"):
            _ = tensor_group[0]

    def test_setitem_and_getitem(self):
        """Test setting and getting tensor values by index."""
        group_type = TensorGroupType(
            name="coords",
            tensors=[
                FloatType("x"),
                FloatType("y"),
                FloatType("z"),
            ],
        )
        tensor_group = TensorGroup(group_type)

        # Set values
        tensor_group[0] = 1.0
        tensor_group[1] = 2.0
        tensor_group[2] = 3.0

        # Get values
        assert tensor_group[0] == 1.0
        assert tensor_group[1] == 2.0
        assert tensor_group[2] == 3.0

    def test_setitem_validates_type(self):
        """Test that setitem validates against tensor type."""
        group_type = TensorGroupType(
            name="data",
            tensors=[
                FloatType("value"),
                IntType("count"),
            ],
        )
        tensor_group = TensorGroup(group_type)

        # Valid assignments
        tensor_group[0] = 3.14
        tensor_group[1] = 42

        # Invalid assignments (wrong type)
        with pytest.raises(TypeError, match="Expected float"):
            tensor_group[0] = 10  # int instead of float

        with pytest.raises(TypeError, match="Expected int"):
            tensor_group[1] = 3.14  # float instead of int

    def test_getitem_out_of_range(self):
        """Test that out-of-range index raises IndexError."""
        group_type = TensorGroupType(name="data", tensors=[FloatType("x")])
        tensor_group = TensorGroup(group_type)
        tensor_group[0] = 1.0

        # Positive out of range
        with pytest.raises(IndexError):
            _ = tensor_group[1]

        # Negative out of range
        with pytest.raises(IndexError):
            _ = tensor_group[-2]

    def test_getitem_negative_index(self):
        """Test that negative indexing works like normal Python lists."""
        group_type = TensorGroupType(
            name="coords",
            tensors=[
                FloatType("x"),
                FloatType("y"),
                FloatType("z"),
            ],
        )
        tensor_group = TensorGroup(group_type)
        tensor_group[0] = 1.0
        tensor_group[1] = 2.0
        tensor_group[2] = 3.0

        # Test negative indexing
        assert tensor_group[-1] == 3.0  # Last element
        assert tensor_group[-2] == 2.0  # Second to last
        assert tensor_group[-3] == 1.0  # Third to last (first element)

    def test_setitem_out_of_range(self):
        """Test that setting out-of-range index raises IndexError."""
        group_type = TensorGroupType(name="data", tensors=[FloatType("x")])
        tensor_group = TensorGroup(group_type)

        with pytest.raises(IndexError):
            tensor_group[1] = 1.0


class TestTensorGroupWithArrays:
    """Test tensor group with numpy arrays."""

    def test_tensor_group_ndarray_access(self, float32_array, matrix_3x3):
        """Test accessing numpy arrays in tensor group."""
        group_type = TensorGroupType(
            name="arrays",
            tensors=[
                NDArrayType(
                    "data", shape=(2, 3), dtype=DLDataType.FLOAT, dtype_bits=32
                ),
                NDArrayType(
                    "matrix", shape=(3, 3), dtype=DLDataType.FLOAT, dtype_bits=32
                ),
            ],
        )
        tensor_group = TensorGroup(group_type)

        # Set arrays
        tensor_group[0] = float32_array
        tensor_group[1] = matrix_3x3

        # Get arrays
        assert np.array_equal(tensor_group[0], float32_array)
        assert np.array_equal(tensor_group[1], matrix_3x3)

    def test_tensor_group_ndarray_validation(self, float32_array):
        """Test that arrays are validated on assignment."""
        group_type = TensorGroupType(
            name="arrays",
            tensors=[
                NDArrayType(
                    "correct_shape", shape=(2, 3), dtype=DLDataType.FLOAT, dtype_bits=32
                ),
                NDArrayType(
                    "wrong_shape", shape=(3, 3), dtype=DLDataType.FLOAT, dtype_bits=32
                ),
            ],
        )
        tensor_group = TensorGroup(group_type)

        # Correct shape should work
        tensor_group[0] = float32_array

        # Wrong shape should fail
        with pytest.raises(TypeError, match="shape mismatch"):
            tensor_group[1] = float32_array


class TestGetTensor:
    """Test get_tensor method for accessing Tensor objects."""

    def test_get_tensor_returns_tensor_object(self):
        """Test that get_tensor returns the Tensor object."""
        group_type = TensorGroupType(
            name="data",
            tensors=[
                FloatType("velocity"),
                IntType("count"),
            ],
        )
        tensor_group = TensorGroup(group_type)

        # Get tensor objects
        tensor0 = tensor_group.get_tensor(0)
        tensor1 = tensor_group.get_tensor(1)

        assert isinstance(tensor0, Tensor)
        assert isinstance(tensor1, Tensor)
        assert tensor0.tensor_type.name == "velocity"
        assert tensor1.tensor_type.name == "count"

    def test_get_tensor_before_set(self):
        """Test getting tensor object before value is set."""
        group_type = TensorGroupType(name="data", tensors=[FloatType("value")])
        tensor_group = TensorGroup(group_type)

        tensor = tensor_group.get_tensor(0)
        assert isinstance(tensor, Tensor)
        assert tensor._value is UNSET_VALUE

    def test_get_tensor_after_set(self):
        """Test getting tensor object after value is set."""
        group_type = TensorGroupType(name="data", tensors=[FloatType("value")])
        tensor_group = TensorGroup(group_type)

        tensor_group[0] = 42.0

        tensor = tensor_group.get_tensor(0)
        assert tensor.value == 42.0

    def test_get_tensor_modify_through_object(self):
        """Test modifying tensor through returned Tensor object."""
        group_type = TensorGroupType(name="data", tensors=[IntType("counter")])
        tensor_group = TensorGroup(group_type)

        # Get tensor and modify it
        tensor = tensor_group.get_tensor(0)
        tensor.value = 100

        # Check that group reflects the change
        assert tensor_group[0] == 100


class TestTensorGroupLen:
    """Test len() operator on tensor groups."""

    def test_len_multiple_tensors(self):
        """Test len with multiple tensors."""
        group_type = TensorGroupType(
            name="data",
            tensors=[
                FloatType("a"),
                FloatType("b"),
                FloatType("c"),
                FloatType("d"),
            ],
        )
        tensor_group = TensorGroup(group_type)

        assert len(tensor_group) == 4

    def test_len_single_tensor(self):
        """Test len with single tensor."""
        group_type = TensorGroupType(name="data", tensors=[FloatType("x")])
        tensor_group = TensorGroup(group_type)

        assert len(tensor_group) == 1

    def test_len_empty(self):
        """Test len with no tensors."""
        group_type = TensorGroupType(name="empty", tensors=[])
        tensor_group = TensorGroup(group_type)

        assert len(tensor_group) == 0


class TestTensorGroupRepr:
    """Test tensor group string representation."""

    def test_repr_with_tensors(self):
        """Test repr with tensors."""
        group_type = TensorGroupType(
            name="sensor_data",
            tensors=[
                FloatType("temp"),
                IntType("count"),
                BoolType("active"),
            ],
        )
        tensor_group = TensorGroup(group_type)

        repr_str = repr(tensor_group)
        assert "TensorGroup" in repr_str
        assert "sensor_data" in repr_str
        assert "3" in repr_str

    def test_repr_empty_group(self):
        """Test repr with empty group."""
        group_type = TensorGroupType(name="empty", tensors=[])
        tensor_group = TensorGroup(group_type)

        repr_str = repr(tensor_group)
        assert "TensorGroup" in repr_str
        assert "empty" in repr_str
        assert "0" in repr_str


class TestTensorGroupTypeProperty:
    """Test group_type property."""

    def test_group_type_property(self):
        """Test accessing group_type property."""
        group_type = TensorGroupType(
            name="test_group", tensors=[FloatType("x"), FloatType("y")]
        )
        tensor_group = TensorGroup(group_type)

        assert tensor_group.group_type == group_type
        assert tensor_group.group_type.name == "test_group"
        assert len(tensor_group.group_type.types) == 2

    def test_group_type_immutable(self):
        """Test that group_type cannot be changed after creation."""
        group_type = TensorGroupType(name="original", tensors=[FloatType("x")])
        tensor_group = TensorGroup(group_type)

        # group_type has no setter, should raise AttributeError
        other_group_type = TensorGroupType(name="other", tensors=[IntType("y")])
        with pytest.raises(AttributeError):
            tensor_group.group_type = other_group_type


class TestTensorGroupIntegration:
    """Integration tests for tensor groups."""

    def test_full_workflow(self):
        """Test complete workflow of creating and using tensor group."""
        # Define group type
        group_type = TensorGroupType(
            name="robot_state",
            tensors=[
                NDArrayType(
                    "joint_positions", shape=(7,), dtype=DLDataType.FLOAT, dtype_bits=32
                ),
                NDArrayType(
                    "joint_velocities",
                    shape=(7,),
                    dtype=DLDataType.FLOAT,
                    dtype_bits=32,
                ),
                FloatType("gripper_width"),
                BoolType("is_moving"),
            ],
        )

        # Create tensor group
        state = TensorGroup(group_type)
        assert len(state) == 4

        # Set values
        positions = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7], dtype=np.float32)
        velocities = np.zeros(7, dtype=np.float32)

        state[0] = positions
        state[1] = velocities
        state[2] = 0.05
        state[3] = True

        # Read back values
        assert np.array_equal(state[0], positions)
        assert np.array_equal(state[1], velocities)
        assert state[2] == 0.05
        assert state[3] is True

        # Update values
        new_velocities = np.array(
            [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07], dtype=np.float32
        )
        state[1] = new_velocities
        assert np.array_equal(state[1], new_velocities)

    def test_multiple_groups_same_type(self):
        """Test creating multiple groups from same type."""
        group_type = TensorGroupType(
            name="coords",
            tensors=[
                FloatType("x"),
                FloatType("y"),
                FloatType("z"),
            ],
        )

        group1 = TensorGroup(group_type)
        group2 = TensorGroup(group_type)

        # Set different values in each group
        group1[0] = 1.0
        group1[1] = 2.0
        group1[2] = 3.0

        group2[0] = 10.0
        group2[1] = 20.0
        group2[2] = 30.0

        # Verify they're independent
        assert group1[0] == 1.0
        assert group2[0] == 10.0


# ============================================================================
# TensorGroup.create_snapshot() / OptionalTensorGroup.create_snapshot() Tests
# ============================================================================


class TestTensorGroupCopy:
    """Tests for TensorGroup.create_snapshot() — independent snapshot of scalar values."""

    def _float_group(self, value: float = 1.0) -> TensorGroup:
        gt = TensorGroupType("g", [FloatType("v")])
        tg = TensorGroup(gt)
        tg[0] = value
        return tg

    def test_copy_returns_new_object(self):
        tg = self._float_group(3.0)
        cp = tg.create_snapshot()
        assert cp is not tg

    def test_copy_preserves_value(self):
        tg = self._float_group(7.5)
        cp = tg.create_snapshot()
        assert cp[0] == 7.5

    def test_copy_scalar_independence(self):
        """Mutating the copy must not affect the original."""
        tg = self._float_group(1.0)
        cp = tg.create_snapshot()
        cp[0] = 99.0
        assert tg[0] == 1.0

    def test_copy_returns_tensor_group_type(self):
        """create_snapshot() on a TensorGroup must return a TensorGroup, not base class."""
        tg = self._float_group(1.0)
        cp = tg.create_snapshot()
        assert type(cp) is TensorGroup
        assert cp.is_none is False

    def test_copy_multi_tensor(self):
        gt = TensorGroupType("pos", [FloatType("x"), FloatType("y"), FloatType("z")])
        tg = TensorGroup(gt)
        tg[0] = 1.0
        tg[1] = 2.0
        tg[2] = 3.0

        cp = tg.create_snapshot()
        assert cp[0] == 1.0
        assert cp[1] == 2.0
        assert cp[2] == 3.0

        cp[0] = 99.0
        assert tg[0] == 1.0

    def test_copy_after_get_tensor_value_mutation(self):
        """create_snapshot() must capture values set via get_tensor().value, not just __setitem__."""
        gt = TensorGroupType("g", [FloatType("v")])
        tg = TensorGroup(gt)
        tg[0] = 1.0

        # Mutate through the Tensor object directly, bypassing __setitem__
        tg.get_tensor(0).value = 99.0

        cp = tg.create_snapshot()
        # Copy must see the mutated value
        assert cp[0] == 99.0
        # Mutating the copy must not affect the original
        cp[0] = 0.0
        assert tg[0] == 99.0

    def test_copy_via_get_tensor_before_setitem(self):
        """create_snapshot() works even when the only write was through get_tensor().value."""
        gt = TensorGroupType("g", [FloatType("v")])
        tg = TensorGroup(gt)

        # Set via get_tensor().value only — __setitem__ never called, so
        # _is_none starts True; is_none property returns False for TensorGroup.
        tg.get_tensor(0).value = 42.0

        cp = tg.create_snapshot()
        assert cp[0] == 42.0

    """Tests for TensorGroup.create_snapshot() with numpy array tensors."""

    def _array_group(self) -> TensorGroup:
        from isaacteleop.retargeting_engine.tensor_types import NDArrayType, DLDataType

        gt = TensorGroupType(
            "arr", [NDArrayType("v", shape=(3,), dtype=DLDataType.FLOAT, dtype_bits=32)]
        )
        tg = TensorGroup(gt)
        tg[0] = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        return tg

    def test_copy_array_independence(self):
        """Mutating the copy's array must not affect the original."""
        tg = self._array_group()
        cp = tg.create_snapshot()

        cp[0][0] = 999.0
        assert tg[0][0] == 1.0

    def test_copy_array_values_equal(self):
        tg = self._array_group()
        cp = tg.create_snapshot()
        assert np.array_equal(cp[0], tg[0])

    def test_copy_array_is_different_buffer(self):
        """The copied array must not share memory with the original."""
        tg = self._array_group()
        cp = tg.create_snapshot()
        assert not np.shares_memory(cp[0], tg[0])


class TestOptionalTensorGroupCopy:
    """Tests for OptionalTensorGroup.create_snapshot()."""

    def _make_opt_type(self):
        from isaacteleop.retargeting_engine.interface.tensor_group_type import (
            OptionalTensorGroupType,
        )

        return OptionalTensorGroupType(TensorGroupType("opt", [FloatType("v")]))

    def test_copy_absent_group_is_also_absent(self):
        from isaacteleop.retargeting_engine.interface import OptionalTensorGroup

        tg = OptionalTensorGroup(self._make_opt_type())
        assert tg.is_none

        cp = tg.create_snapshot()
        assert cp.is_none
        assert cp is not tg

    def test_copy_present_group_has_correct_value(self):
        from isaacteleop.retargeting_engine.interface import OptionalTensorGroup

        tg = OptionalTensorGroup(self._make_opt_type())
        tg[0] = 5.0

        cp = tg.create_snapshot()
        assert not cp.is_none
        assert cp[0] == 5.0

    def test_copy_returns_optional_tensor_group_type(self):
        from isaacteleop.retargeting_engine.interface import OptionalTensorGroup

        tg = OptionalTensorGroup(self._make_opt_type())
        tg[0] = 1.0

        cp = tg.create_snapshot()
        assert type(cp) is OptionalTensorGroup


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
