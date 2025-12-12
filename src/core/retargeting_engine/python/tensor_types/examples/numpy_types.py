"""
NumPy array tensor types for the retargeting engine.

Provides support for NumPy arrays with dtype and shape constraints.
"""

from typing import Any, Optional, Tuple, Union
import numpy as np
import numpy.typing as npt
from ...interface.tensor_type import TensorType


class NumpyArrayType(TensorType):
    """
    Represents NumPy array tensor types.
    
    Can be subclassed to create specific array types (e.g., Vector3Type, Matrix4x4Type).
    Compatibility is strict - dtype and shape must match exactly.
    """
    
    def __init__(
        self, 
        name: str,
        dtype: Optional[npt.DTypeLike] = None, 
        shape: Optional[Tuple[Optional[int], ...]] = None,
    ) -> None:
        """
        Initialize a NumPy array tensor type.
        
        Args:
            name: Name for this tensor type
            dtype: NumPy dtype (required for strict compatibility)
            shape: Shape tuple (required for strict compatibility)
        """
        self._dtype = dtype
        self._shape = shape
        super().__init__(name)

    def _check_instance_compatibility(self, other: TensorType) -> bool:
        """
        Check instance compatibility for NumPy array types.
        
        Both dtype and shape must match exactly for compatibility.
        """
        if isinstance(other, NumpyArrayType):
            # Exact dtype match required
            if self._dtype != other._dtype:
                return False
            
            # Exact shape match required
            if self._shape != other._shape:
                return False
            
            return True
        return False

    def allocate_default(self) -> Union[npt.NDArray[Any], None]:
        """
        Allocate a default value for NumPy array types.

        Returns:
            A NumPy array filled with zeros if dtype and shape are specified,
            otherwise None
        """
        if self._dtype is not None and self._shape is not None:
            # Create array of zeros with specified dtype and shape
            # Type ignore for numpy's flexible shape/dtype handling
            return np.zeros(self._shape, dtype=self._dtype)  # type: ignore[arg-type]
        else:
            # Cannot allocate without both dtype and shape
            return None

