"""
Tensor class for the Retargeting Engine.

A Tensor holds actual data. Type information is stored separately in TensorCollection.
"""

from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .tensor_type import TensorType


class Tensor:
    """
    A tensor that holds data.

    Type information is managed separately in TensorCollection.
    This allows the compute graph (types) to be separate from execution (data).
    """

    def __init__(self, tensor_type: 'TensorType') -> None:
        """
        Initialize a tensor with a default value from the type.

        Args:
            tensor_type: Tensor type for default allocation
        """
        self._value = tensor_type.allocate_default()
    
    @property
    def value(self) -> Any:
        """Get the current value."""
        return self._value
    
    @value.setter
    def value(self, new_value: Any) -> None:
        """Set a new value."""
        self._value = new_value
    
    def __repr__(self) -> str:
        value_repr = f"{type(self._value).__name__}" if self._value is not None else "None"
        return f"Tensor(value_type={value_repr})"

