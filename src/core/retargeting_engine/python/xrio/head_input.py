"""
Head Input Node - wraps XRIO HeadTracker.

Converts HeadPose data from XRIO into TensorGroups.
Requires a trigger input from XrioUpdateNode to ensure data freshness.
"""

from typing import Any, List, Optional
import numpy as np
from ..interface.retargeter_node import RetargeterNode
from ..interface.tensor_collection import TensorCollection
from ..interface.tensor_group import TensorGroup
from ..interface.output_selector import OutputSelector
from ..tensor_types.examples.scalar_types import BoolType, IntType
from ..tensor_types.examples.numpy_types import NumpyArrayType


class HeadInput(RetargeterNode):
    """
    Input node for XRIO HeadTracker.
    
    Provides head position, orientation, validity, and timestamp.
    
    This node creates and manages its own HeadTracker instance.
    
    **Important**: Requires a trigger input from XrioUpdateNode to ensure tracker
    data is fresh before reading.
    
    Usage:
        builder = xrio.XrioSessionBuilder()
        xrio_update = XrioUpdateNode(builder, app_name="MyApp")
        head = HeadInput(builder, trigger=xrio_update.trigger())
    """
    
    def __init__(self, xrio_session_builder: Any, name: str = "head") -> None:
        """
        Initialize head input node and create HeadTracker.
        
        Args:
            xrio_session_builder: xrio.XrioSessionBuilder to register the tracker with
            name: Name identifier for this input (default: "head")
        """
        # Import xrio and create tracker
        import teleopcore.xrio as xrio
        
        # Create and register tracker
        self._head_tracker = xrio.HeadTracker()
        xrio_session_builder.add_tracker(self._head_tracker)
        
        super().__init__(name)
    
    def connect_trigger(self, trigger: OutputSelector) -> None:
        """
        Connect the head input to its trigger source.
        
        Args:
            trigger: OutputSelector from XrioUpdateNode to ensure data freshness
        """
        self.connect([trigger])
    
    def _define_inputs(self) -> List[TensorCollection]:
        """Define trigger input from XrioUpdateNode."""
        return [
            TensorCollection("trigger", [
                BoolType("update_success")
            ])
        ]
    
    def _define_outputs(self) -> List[TensorCollection]:
        """Define head input output structure."""
        return [TensorCollection(self._name, [
            NumpyArrayType("head_position", dtype=np.dtype('float32'), shape=(3,)),
            NumpyArrayType("head_orientation", dtype=np.dtype('float32'), shape=(4,)),
            BoolType("head_is_valid"),
            IntType("head_timestamp"),
        ])]
    
    def execute(self, inputs: List[TensorGroup], outputs: List[TensorGroup], output_mask: Optional[List[bool]] = None) -> None:
        """
        Read head tracking data from XRIO tracker.
        
        Args:
            inputs: List with one TensorGroup containing the trigger signal
            outputs: List with one TensorGroup for head data
            output_mask: Optional mask for which outputs to compute
        """
        # Trigger is in inputs[0], but we don't need to check it - 
        # the fact that we're executing means the dependency was satisfied
        
        output = outputs[0]
        head_pose = self._head_tracker.get_head()
        
        # Convert to numpy arrays
        position = np.array(head_pose.position, dtype=np.float32)
        orientation = np.array(head_pose.orientation, dtype=np.float32)
        
        # Update using index-based access
        output[0] = position
        output[1] = orientation
        output[2] = head_pose.is_valid
        output[3] = int(head_pose.timestamp)

