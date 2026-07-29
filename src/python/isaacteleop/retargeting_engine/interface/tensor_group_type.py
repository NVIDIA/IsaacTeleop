# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tensor Group Type for type metadata.

A TensorGroupType defines the types and structure of a group of tensors.
Supports an Optional wrapper to indicate that a tensor group may be absent
at runtime (e.g., when a tracker is inactive).
"""

from typing import List
from .tensor_type import TensorType


class TensorGroupType:
    """
    Defines the type metadata for a collection of tensors.

    Used for building compute graphs. Does not hold actual data.
    """

    def __init__(self, name: str, tensors: List[TensorType]) -> None:
        """
        Initialize a tensor group type.

        Args:
            name: Name for this group type
            tensors: List of tensor types.
        """
        self._name = name
        self._types: List[TensorType] = list(tensors)

    @property
    def name(self) -> str:
        """Get the name of this group type."""
        return self._name

    @property
    def types(self) -> List[TensorType]:
        """Get the list of tensor types."""
        return self._types

    @property
    def is_optional(self) -> bool:
        """Whether this type is wrapped in Optional."""
        return False

    @property
    def inner_type(self) -> "TensorGroupType":
        """Get the unwrapped type. Returns self for non-optional types."""
        return self

    def __len__(self) -> int:
        """Get the number of tensors in this group."""
        return len(self._types)

    def check_compatibility(self, other: "TensorGroupType"):
        """
        Check if this group type is type-compatible with another.

        Compatibility rules when Optional is involved:
        - Required output -> Required input: OK (check inner types)
        - Required output -> Optional input: OK (check inner types)
        - Optional output -> Optional input: OK (check inner types)
        - Optional output -> Required input: ERROR

        Args:
            other: Another TensorGroupType to check compatibility with.
                   ``self`` is the expected (input) type; ``other`` is the
                   actual (output) type being connected.

        Raises:
            ValueError: If types are incompatible or optionality rules are violated
        """
        # Optionality gate: optional output cannot feed a required input
        if other.is_optional and not self.is_optional:
            raise ValueError(
                f"Cannot connect optional output '{other.name}' to required input "
                f"'{self.name}': declare the input as OptionalType() to accept optional outputs"
            )

        # Unwrap for structural comparison
        self_inner = self.inner_type
        other_inner = other.inner_type

        if len(self_inner) != len(other_inner):
            raise ValueError(
                f"Group type size mismatch: expected {len(self_inner)} tensors, "
                f"got {len(other_inner)} tensors"
            )

        for i, tensor_type in enumerate(self_inner._types):
            other_type = other_inner._types[i]
            if not tensor_type.is_compatible_with(other_type):
                raise ValueError(
                    f"Tensor {i} type mismatch: "
                    f"expected {tensor_type.__class__.__name__} ('{tensor_type.name}'), "
                    f"got {other_type.__class__.__name__} ('{other_type.name}')"
                )

    def __repr__(self) -> str:
        tensor_list = ", ".join(f"{t.name}:{t.__class__.__name__}" for t in self._types)
        return f"TensorGroupType({len(self)} types: {tensor_list})"


class OptionalTensorGroupType(TensorGroupType):
    """
    Wrapper indicating that a TensorGroupType may be absent at runtime.

    At runtime an optional slot holds an ``OptionalTensorGroup``.  When data
    is unavailable the producer calls ``group.set_none()``; consumers check
    ``group.is_none`` before accessing tensor values.

    Use the ``OptionalType()`` factory function to create instances.
    """

    _inner: TensorGroupType

    def __init__(self, inner: TensorGroupType) -> None:
        if isinstance(inner, OptionalTensorGroupType):
            inner = inner._inner
        super().__init__(inner.name, inner.types)
        self._inner = inner

    @property
    def is_optional(self) -> bool:
        return True

    @property
    def inner_type(self) -> TensorGroupType:
        return self._inner

    def __repr__(self) -> str:
        return f"Optional({self._inner!r})"


def OptionalType(tensor_group_type: TensorGroupType) -> OptionalTensorGroupType:
    """
    Mark a TensorGroupType as optional in an input or output spec.

    When used on an **output**, the compute function may call
    ``set_none()`` to signal that data is unavailable.

    When used on an **input**, the retargeter is declaring that it can handle
    absent data and will check ``.is_none`` before accessing the data.

    Compatibility rules:
    - ``Optional output -> Optional input``: allowed
    - ``Required output -> Optional input``: allowed
    - ``Required output -> Required input``: allowed
    - ``Optional output -> Required input``: **rejected at connect() time**

    Args:
        tensor_group_type: The TensorGroupType to wrap.

    Returns:
        An OptionalTensorGroupType wrapping the given type.

    Example::

        def output_spec(self) -> RetargeterIOType:
            return {
                "controller_left": OptionalType(ControllerInput()),
            }

        def input_spec(self) -> RetargeterIOType:
            return {
                "controller_left": OptionalType(ControllerInput()),  # can be absent
                "hand_left": HandInput(),                            # required
            }

        def compute(self, inputs, outputs):
            ctrl = inputs["controller_left"]
            if ctrl.is_none:
                outputs["result"].set_none()
                return
            # ctrl[0], ctrl[1], ... are safe to access here
    """
    if isinstance(tensor_group_type, OptionalTensorGroupType):
        return tensor_group_type
    return OptionalTensorGroupType(tensor_group_type)
