# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tensor Group for data storage.

``OptionalTensorGroup`` is the base class holding tensor data, a reference to
its ``TensorGroupType``, and ``is_none`` / ``set_none()`` for absent-state
handling.  New instances start in the absent state; writing any value via
``__setitem__`` automatically transitions to the present state.

``TensorGroup`` inherits from ``OptionalTensorGroup`` and locks
``is_none`` to ``False`` / ``set_none()`` to raise ``TypeError``, making it
the required (non-optional) variant.
"""

from typing import List, Any
from .tensor_group_type import TensorGroupType
from .tensor import Tensor


class OptionalTensorGroup:
    """A group of tensors that can represent an absent (None-like) state.

    Used for inputs/outputs declared with ``OptionalType()`` in the spec.
    New instances start absent; writing a value via ``__setitem__``
    automatically makes the group present.  When absent, ``__getitem__``
    raises ``ValueError``.

    This is also the base class for ``TensorGroup`` (the required variant).
    """

    def __init__(self, group_type: TensorGroupType) -> None:
        """
        Initialize an optional tensor group in the absent state.

        Tensors are pre-allocated but the group starts absent (``is_none``
        is ``True``).  Writing any value via ``__setitem__`` automatically
        transitions to the present state.

        If *group_type* is an ``OptionalTensorGroupType``, the inner
        (unwrapped) type is stored — optionality is a spec-level concept,
        not a data-level one.

        Args:
            group_type: The TensorGroupType defining the structure
        """
        self._group_type = group_type.inner_type
        self._is_none = True

        self._tensors: List[Tensor] = [
            Tensor(tensor_type) for tensor_type in self._group_type.types
        ]

    @property
    def group_type(self) -> TensorGroupType:
        """Get the associated group type."""
        return self._group_type

    @property
    def is_none(self) -> bool:
        """Whether this group is in the absent state."""
        return self._is_none

    def set_none(self) -> None:
        """Mark this group as absent (no data available)."""
        self._is_none = True

    def __len__(self) -> int:
        """Get the number of tensors in the group."""
        return len(self._tensors)

    def __getitem__(self, index: int) -> Any:
        """
        Get a tensor value by index.

        Args:
            index: Integer index

        Returns:
            The tensor value (with optional runtime validation)

        Raises:
            ValueError: If the group is absent or tensor value has not been set
        """
        if self.is_none:
            raise ValueError(
                f"Cannot read from absent OptionalTensorGroup '{self._group_type.name}'"
            )
        return self._tensors[index].value

    def __setitem__(self, index: int, value: Any) -> None:
        """
        Set a tensor value by index.

        Writing to an absent group automatically marks it as present.

        Args:
            index: Integer index
            value: The value to set (validated against tensor type)

        Raises:
            TypeError: If value doesn't validate against the tensor type
        """
        self._is_none = False
        self._tensors[index].value = value

    def get_tensor(self, index: int) -> Tensor:
        """
        Get the Tensor object (not just the value) by index.

        This is useful if you need access to the tensor type or want to
        pass the tensor around without unwrapping.

        Args:
            index: Integer index

        Returns:
            The Tensor object
        """
        return self._tensors[index]

    def __repr__(self) -> str:
        if self._is_none:
            return f"OptionalTensorGroup({self._group_type.name}, absent)"
        return f"OptionalTensorGroup({self._group_type.name}, {len(self)} tensors)"


class TensorGroup(OptionalTensorGroup):
    """A required (non-optional) group of tensors.

    Inherits all data storage from ``OptionalTensorGroup`` but locks
    ``is_none`` to ``False`` and ``set_none()`` to raise ``TypeError``.

    Standard types use ``TensorGroup`` for required fields.
    """

    @property
    def is_none(self) -> bool:
        """Always ``False`` — a required group is never absent."""
        return False

    def set_none(self) -> None:
        """Raises ``TypeError`` — a required group cannot be marked absent."""
        raise TypeError(
            "Cannot set_none on a required TensorGroup. "
            "Use OptionalTensorGroup for optional outputs."
        )

    def __repr__(self) -> str:
        return f"TensorGroup({self._group_type.name}, {len(self)} tensors)"
