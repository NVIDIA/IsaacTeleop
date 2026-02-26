# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Hand and Controller Velocity Tracker Example with TeleopSessionManager

Demonstrates using TeleopSession with velocity tracking.

This example shows:
1. Computing velocity from wrist and controller position changes
2. Using TeleopSession with synthetic hands plugin
3. Displaying velocity data
"""

import sys
import time
import numpy as np
from pathlib import Path
from typing import Dict, Optional

from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    HandsSource,
    ControllersSource,
)
from isaacteleop.teleop_session_manager import (
    TeleopSession,
    TeleopSessionConfig,
    PluginConfig,
)
from isaacteleop.retargeting_engine.interface import BaseRetargeter
from isaacteleop.retargeting_engine.tensor_types import (
    HandInput,
    HandInputIndex,
    ControllerInput,
    ControllerInputIndex,
)
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    TensorGroupType,
    OptionalType,
)
from isaacteleop.retargeting_engine.interface.tensor_group import TensorGroup
from isaacteleop.retargeting_engine.tensor_types import FloatType


PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"


# ==============================================================================
# Velocity Tracker
# ==============================================================================


class VelocityTracker(BaseRetargeter):
    """Computes velocity from hand wrist and controller position changes."""

    def __init__(self, name: str):
        super().__init__(name)

        # Store previous positions for velocity computation
        self._prev_hand_left: Optional[np.ndarray] = None
        self._prev_hand_right: Optional[np.ndarray] = None
        self._prev_controller_left: Optional[np.ndarray] = None
        self._prev_controller_right: Optional[np.ndarray] = None
        self._prev_time: Optional[float] = None

    def input_spec(self):
        return {
            HandsSource.LEFT: OptionalType(HandInput()),
            HandsSource.RIGHT: OptionalType(HandInput()),
            ControllersSource.LEFT: OptionalType(ControllerInput()),
            ControllersSource.RIGHT: OptionalType(ControllerInput()),
        }

    def output_spec(self):
        return {
            "hand_velocity_left": TensorGroupType(
                "hand_velocity_left", [FloatType("magnitude")]
            ),
            "hand_velocity_right": TensorGroupType(
                "hand_velocity_right", [FloatType("magnitude")]
            ),
            "controller_velocity_left": TensorGroupType(
                "controller_velocity_left", [FloatType("magnitude")]
            ),
            "controller_velocity_right": TensorGroupType(
                "controller_velocity_right", [FloatType("magnitude")]
            ),
        }

    def _extract_wrist(self, hand_input):
        """Extract wrist position from hand joint positions."""
        positions = hand_input[HandInputIndex.JOINT_POSITIONS]
        return np.array([positions[0][0], positions[0][1], positions[0][2]])

    def _extract_grip(self, controller_input):
        """Extract grip position from controller input."""
        pos = controller_input[ControllerInputIndex.GRIP_POSITION]
        return np.array([pos[0], pos[1], pos[2]])

    def _velocity(self, current, previous, dt):
        """Compute velocity magnitude between two positions."""
        if previous is None or dt <= 0:
            return 0.0
        return float(np.linalg.norm(current - previous) / dt)

    def compute(
        self, inputs: Dict[str, TensorGroup], outputs: Dict[str, TensorGroup]
    ) -> None:
        current_time = time.time()
        dt = (current_time - self._prev_time) if self._prev_time is not None else 0.0

        # Hand left
        if not inputs[HandsSource.LEFT].is_none:
            wrist = self._extract_wrist(inputs[HandsSource.LEFT])
            outputs["hand_velocity_left"][0] = self._velocity(
                wrist, self._prev_hand_left, dt
            )
            self._prev_hand_left = wrist
        else:
            outputs["hand_velocity_left"][0] = 0.0
            self._prev_hand_left = None

        # Hand right
        if not inputs[HandsSource.RIGHT].is_none:
            wrist = self._extract_wrist(inputs[HandsSource.RIGHT])
            outputs["hand_velocity_right"][0] = self._velocity(
                wrist, self._prev_hand_right, dt
            )
            self._prev_hand_right = wrist
        else:
            outputs["hand_velocity_right"][0] = 0.0
            self._prev_hand_right = None

        # Controller left
        if not inputs[ControllersSource.LEFT].is_none:
            grip = self._extract_grip(inputs[ControllersSource.LEFT])
            outputs["controller_velocity_left"][0] = self._velocity(
                grip, self._prev_controller_left, dt
            )
            self._prev_controller_left = grip
        else:
            outputs["controller_velocity_left"][0] = 0.0
            self._prev_controller_left = None

        # Controller right
        if not inputs[ControllersSource.RIGHT].is_none:
            grip = self._extract_grip(inputs[ControllersSource.RIGHT])
            outputs["controller_velocity_right"][0] = self._velocity(
                grip, self._prev_controller_right, dt
            )
            self._prev_controller_right = grip
        else:
            outputs["controller_velocity_right"][0] = 0.0
            self._prev_controller_right = None

        self._prev_time = current_time


def main():
    # ==================================================================
    # Build Pipeline
    # ==================================================================

    hands = HandsSource(name="hands")
    controllers = ControllersSource(name="controllers")

    tracker = VelocityTracker(name="velocity_tracker")
    pipeline = tracker.connect(
        {
            HandsSource.LEFT: hands.output(HandsSource.LEFT),
            HandsSource.RIGHT: hands.output(HandsSource.RIGHT),
            ControllersSource.LEFT: controllers.output(ControllersSource.LEFT),
            ControllersSource.RIGHT: controllers.output(ControllersSource.RIGHT),
        }
    )

    # ==================================================================
    # Create TeleopSession with synthetic hands plugin
    # ==================================================================

    config = TeleopSessionConfig(
        app_name="VelocityTrackerExample",
        pipeline=pipeline,
        plugins=[
            PluginConfig(
                plugin_name="controller_synthetic_hands",
                plugin_root_id="synthetic_hands",
                search_paths=[PLUGIN_ROOT_DIR],
            )
        ],
    )

    with TeleopSession(config) as session:
        print("\n" + "=" * 70)
        print("Velocity Tracker - Move your hands and controllers")
        print("Press Ctrl+C to exit")
        print("=" * 70 + "\n")

        while True:
            result = session.step()

            hand_left_vel = result["hand_velocity_left"][0]
            hand_right_vel = result["hand_velocity_right"][0]
            controller_left_vel = result["controller_velocity_left"][0]
            controller_right_vel = result["controller_velocity_right"][0]

            if session.frame_count % 30 == 0:
                elapsed = session.get_elapsed_time()
                print(
                    f"[{elapsed:5.1f}s] Hand L/R: {hand_left_vel:.3f}/{hand_right_vel:.3f} m/s  "
                    f"Controller L/R: {controller_left_vel:.3f}/{controller_right_vel:.3f} m/s"
                )

            time.sleep(0.016)  # ~60 FPS

    return 0


if __name__ == "__main__":
    sys.exit(main())
