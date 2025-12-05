"""
Tensor Type System for Retargeting Engine

This module provides the base abstract class for tensor types.
Specific tensor type implementations are defined in the types/ directory.
"""

from abc import ABC, abstractmethod
from typing import Any


class TensorType(ABC):
    """
    Abstract base class for tensor types.
    
    All tensor types must inherit from this class and implement
    the required methods for type checking and compatibility.
    
    Adding a new tensor type is as simple as creating a new class
    that inherits from TensorType or one of its subclasses.
    """
    
    def __init__(self, name: str) -> None:
        """
        Initialize a tensor type.
        
        Args:
            name: Name for this tensor type (required)
        """
        self._name = name
    
    @property
    def name(self) -> str:
        """Get the name of this tensor type."""
        return self._name
    
    def is_compatible_with(self, other: 'TensorType') -> bool:
        """
        Check if this tensor type is compatible with another.

        First checks if the types are the same class, then checks instance compatibility.

        Args:
            other: Another tensor type to check compatibility with

        Returns:
            True if the types are compatible, False otherwise
        """
        # First check: must be the same class
        if type(self) != type(other):
            return False
        
        # Second check: instance-level compatibility
        return self._check_instance_compatibility(other)
    
    @abstractmethod
    def _check_instance_compatibility(self, other: 'TensorType') -> bool:
        """
        Check if this instance is compatible with another instance of the same class.
        
        This is called after verifying that both instances are the same class type.
        Subclasses should implement their specific compatibility logic here.
        
        Args:
            other: Another tensor type of the same class
            
        Returns:
            True if the instances are compatible, False otherwise
        """
        pass

    @abstractmethod
    def allocate_default(self) -> Any:
        """
        Allocate a default value for this tensor type.

        This provides the initial value for tensors when using direct assignment mode,
        ensuring tensors are never None/null.

        Returns:
            A default value appropriate for this tensor type
        """
        pass
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self._name}')"
