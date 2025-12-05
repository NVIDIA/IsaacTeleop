"""
Holoscan utilities for wrapping retargeting nodes as Holoscan operators.
"""

from typing import Any, List, Optional
from holoscan.core import Operator, OperatorSpec

from ..interface.retargeter_node import RetargeterNode
from ..interface.tensor_group import TensorGroup


class RetargeterOperator(Operator):  # type: ignore[misc]
    """
    Wraps a RetargeterNode as a Holoscan Operator.
    
    This allows retargeting nodes to be used in Holoscan compute graphs.
    
    The operator:
    - Creates input ports for each input collection (using collection names)
    - Creates output ports for each output collection (using collection names)
    - Executes the retargeting node's execute() method
    
    Example:
        # Wrap a gripper retargeter
        gripper = GripperRetargeter(controllers.left(), controllers.right())
        gripper_op = RetargeterOperator(fragment, gripper, name="gripper_op")
        
        # Wrap a controllers input (has trigger input already defined)
        controllers = ControllersInput(builder, trigger=xrio_update.trigger())
        controllers_op = RetargeterOperator(fragment, controllers, name="controllers")
    """
    
    def __init__(self, fragment: Any, retargeter_node: RetargeterNode, name: str = "retargeter") -> None:
        """
        Initialize the retargeter operator.
        
        Args:
            fragment: Holoscan fragment or application
            retargeter_node: RetargeterNode to wrap
            name: Name for this operator
        """
        # Store node and collections BEFORE calling super().__init__()
        # because setup() is called during parent initialization in Holoscan 3.4+
        self._node = retargeter_node
        self._input_collections = retargeter_node._input_collections
        self._output_collections = retargeter_node._output_collections
        
        # Groups will be created in start()
        self._input_groups: Optional[List[TensorGroup]] = None
        self._output_groups: Optional[List[TensorGroup]] = None
        
        # Now call parent init which will trigger setup()
        super().__init__(fragment, name=name)
    
    def setup(self, spec: Any) -> None:
        """
        Setup the operator specification.
        
        Creates input and output ports using collection names.
        """
        # Create input ports using collection names
        for collection in self._input_collections:
            spec.input(collection.name)
        
        # Create output ports using collection names
        for collection in self._output_collections:
            spec.output(collection.name)
    
    def start(self) -> None:
        """
        Start the operator - create tensor groups.
        
        Called when the operator starts executing.
        """
        # Create input/output tensor groups
        self._input_groups = [
            TensorGroup(collection) for collection in self._input_collections
        ]
        self._output_groups = [
            TensorGroup(collection) for collection in self._output_collections
        ]
    
    def stop(self) -> None:
        """
        Stop the operator - cleanup tensor groups.
        
        Called when the operator stops executing.
        """
        # Clear references to tensor groups
        self._input_groups = None
        self._output_groups = None
    
    def compute(self, op_input: Any, op_output: Any, context: Any) -> None:
        """
        Execute the retargeting node.
        
        Reads data from input ports, executes the node, writes to output ports.
        """
        # Ensure groups are initialized
        if self._input_groups is None or self._output_groups is None:
            raise RuntimeError("Operator groups not initialized. start() may not have been called.")
        
        # Read inputs from Holoscan ports using collection names
        for i, collection in enumerate(self._input_collections):
            data = op_input.receive(collection.name)
            if data is not None:
                # Assuming data is a list of tensor values matching the collection
                for j, value in enumerate(data):
                    self._input_groups[i][j] = value
        
        # Execute the retargeting node
        self._node.execute(self._input_groups, self._output_groups)
        
        # Write outputs to Holoscan ports using collection names
        for i, collection in enumerate(self._output_collections):
            # Extract values from the output group
            output_data = self._output_groups[i].values()
            op_output.emit(output_data, collection.name)


