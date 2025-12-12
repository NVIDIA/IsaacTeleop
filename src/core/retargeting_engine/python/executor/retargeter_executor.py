"""
RetargeterExecutor - Orchestrates data flow in a retargeter computation graph.

The executor manages connections between retargeter nodes in a computation graph,
compiles the execution order via topological sort, and executes the graph efficiently.
"""

from typing import List, Tuple, Dict, Set, Any
from collections import deque
from ..interface.retargeter_node import RetargeterNode
from ..interface.tensor_group import TensorGroup


class RetargeterExecutor:
    """
    Executor that orchestrates data flow in a retargeter computation graph.
    
    The executor:
    - Automatically discovers the graph from output nodes
    - Compiles the execution order via topological sort
    - Maintains one output buffer per node (shared across all consumers)
    - Executes the graph efficiently
    """
    
    def __init__(self, output_nodes: List[RetargeterNode]) -> None:
        """
        Initialize and compile the retargeter executor with output nodes.
        
        Automatically discovers the computation graph by traversing backwards from
        output nodes, then compiles the execution order via topological sort.
        
        Args:
            output_nodes: List of RetargeterNode instances (including InputNodes)
                         that represent the outputs of the computation graph.
        
        Raises:
            ValueError: If no output nodes provided or graph has issues (cycles, etc.)
        """
        if not output_nodes:
            raise ValueError("At least one output node must be provided")
        
        # Store output nodes
        self._output_nodes: List[RetargeterNode] = output_nodes
        
        # All nodes in the graph
        self._nodes: Set[RetargeterNode] = set()
        
        # Output buffers: one per node
        # Map: Node -> List[TensorGroup] (one per output collection)
        self._node_outputs: Dict[RetargeterNode, List[TensorGroup]] = {}
        
        # Bindings: Map from RetargeterNode to its input sources
        # Each source is (source_node, output_index)
        self._bindings: Dict[RetargeterNode, List[Tuple[RetargeterNode, int]]] = {}
        
        # Dependency graph for topological sort
        # Map: Node -> Set[Node] (nodes that depend on this node)
        self._dependents: Dict[RetargeterNode, Set[RetargeterNode]] = {}
        
        # Reverse dependency: Map: Node -> Set[Node] (nodes this node depends on)
        self._dependencies: Dict[RetargeterNode, Set[RetargeterNode]] = {}
        
        # Discover and register the graph
        self._discover_graph(output_nodes)
        
        # Build dependency graph and compile execution order
        self._build_dependency_graph()
        self._execution_order: List[RetargeterNode] = self._topological_sort()
    
    def _discover_graph(self, output_nodes: List[RetargeterNode]) -> None:
        """
        Discover and register the computation graph from output nodes.
        
        Traverses backwards from output nodes through their input selectors
        to find all nodes in the graph.
        
        Args:
            output_nodes: List of output nodes to start traversal from
        """
        # Traverse graph from output nodes
        to_visit: Set[RetargeterNode] = set(output_nodes)
        visited: Set[RetargeterNode] = set()
        
        while to_visit:
            node = to_visit.pop()
            
            if node in visited:
                continue
            
            visited.add(node)
            self._nodes.add(node)
            
            # Create output buffer if not exists
            if node not in self._node_outputs:
                self._node_outputs[node] = [
                    TensorGroup(collection)
                    for collection in node._output_collections
                ]
            
            # Create binding from input selectors
            input_sources = [
                (selector.node, selector.output_index)
                for selector in node.input_selectors
            ]
            
            # Store binding
            if node not in self._bindings:
                self._bindings[node] = input_sources
            
            # Add input nodes to visit queue
            for selector in node.input_selectors:
                to_visit.add(selector.node)
    
    def _build_dependency_graph(self) -> None:
        """Build the dependency graph from bindings."""
        # Reset dependency tracking
        self._dependents.clear()
        self._dependencies.clear()
        
        # Initialize all nodes
        for node in self._nodes:
            self._dependents[node] = set()
            self._dependencies[node] = set()
        
        # Build dependencies from bindings
        for retargeter, input_sources in self._bindings.items():
            for source_node, _ in input_sources:
                # source_node must execute before retargeter
                self._dependents[source_node].add(retargeter)
                self._dependencies[retargeter].add(source_node)
    
    def _topological_sort(self) -> List[RetargeterNode]:
        """
        Perform topological sort using Kahn's algorithm.
        
        Returns:
            List of nodes in execution order
        
        Raises:
            ValueError: If the graph has cycles
        """
        # Count in-degrees (number of dependencies)
        in_degree: Dict[RetargeterNode, int] = {
            node: len(self._dependencies[node])
            for node in self._nodes
        }
        
        # Queue of nodes with no dependencies (can execute immediately)
        queue: deque[RetargeterNode] = deque([
            node for node in self._nodes if in_degree[node] == 0
        ])
        
        # Result: execution order
        execution_order: List[RetargeterNode] = []
        
        # Process queue
        while queue:
            # Get a node with no remaining dependencies
            node = queue.popleft()
            execution_order.append(node)
            
            # Reduce in-degree of dependent nodes
            for dependent in self._dependents[node]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        
        # Check for cycles
        if len(execution_order) != len(self._nodes):
            # Some nodes weren't processed - there's a cycle
            unprocessed = [
                node.__class__.__name__
                for node in self._nodes
                if node not in execution_order
            ]
            raise ValueError(
                f"Computation graph has cycles. Could not process nodes: {unprocessed}"
            )
        
        return execution_order
    
    def execute(self) -> None:
        """
        Execute the computation graph in compiled order.
        
        Executes all nodes (including InputNodes) in topologically sorted order.
        """
        # Execute nodes in order
        for node in self._execution_order:
            # Get input groups from source nodes
            input_sources = self._bindings[node]
            input_groups = [
                self._node_outputs[source_node][output_idx]
                for source_node, output_idx in input_sources
            ]
            
            # Get output groups (shared buffer)
            output_groups = self._node_outputs[node]
            
            # Execute (InputNodes have empty inputs list)
            node.execute(inputs=input_groups, outputs=output_groups)
    
    def get_outputs(self, node: RetargeterNode) -> List[TensorGroup]:
        """
        Get the output tensor groups for a node.
        
        Args:
            node: The RetargeterNode (or InputNode) to get outputs for
        
        Returns:
            List of output TensorGroups from the node
        
        Raises:
            KeyError: If node is not registered
        """
        if node not in self._node_outputs:
            raise KeyError(
                f"Node {node.__class__.__name__} is not registered with this executor"
            )
        
        return self._node_outputs[node]
    
    def get_output(self, node: RetargeterNode, index: int) -> TensorGroup:
        """
        Get a specific output tensor group from a node.
        
        Args:
            node: The RetargeterNode to get output from
            index: The output collection index
        
        Returns:
            The output TensorGroup
        
        Raises:
            KeyError: If node is not registered
            IndexError: If index is out of range
        """
        outputs = self.get_outputs(node)
        return outputs[index]
    
    @property
    def num_nodes(self) -> int:
        """Get the total number of nodes in the graph."""
        return len(self._nodes)
    
    def get_output_results(self) -> List[List[Any]]:
        """
        Get the output values from all output nodes.
        
        Returns:
            List of lists, where each inner list contains the tensor values 
            from one output node's collections.
        """
        results = []
        for output_node in self._output_nodes:
            node_outputs = self._node_outputs[output_node]
            # Each output node has multiple collections, get values from all
            node_result = [group.values() for group in node_outputs]
            results.append(node_result)
        return results
    
    def __repr__(self) -> str:
        return f"RetargeterExecutor(nodes={self.num_nodes})"

