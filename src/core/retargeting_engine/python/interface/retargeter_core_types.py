from abc import ABC, abstractmethod
from typing import Dict, List

from .tensor_group_type import TensorGroupType
from .tensor_group import TensorGroup


RetargeterIOType = Dict[str, TensorGroupType]
RetargeterIO = Dict[str, TensorGroup]



class ExecutionContext:
    def __init__(self, leaf_inputs: Dict[str, RetargeterIO]):
        self.leaf_inputs: Dict[str, RetargeterIO] = leaf_inputs
        self.cached_outputs: Dict[int, RetargeterIO] = {}

    def get_cached(self, id: int) -> RetargeterIO | None:
        return self.cached_outputs.get(id, None)

    def cache(self, id: int, outputs: RetargeterIO) -> None:
        self.cached_outputs[id] = outputs

    def get_leaf_input(self, name: str) -> RetargeterIO | None:
        return self.leaf_inputs.get(name, None)

class OutputSelector:
    def __init__(self, module: 'GraphExecutable', output_name: str):
        self.module = module
        self.output_name = output_name

class BaseExecutable(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Get the name of this executable."""
        pass

    @abstractmethod
    def _compute_without_context(self, inputs: RetargeterIO) -> RetargeterIO:
        """
        Compute the transformation from inputs to outputs.

        Args:
            inputs: Dict[str, TensorGroup] - Input tensor groups
            outputs: Dict[str, TensorGroup] - Output tensor groups (pre-allocated, to be filled)
        """
        pass

class GraphExecutable(ABC):
    """
    Protocol for retargeter subgraphs that can be executed in a graph context.
    """
    @abstractmethod
    def _compute_in_graph(self, context: ExecutionContext) -> RetargeterIO:
        pass

    @abstractmethod
    def output_types(self) -> RetargeterIOType:
        """
        Return the output type specification for this executable.

        Returns:
            Dict[str, TensorGroupType] - Output type specification
        """
        pass

    def output(self, output_name: str) -> OutputSelector:
        return OutputSelector(self, output_name)

    @abstractmethod
    def get_leaf_nodes(self) -> List['BaseExecutable']:
        """
        Get all leaf nodes (sources) in this graph.

        Returns:
            List[BaseExecutable] - List of module instances that are leaf nodes (sources)
        """
        pass