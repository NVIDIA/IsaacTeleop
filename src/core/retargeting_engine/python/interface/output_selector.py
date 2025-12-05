"""
OutputSelector - Represents a connection point from a node output.

This abstraction allows semantic binding between nodes without using numeric indices.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .retargeter_node import RetargeterNode


class OutputSelector:
    """
    Represents a specific output from a RetargeterNode (including InputNodes).
    
    This provides a semantic way to reference outputs when building computation graphs,
    abstracting away the numeric output index.
    """
    
    def __init__(self, node: 'RetargeterNode', output_index: int) -> None:
        """
        Create an output selector.
        
        Args:
            node: The RetargeterNode this output comes from
            output_index: The index of the output collection
        """
        self._node = node
        self._output_index = output_index
    
    @property
    def node(self) -> 'RetargeterNode':
        """Get the source node."""
        return self._node
    
    @property
    def output_index(self) -> int:
        """Get the output collection index."""
        return self._output_index
    
    def __repr__(self) -> str:
        return f"OutputSelector({self._node.__class__.__name__}.output[{self._output_index}])"



