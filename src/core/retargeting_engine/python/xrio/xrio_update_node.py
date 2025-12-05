"""
XRIO Update Node - triggers XRIO session updates.

A specialized InputNode that calls xrio_session.update() and provides
a trigger signal for downstream operators. Lazily builds the XRIO session
from a builder when first executed.
"""

from typing import Any, List, Optional
import teleopcore.xrio as xrio
from ..interface.input_node import InputNode
from ..interface.tensor_collection import TensorCollection
from ..interface.tensor_group import TensorGroup
from ..interface.output_selector import OutputSelector
from ..tensor_types.examples.scalar_types import BoolType


class XrioUpdateNode(InputNode):
    """
    Input node that triggers XRIO session updates.
    
    This node builds the XRIO session lazily from a builder and calls 
    xrio_session.update() on each execution, outputting a boolean trigger
    signal indicating success. It serves as the synchronization point
    in a retargeting pipeline, ensuring tracker data is fresh before
    downstream nodes execute.
    
    **Important**: All other XRIO input nodes (ControllersInput, HandsInput, 
    HeadInput, etc.) should take trigger=xrio_update.trigger() in their
    constructors to ensure they only read tracker data AFTER xrio_session.update()
    has refreshed it.
    
    Outputs:
        - trigger: Boolean indicating successful XRIO update
    
    Usage:
        # Simple case - XrioUpdateNode creates its own OpenXR session:
        builder = xrio.XrioSessionBuilder()
        xrio_update = XrioUpdateNode(builder, app_name="MyApp")
        controllers = ControllersInput(builder)
        controllers.connect_trigger(xrio_update.trigger())
        gripper = GripperRetargeter()
        gripper.connect_controllers(controllers.left(), controllers.right())
        executor = RetargeterExecutor([gripper])
        
        # Just use it - sessions build on first execute(), cleanup automatic
        for _ in range(100):
            executor.execute()
        
        # Advanced case - You manage OpenXR session (e.g., for custom extensions):
        builder = xrio.XrioSessionBuilder()
        xrio_update = XrioUpdateNode(builder, app_name="MyApp")
        controllers = ControllersInput(builder)
        controllers.connect_trigger(xrio_update.trigger())
        
        oxr_session = oxr.OpenXRSession.create("MyApp", custom_extensions)
        with oxr_session:
            xrio_update.set_oxr_handles(oxr_session.get_handles())
            executor.execute()
        
        # In Holoscan:
        xrio_update = XrioUpdateNode(builder, app_name="HoloscanApp")
        update_op = SourceOperator(app, xrio_update, name="xrio_update")
        controllers_op = RetargeterOperator(app, controllers, name="controllers")
        app.add_flow(update_op, controllers_op, {("trigger", "trigger")})
    """
    
    def __init__(self, xrio_session_builder: Any, app_name: str = "TeleopApp", 
                 name: str = "xrio_update") -> None:
        """
        Initialize XRIO update node.
        
        Args:
            xrio_session_builder: xrio.XrioSessionBuilder (will be built lazily)
            app_name: Application name for OpenXR session (default: "TeleopApp").
                      Only used when creating an internal OpenXR session.
                      Ignored if set_oxr_handles() is called with external handles.
            name: Name identifier for this node (default: "xrio_update")
        """
        self._builder = xrio_session_builder
        self._oxr_handles: Optional[Any] = None
        self._app_name = app_name
        self._xrio_session: Optional[Any] = None
        self._oxr_session: Optional[Any] = None  # Only set if we create our own
        super().__init__(name)
    
    def set_oxr_handles(self, oxr_handles: Any) -> None:
        """
        Set OpenXR handles for this node to use.
        
        Must be called before first execute() if you want to use an external OpenXR session.
        
        Args:
            oxr_handles: OpenXR handles from oxr_session.get_handles()
        
        Raises:
            RuntimeError: If XRIO session has already been built
        """
        if self._xrio_session is not None:
            raise RuntimeError("Cannot set OpenXR handles after XRIO session has been built")
        self._oxr_handles = oxr_handles
    
    def _define_outputs(self) -> List[TensorCollection]:
        """Define single trigger output."""
        return [
            TensorCollection("trigger", [
                BoolType("update_success")
            ])
        ]
    
    def _build_session_if_needed(self) -> bool:
        """
        Lazily build the XRIO session if not already built.
        Creates its own OpenXR session if handles weren't provided.
        
        Returns:
            True if session is ready, False on failure
        """
        if self._xrio_session is not None:
            return True
        
        # If no handles provided, create our own OpenXR session
        if self._oxr_handles is None:
            try:
                import teleopcore.oxr as oxr
                
                # Get required extensions from the builder
                extensions = self._builder.get_required_extensions()
                
                # Create OpenXR session
                self._oxr_session = oxr.OpenXRSession.create(self._app_name, extensions)
                if self._oxr_session is None:
                    print(f"Failed to create OpenXR session for {self._app_name}")
                    return False
                
                # Enter session context (required by Python bindings)
                self._oxr_session.__enter__()
                
                # Get handles from our session
                self._oxr_handles = self._oxr_session.get_handles()
                
            except Exception as e:
                print(f"Failed to create OpenXR session: {e}")
                return False
        
        # Build the XRIO session
        self._xrio_session = self._builder.build(self._oxr_handles)
        if self._xrio_session is None:
            print("Failed to build XRIO session")
            # Clean up OpenXR session if we created it
            if self._oxr_session is not None:
                self._oxr_session.__exit__(None, None, None)
                self._oxr_session = None
            return False
        
        # Enter XRIO session context (required by Python bindings)
        self._xrio_session.__enter__()
        
        return True
    
    def __del__(self) -> None:
        """Destructor - cleanup resources automatically."""
        if self._xrio_session is not None:
            try:
                self._xrio_session.__exit__(None, None, None)
            except Exception as e:
                print(f"Warning: Error while cleaning up XRIO session: {e}")
            self._xrio_session = None
        
        # Clean up OpenXR session only if we created it
        if self._oxr_session is not None:
            try:
                self._oxr_session.__exit__(None, None, None)
            except Exception as e:
                print(f"Warning: Error while cleaning up OpenXR session: {e}")
            self._oxr_session = None
    
    def update(self, outputs: List[TensorGroup]) -> None:
        """
        Build session if needed, call XRIO session update, and output success status.
        
        Args:
            outputs: List containing single TensorGroup for trigger output
        """
        trigger_group = outputs[0]
        
        # Build session on first call if needed (for convenience)
        if not self._build_session_if_needed():
            trigger_group[0] = False
            return
        
        # Update XRIO session (reads all tracker data)
        if self._xrio_session is not None:
            success = self._xrio_session.update()
        else:
            success = False
        
        # Output trigger signal
        trigger_group[0] = success
    
    # Semantic output selector
    def trigger(self) -> OutputSelector:
        """Get the trigger output selector for connecting to other input nodes."""
        return self.output(0)


