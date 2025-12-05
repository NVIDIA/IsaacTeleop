"""
Abstract Retargeter Node.

A RetargeterNode defines a transformation from input tensor collections to output tensor collections.
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from .tensor_collection import TensorCollection
from .tensor_group import TensorGroup
from .output_selector import OutputSelector


class RetargeterNode(ABC):
    """
    Abstract base class for retargeter nodes.
    
    A retargeter node defines:
    - Input tensor collections (metadata for graph building)
    - Output tensor collections (metadata for graph building)
    - Transform logic using index-based access for fast execution
    """
    
    def __init__(self, name: str = "retargeter") -> None:
        """Initialize the retargeter node.
        
        Args:
            name: Name identifier for this retargeter (useful for debugging)
        """
        self._name = name
        # Get collections from subclass
        self._input_collections: List[TensorCollection] = self._define_inputs()
        self._output_collections: List[TensorCollection] = self._define_outputs()
        
        # Input selectors are set via connect() method
        self._input_selectors: List[OutputSelector] = []
    
    @property
    def name(self) -> str:
        """Get the name of this retargeter node."""
        return self._name
    
    def connect(self, inputs: List[OutputSelector]) -> None:
        """
        Connect this node to its input sources.
        
        Args:
            inputs: List of OutputSelector instances to bind as inputs.
        """
        if len(inputs) != self.num_inputs:
            raise ValueError(
                f"{self.__class__.__name__} expects {self.num_inputs} inputs "
                f"but {len(inputs)} were provided"
            )
        
        for i, selector in enumerate(inputs):
            if not isinstance(selector, OutputSelector):
                raise TypeError(
                    f"Input {i}: Expected OutputSelector, got {type(selector).__name__}"
                )
            
            source_collection = selector.node.get_output_collection(selector.output_index)
            expected_collection = self._input_collections[i]
            
            if not expected_collection.is_compatible_with(source_collection):
                reason = expected_collection.get_incompatibility_reason(source_collection)
                raise ValueError(
                    f"Input {i}: Type mismatch.\n"
                    f"  Source: {selector.node.__class__.__name__}.output[{selector.output_index}] "
                    f"(collection '{source_collection.name}')\n"
                    f"  Expected: {expected_collection.name}\n"
                    f"  Reason: {reason}"
                )
        
        self._input_selectors = list(inputs)
    
    @abstractmethod
    def _define_inputs(self) -> List[TensorCollection]:
        """
        Define input tensor collections.
        
        Returns:
            List of input TensorCollections
        """
        pass
    
    @abstractmethod
    def _define_outputs(self) -> List[TensorCollection]:
        """
        Define output tensor collections.
        
        Returns:
            List of output TensorCollections
        """
        pass
    
    @abstractmethod
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup], output_mask: Optional[List[bool]] = None) -> None:
        """
        Execute the retargeting transformation.
        
        Pure index-based execution for performance.
        Output groups are pre-allocated by caller and reused across executions.
        
        Args:
            inputs: List of input TensorGroups (ordered by define order)
            outputs: List of output TensorGroups (pre-allocated, ordered by define order)
                     This method writes results directly into these groups.
            output_mask: Optional mask indicating which output collections to compute.
                        If provided, should be a list of bools where True means
                        compute this output collection. If None, compute all outputs.
        """
        pass
    
    @property
    def input_selectors(self) -> List[OutputSelector]:
        """Get the input selectors for this node."""
        return self._input_selectors
    
    def get_output_collection(self, index: int) -> TensorCollection:
        """Get an output collection by index."""
        return self._output_collections[index]
    
    @property
    def num_inputs(self) -> int:
        """Get number of input collections."""
        return len(self._input_collections)
    
    @property
    def num_outputs(self) -> int:
        """Get number of output collections."""
        return len(self._output_collections)
    
    def output(self, index: int) -> OutputSelector:
        """
        Create an OutputSelector for a specific output collection.
        
        Args:
            index: The output collection index
        
        Returns:
            OutputSelector representing this output
        
        Raises:
            IndexError: If index is out of range
        """
        if index < 0 or index >= self.num_outputs:
            raise IndexError(
                f"Output index {index} out of range for {self.__class__.__name__} "
                f"(has {self.num_outputs} outputs)"
            )
        return OutputSelector(self, index)
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(inputs={self.num_inputs}, outputs={self.num_outputs})"

