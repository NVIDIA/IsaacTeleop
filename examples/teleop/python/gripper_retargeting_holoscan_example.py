#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Gripper Retargeting Example with Holoscan

Demonstrates using RetargeterOperator to wrap retargeting nodes in a Holoscan application.
Uses manual setup without TeleopSession for full control over the Holoscan pipeline.

**Note**: This example requires Holoscan SDK with CUDA support.
Install with: pip install teleopcore[holoscan]
or: uv pip install teleopcore[holoscan]
"""

import sys
import time
from pathlib import Path

try:
    import teleopcore.xrio as xrio
    import teleopcore.oxr as oxr
    import teleopcore.plugin_manager as pm
    from teleopcore.retargeting_engine import GripperRetargeter
    from teleopcore.retargeting_engine.xrio import ControllersInput, XrioUpdateNode
    from teleopcore.retargeting_engine.holoscan_utils import RetargeterOperator, SourceOperator
    from holoscan.core import Application, Operator, OperatorSpec
    from holoscan.conditions import CountCondition
    from holoscan.schedulers import GreedyScheduler
except ImportError as e:
    print(f"Error: {e}")
    print("\nThis example requires Holoscan SDK.")
    print("Install with: pip install teleopcore[holoscan]")
    print("or: uv pip install teleopcore[holoscan]")
    sys.exit(1)


PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"
PLUGIN_NAME = "controller_synthetic_hands"
PLUGIN_ROOT_ID = "synthetic_hands"


class TickerOp(Operator):
    """Periodic ticker operator to drive the execution loop."""
    
    def __init__(self, fragment, count=1000, name="ticker"):
        """Initialize ticker with a count condition (number of iterations)."""
        super().__init__(fragment, CountCondition(fragment, count), name=name)
    
    def setup(self, spec: OperatorSpec):
        spec.output("tick")
    
    def compute(self, op_input, op_output, context):
        # Brief sleep to control rate (~60 FPS)
        time.sleep(0.0167)
        # Output a simple tick signal (True)
        op_output.emit(True, "tick")


class PrinterOp(Operator):
    """Operator that prints gripper values."""
    
    def __init__(self, fragment, name="printer"):
        super().__init__(fragment, name=name)
        self._frame_count = 0
        self._start_time = time.time()
        self._last_print = self._start_time
    
    def setup(self, spec: OperatorSpec):
        spec.input("left_gripper")
        spec.input("right_gripper")
    
    def compute(self, op_input, op_output, context):
        left_data = op_input.receive("left_gripper")
        right_data = op_input.receive("right_gripper")
        
        if left_data is not None and right_data is not None:
            left_value = left_data[0] if isinstance(left_data, list) else left_data
            right_value = right_data[0] if isinstance(right_data, list) else right_data
            
            current_time = time.time()
            if current_time - self._last_print >= 0.5:
                elapsed = current_time - self._start_time
                print(f"[{elapsed:5.1f}s] Left: {left_value:.2f}  Right: {right_value:.2f}")
                self._last_print = current_time
        
        self._frame_count += 1


class GripperApp(Application):
    """Holoscan application for gripper retargeting."""
    
    def __init__(self, xrio_update_node, controllers_input, gripper_retargeter):
        super().__init__()
        self._xrio_update = xrio_update_node
        self._controllers = controllers_input
        self._gripper = gripper_retargeter
    
    def compose(self):
        # Configure scheduler to not stop on deadlock
        scheduler = GreedyScheduler(self, stop_on_deadlock=False)
        self.scheduler(scheduler)
        
        # Add ticker with count condition (runs for 1000 iterations)
        ticker = TickerOp(self, count=1000, name="ticker")
        
        # Wrap retargeter nodes as Holoscan operators
        xrio_update_op = SourceOperator(self, self._xrio_update, name="xrio_update")
        controllers_op = RetargeterOperator(self, self._controllers, name="controllers_input")
        gripper_op = RetargeterOperator(self, self._gripper, name="gripper_retargeter")
        
        # Create printer operator
        printer = PrinterOp(self)
        
        # Connect the graph using actual collection names:
        # ticker -> xrio_update_op -> controllers_op -> gripper_op -> printer
        self.add_flow(ticker, xrio_update_op, {("tick", "trigger")})
        # xrio_update outputs "trigger" -> controllers expects "trigger" input
        self.add_flow(xrio_update_op, controllers_op, {("trigger", "trigger")})
        # controllers outputs "controller_left"/"controller_right" -> gripper expects same
        self.add_flow(controllers_op, gripper_op, {
            ("controller_left", "controller_left"), 
            ("controller_right", "controller_right")
        })
        # gripper outputs "gripper_left"/"gripper_right" -> printer expects left_gripper/right_gripper
        self.add_flow(gripper_op, printer, {
            ("gripper_left", "left_gripper"), 
            ("gripper_right", "right_gripper")
        })


def main():
    # Create XRIO session builder
    builder = xrio.XrioSessionBuilder()
    
    # Create XRIO update node (will create OpenXR and XRIO sessions lazily)
    xrio_update = XrioUpdateNode(builder, app_name="HoloscanGripperExample")
    
    # Create input nodes (they register trackers with builder)
    # Note: In Holoscan mode, we don't call connect() - connections via Holoscan flows
    controllers = ControllersInput(builder)
    
    # Build retargeting graph
    # Note: In Holoscan mode, we don't call connect() - connections via Holoscan flows
    gripper = GripperRetargeter(name="gripper")
    
    # Initialize plugin (if available)
    plugin_context = None
    if PLUGIN_ROOT_DIR.exists():
        manager = pm.PluginManager([str(PLUGIN_ROOT_DIR)])
        if PLUGIN_NAME in manager.get_plugin_names():
            plugin_context = manager.start(PLUGIN_NAME, PLUGIN_ROOT_ID)
    
    # Run Holoscan app - sessions build on first execute(), cleanup in destructor
    if plugin_context:
        with plugin_context:
            return run_holoscan_app(xrio_update, controllers, gripper)
    else:
        return run_holoscan_app(xrio_update, controllers, gripper)


def run_holoscan_app(xrio_update_node, controllers, gripper):
    """Run the Holoscan application."""
    # Create and run Holoscan application
    app = GripperApp(xrio_update_node, controllers, gripper)
    
    # Run the app (it will run until interrupted or for the duration of the scheduler)
    app.run()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
