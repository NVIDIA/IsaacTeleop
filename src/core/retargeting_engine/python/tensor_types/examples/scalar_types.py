"""
Scalar tensor types for the retargeting engine.

Provides basic scalar types: bool, int, float.
"""

from typing import Any
from ...interface.tensor_type import TensorType


class ScalarType(TensorType):
    """
    Base class for scalar tensor types.
    
    Subclass this to create specific scalar types like BoolType, IntType, FloatType.
    Compatibility is strict - only exact type matches are compatible.
    """
    
    def __init__(self, dtype: type, name: str) -> None:
        """
        Initialize a scalar tensor type.
        
        Args:
            dtype: The Python type (bool, int, float)
            name: Name for this tensor type
        """
        self._dtype = dtype
        super().__init__(name)

    def _check_instance_compatibility(self, other: TensorType) -> bool:
        """
        Check instance compatibility for scalar types.
        
        Scalar types with the same dtype are compatible.
        """
        if isinstance(other, ScalarType):
            return self._dtype == other._dtype
        return False

    def allocate_default(self) -> Any:
        """
        Allocate a default value for scalar types.

        Returns:
            Default value by calling the type constructor
        """
        return self._dtype()


class BoolType(ScalarType):
    """Boolean tensor type. Only compatible with other BoolType instances."""
    
    def __init__(self, name: str) -> None:
        super().__init__(bool, name)


class IntType(ScalarType):
    """Integer tensor type. Only compatible with other IntType instances."""
    
    def __init__(self, name: str) -> None:
        super().__init__(int, name)


class FloatType(ScalarType):
    """Float tensor type. Only compatible with other FloatType instances."""
    
    def __init__(self, name: str) -> None:
        super().__init__(float, name)

