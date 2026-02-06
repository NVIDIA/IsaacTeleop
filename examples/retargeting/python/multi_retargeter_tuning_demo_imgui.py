#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Multi-Retargeter Tuning Demo with ImGui - Chained Processing Example

Demonstrates using MultiRetargeterTuningUIImGui with multiple instances of the same
retargeter type chained together.

This example shows:
- Creating a simple gain+offset retargeter
- Chaining three instances together (Stage 1 → Stage 2 → Stage 3)
- Tuning all stages simultaneously in a unified ImGui window
- Real-time visualization of the processing chain

Usage:
    python multi_retargeter_tuning_demo_imgui.py [layout_mode]
    
    layout_mode: tabs (default), vertical, horizontal, floating
"""

import sys
import time

import numpy as np

from example_retargeters import GainOffsetRetargeter
from isaacteleop.retargeting_engine.interface import TensorGroup
from isaacteleop.retargeting_engine_ui import MultiRetargeterTuningUIImGui, LayoutModeImGui


def main():
    print("=" * 70)
    print("Multi-Retargeter Tuning Demo - ImGui UI")
    print("=" * 70)
    print()
    
    # Parse command line arguments
    layout_mode = LayoutModeImGui.TABS
    if len(sys.argv) > 1:
        mode_str = sys.argv[1].lower()
        mode_map = {
            "tabs": LayoutModeImGui.TABS,
            "vertical": LayoutModeImGui.VERTICAL,
            "horizontal": LayoutModeImGui.HORIZONTAL,
            "floating": LayoutModeImGui.FLOATING,
        }
        layout_mode = mode_map.get(mode_str, LayoutModeImGui.TABS)
    
    print(f"[1] Using layout mode: {layout_mode.value}")
    print()
    
    # Create three chained retargeters
    print("[2] Creating chained retargeters...")
    stage1 = GainOffsetRetargeter("Stage 1", config_file="stage1_imgui.json")
    stage2 = GainOffsetRetargeter("Stage 2", config_file="stage2_imgui.json")
    stage3 = GainOffsetRetargeter("Stage 3", config_file="stage3_imgui.json")
    print(f"    ✓ Stage 1: gain={stage1.gain:.3f}, offset={stage1.offset:.3f}")
    print(f"    ✓ Stage 2: gain={stage2.gain:.3f}, offset={stage2.offset:.3f}")
    print(f"    ✓ Stage 3: gain={stage3.gain:.3f}, offset={stage3.offset:.3f}")
    print()
    
    # Open multi-retargeter ImGui UI using context manager (RAII)
    print("[3] Opening multi-retargeter ImGui UI...")
    with MultiRetargeterTuningUIImGui(
        [stage1, stage2, stage3],
        title="Chained Retargeter Tuning (ImGui)",
        layout_mode=layout_mode
    ) as ui:
        print("    ✓ ImGui UI opened in background thread")
        print()
        
        # Create input tensor using public API
        input_tensor = TensorGroup(stage1.input_spec()["value"])
        
        # Main processing loop
        print("[4] Starting processing loop...")
        print("    Close ImGui window to stop")
        print("    Adjust parameters in the ImGui window to see real-time effects!")
        print()
        
        frame_count = 0
        start_time = time.time()
        
        while ui.is_running():
            # Generate sinusoidal input
            t = time.time() * 0.5
            input_tensor[0] = np.sin(t)
            
            # Process through chain: Stage 1 → Stage 2 → Stage 3
            output1 = stage1({"value": input_tensor})
            value1 = output1["value"][0]
            
            output2 = stage2({"value": output1["value"]})
            value2 = output2["value"][0]
            
            output3 = stage3({"value": output2["value"]})
            value3 = output3["value"][0]
            
            # Display status
            frame_count += 1
            if frame_count % 30 == 0:
                elapsed = time.time() - start_time
                fps = frame_count / elapsed if elapsed > 0 else 0
                
                print(f"\rFrame {frame_count:5d} | FPS: {fps:5.1f} | "
                      f"Input: {input_tensor[0]:+6.3f} → "
                      f"S1: {value1:+6.3f} → "
                      f"S2: {value2:+6.3f} → "
                      f"S3: {value3:+6.3f}", end="")
            
            # Small sleep to avoid spinning
            time.sleep(0.016)  # ~60 FPS
    
    # UI automatically closed via context manager
    print()
    print("=" * 70)
    print("Demo Complete")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())