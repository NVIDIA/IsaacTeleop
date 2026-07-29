# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tunable parameter specification for retargeters.

Provides parameter types that can be exposed through a GUI for real-time tuning.
"""

from abc import ABC, abstractmethod
from typing import Any, List, Optional, Union, Callable
from dataclasses import dataclass
import numpy as np


@dataclass
class ParameterSpec(ABC):
    """Base class for tunable parameter specifications (immutable)."""

    name: str
    description: str
    saveable: bool = True  # Whether this parameter should be saved to config files
    sync_fn: Optional[Callable[[Any], None]] = (
        None  # Optional sync function called when value changes
    )

    @abstractmethod
    def validate(self, value: Any) -> bool:
        """Check if a value is valid for this parameter."""
        pass

    @abstractmethod
    def get_default_value(self) -> Any:
        """Get the default value for this parameter."""
        pass

    @abstractmethod
    def serialize(self, value: Any) -> Any:
        """Serialize a value to a JSON-compatible format."""
        pass

    @abstractmethod
    def deserialize(self, value: Any) -> Any:
        """Deserialize a value from a JSON-compatible format."""
        pass


@dataclass
class BoolParameter(ParameterSpec):
    """Boolean parameter specification (immutable)."""

    default_value: bool = False

    def validate(self, value: Any) -> bool:
        return isinstance(value, bool)

    def get_default_value(self) -> bool:
        return self.default_value

    def serialize(self, value: bool) -> bool:
        """Serialize to JSON-compatible format."""
        return bool(value)

    def deserialize(self, value: Any) -> bool:
        """Deserialize from JSON-compatible format."""
        return bool(value)


@dataclass
class FloatParameter(ParameterSpec):
    """Float parameter specification with bounded range (immutable)."""

    default_value: float = 0.0
    min_value: float = -float("inf")
    max_value: float = float("inf")
    step_size: float = 0.01

    def __post_init__(self):
        # Validate bounds
        if self.min_value >= self.max_value:
            raise ValueError(f"min_value must be less than max_value for '{self.name}'")

    def validate(self, value: Any) -> bool:
        if not isinstance(value, (int, float)):
            return False
        if value < self.min_value:
            return False
        if value > self.max_value:
            return False
        return True

    def get_default_value(self) -> float:
        return self.default_value

    def is_bounded(self) -> bool:
        """Check if this parameter has finite bounds."""
        return self.min_value != -float("inf") and self.max_value != float("inf")

    def serialize(self, value: float) -> float:
        """Serialize to JSON-compatible format."""
        return float(value)

    def deserialize(self, value: Any) -> float:
        """Deserialize from JSON-compatible format."""
        return float(value)


@dataclass
class IntParameter(ParameterSpec):
    """Integer parameter specification with bounded range (immutable)."""

    default_value: int = 0
    min_value: int = -2147483648  # INT32_MIN
    max_value: int = 2147483647  # INT32_MAX
    step_size: int = 1

    def __post_init__(self):
        # Validate bounds
        if self.min_value >= self.max_value:
            raise ValueError(f"min_value must be less than max_value for '{self.name}'")

    def validate(self, value: Any) -> bool:
        if not isinstance(value, int):
            return False
        if value < self.min_value:
            return False
        if value > self.max_value:
            return False
        return True

    def get_default_value(self) -> int:
        return self.default_value

    def is_bounded(self) -> bool:
        """Check if this parameter has reasonable bounds."""
        return self.min_value != -2147483648 and self.max_value != 2147483647

    def serialize(self, value: int) -> int:
        """Serialize to JSON-compatible format."""
        return int(value)

    def deserialize(self, value: Any) -> int:
        """Deserialize from JSON-compatible format."""
        return int(value)


@dataclass
class VectorParameter(ParameterSpec):
    """N-dimensional vector parameter with named elements and optional bounds (immutable)."""

    element_names: Optional[List[str]] = (
        None  # Required but given default for dataclass ordering
    )
    default_value: Optional[np.ndarray] = None
    min_value: Optional[Union[float, np.ndarray]] = None
    max_value: Optional[Union[float, np.ndarray]] = None
    step_size: Union[float, np.ndarray] = 0.01

    def __post_init__(self):
        # Validate required fields
        if self.element_names is None:
            raise ValueError("element_names is required for VectorParameter")

        # Initialize default value if not provided
        if self.default_value is None:
            object.__setattr__(
                self,
                "default_value",
                np.zeros(len(self.element_names), dtype=np.float32),
            )

        # Convert to numpy array if needed
        if not isinstance(self.default_value, np.ndarray):
            object.__setattr__(
                self, "default_value", np.array(self.default_value, dtype=np.float32)
            )

        # At this point, default_value is definitely an ndarray
        assert isinstance(self.default_value, np.ndarray)

        # Validate dimensions
        if len(self.default_value) != len(self.element_names):
            raise ValueError(
                f"default_value length ({len(self.default_value)}) doesn't match "
                f"element_names length ({len(self.element_names)}) for '{self.name}'"
            )

        # Convert bounds to arrays if they are scalars
        if self.min_value is not None and not isinstance(self.min_value, np.ndarray):
            object.__setattr__(
                self,
                "min_value",
                np.full(len(self.element_names), self.min_value, dtype=np.float32),
            )

        if self.max_value is not None and not isinstance(self.max_value, np.ndarray):
            object.__setattr__(
                self,
                "max_value",
                np.full(len(self.element_names), self.max_value, dtype=np.float32),
            )

        if not isinstance(self.step_size, np.ndarray):
            object.__setattr__(
                self,
                "step_size",
                np.full(len(self.element_names), self.step_size, dtype=np.float32),
            )

        # Validate bounds
        if self.min_value is not None and self.max_value is not None:
            if np.any(self.min_value >= self.max_value):
                raise ValueError(
                    f"All min_value elements must be less than max_value for '{self.name}'"
                )

    def get_default_value(self) -> np.ndarray:
        assert self.default_value is not None, "default_value should be initialized"
        return self.default_value.copy()

    def validate(self, value: Union[np.ndarray, List[float]]) -> bool:
        if not isinstance(value, (np.ndarray, list)):
            return False

        if isinstance(value, list):
            value = np.array(value)

        assert self.element_names is not None, "element_names should be initialized"
        if len(value) != len(self.element_names):
            return False

        if self.min_value is not None and np.any(value < self.min_value):
            return False

        if self.max_value is not None and np.any(value > self.max_value):
            return False

        return True

    def is_bounded(self) -> bool:
        """Check if this parameter has bounds."""
        return self.min_value is not None and self.max_value is not None

    def __len__(self) -> int:
        """Return the number of elements in this vector."""
        assert self.element_names is not None, "element_names should be initialized"
        return len(self.element_names)

    def serialize(self, value: np.ndarray) -> List[float]:
        """Serialize to JSON-compatible format."""
        if isinstance(value, list):
            return value
        return list(value.tolist())

    def deserialize(self, value: Any) -> np.ndarray:
        """Deserialize from JSON-compatible format."""
        if isinstance(value, list):
            return np.array(value, dtype=np.float32)
        else:
            return np.array(value, dtype=np.float32)