def create_retargeter_operator(fragment: Any, retargeter_node: RetargeterNode, name: Optional[str] = None) -> RetargeterOperator:
    """
    Convenience function to create a RetargeterOperator.
    
    Args:
        fragment: Holoscan fragment or application
        retargeter_node: RetargeterNode to wrap
        name: Optional name for the operator (defaults to node's name)
    
    Returns:
        RetargeterOperator wrapping the node
    
    Example:
        gripper_node = GripperRetargeter(...)
        gripper_op = create_retargeter_operator(app, gripper_node)
    """
    if name is None:
        name = retargeter_node.name
    
    return RetargeterOperator(fragment, retargeter_node, name=name)


class SourceOperator(Operator):  # type: ignore[misc]
    """
    Wraps a source RetargeterNode (InputNode with no inputs) as a triggered Holoscan operator.
    
    This operator is designed for source nodes like XrioUpdateNode that generate data
    without consuming inputs. It adds a 'trigger' input port so it can be driven
    by an external ticker or another operator.
    
    Example:
        xrio_update = XrioUpdateNode(builder)
        xrio_op = SourceOperator(app, xrio_update)
        # Connect ticker to drive execution
        app.add_flow(ticker, xrio_op, {("tick", "trigger")})
    """
    
    def __init__(self, fragment: Any, retargeter_node: RetargeterNode, name: Optional[str] = None) -> None:
        """
        Initialize the source operator.
        
        Args:
            fragment: Holoscan fragment or application
            retargeter_node: RetargeterNode to wrap (should have no inputs)
            name: Name for this operator (defaults to node's name)
        """
        # Store node and collections BEFORE calling super().__init__()
        self._node = retargeter_node
        self._input_collections = retargeter_node._input_collections
        self._output_collections = retargeter_node._output_collections
        
        # Verify this is a source node (no inputs)
        if len(self._input_collections) > 0:
            raise ValueError(f"SourceOperator can only wrap source nodes (nodes with no inputs). "
                           f"Node {retargeter_node.name} has {len(self._input_collections)} input(s).")
        
        # Groups will be created in start()
        self._input_groups: List[TensorGroup] = []  # Always empty for source nodes
        self._output_groups: Optional[List[TensorGroup]] = None
        
        # Set name
        if name is None:
            name = retargeter_node.name
            
        # Call parent init
        super().__init__(fragment, name=name)
    
    def setup(self, spec: Any) -> None:
        """
        Setup the operator specification.
        
        Creates 'trigger' input and output ports using collection names.
        """
        # Add trigger input to drive execution
        spec.input("trigger")
        
        # Create output ports using collection names
        for collection in self._output_collections:
            spec.output(collection.name)
    
    def start(self) -> None:
        """
        Start the operator - create output tensor groups.
        
        Called when the operator starts executing.
        """
        # Create output tensor groups
        self._output_groups = [
            TensorGroup(collection) for collection in self._output_collections
        ]
    
    def stop(self) -> None:
        """
        Stop the operator - cleanup tensor groups.
        
        Called when the operator stops executing.
        """
        # Clear references to tensor groups
        self._output_groups = None
    
    def compute(self, op_input: Any, op_output: Any, context: Any) -> None:
        """
        Execute the retargeting node when triggered.
        
        Waits for trigger, executes the node, and writes outputs.
        """
        # Ensure output groups are initialized
        if self._output_groups is None:
            raise RuntimeError("Operator groups not initialized. start() may not have been called.")
        
        # Wait for trigger
        trigger = op_input.receive("trigger")
        if trigger is None:
            return
            
        # Execute the retargeting node (no inputs for source nodes)
        self._node.execute(self._input_groups, self._output_groups)
        
        # Write outputs to Holoscan ports using collection names
        for i, collection in enumerate(self._output_collections):
            # Extract values from the output group
            output_data = self._output_groups[i].values()
            op_output.emit(output_data, collection.name)


def create_source_operator(fragment: Any, retargeter_node: RetargeterNode, name: Optional[str] = None) -> SourceOperator:
    """
    Convenience function to create a SourceOperator.
    
    Args:
        fragment: Holoscan fragment or application
        retargeter_node: Source RetargeterNode to wrap (should have no inputs)
        name: Optional name for the operator (defaults to node's name)
    
    Returns:
        SourceOperator wrapping the node
    """
    return SourceOperator(fragment, retargeter_node, name=name)
