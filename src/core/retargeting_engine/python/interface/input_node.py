"""
Input Node for the Retargeting Engine.

An InputNode is a specialized RetargeterNode with no inputs that provides
source data (e.g., from tracking systems).
"""

from abc import abstractmethod
from typing import List, Optional
from .tensor_collection import TensorCollection
from .tensor_group import TensorGroup
from .retargeter_node import RetargeterNode


class InputNode(RetargeterNode):
    """
    Input node - a RetargeterNode with no inputs.
    
    An InputNode provides source data (e.g., from tracking systems) without
    taking any inputs. It's a specialized RetargeterNode where _define_inputs()
    returns an empty list.
    """
    
    def __init__(self, name: str) -> None:
        """
        Initialize the input node.
        
        Args:
            name: Name identifier for this input node
        """
        super().__init__(name=name)
    
    def _define_inputs(self) -> List[TensorCollection]:
        """Input nodes have no inputs."""
        return []
    
    @abstractmethod
    def update(self, outputs: List[TensorGroup]) -> None:
        """
        Update TensorGroups with current input data.
        
        This method should read from the underlying data source
        (e.g., tracking hardware) and populate the TensorGroups.
        
        Args:
            outputs: List of TensorGroups to populate with current data.
        """
        pass
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup], output_mask: Optional[List[bool]] = None) -> None:
        """
        Execute the input node by calling update().
        
        Args:
            inputs: Empty list (input nodes have no inputs)
            outputs: List of TensorGroups to populate
            output_mask: Ignored for input nodes
        """
        self.update(outputs)


