# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Helper utilities for the simple teleop controls example."""

from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    HeadSource,
    HandsSource,
    ControllersSource,
)
from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    OutputCombiner,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (
    ComputeContext,
    RetargeterIO,
)
from isaacteleop.retargeting_engine.interface.tensor_group_type import (
    OptionalType,
    TensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (
    BoolType,
    ControllerInput,
    HandInput,
    HandInputIndex,
    HeadPose,
    HeadPoseIndex,
)


class TeleopStatePrinterRetargeter(BaseRetargeter):
    """Dummy retargeter that prints execution events from ComputeContext."""

    def __init__(self, name: str, print_every_n_frames: int = 30) -> None:
        self._print_every_n_frames = print_every_n_frames
        self._frame = 0
        super().__init__(name=name)

    def input_spec(self) -> RetargeterIOType:
        return {
            "head": OptionalType(HeadPose()),
            "hand_left": OptionalType(HandInput()),
            "hand_right": OptionalType(HandInput()),
            "controller_left": OptionalType(ControllerInput()),
            "controller_right": OptionalType(ControllerInput()),
        }

    def output_spec(self) -> RetargeterIOType:
        return {"tick": TensorGroupType("tick", [BoolType("tick")])}

    def _compute_fn(
        self, inputs: RetargeterIO, outputs: RetargeterIO, context: ComputeContext
    ) -> None:
        if self._frame % self._print_every_n_frames == 0:
            print(
                "[retargeter] "
                f"state={context.execution_events.execution_state.value} "
                f"reset={context.execution_events.reset} "
                f"head={not inputs['head'].is_none} "
                f"hands(L/R)={not inputs['hand_left'].is_none}/{not inputs['hand_right'].is_none} "
                f"controllers(L/R)={not inputs['controller_left'].is_none}/{not inputs['controller_right'].is_none}"
            )
        self._frame += 1
        outputs["tick"][0] = True


def build_observation_pipeline(
    head: HeadSource, hands: HandsSource, controllers: ControllersSource
) -> OutputCombiner:
    """Build non-control pipeline pieces used only for demo printing."""
    printer = TeleopStatePrinterRetargeter(name="teleop_state_printer")
    printer_pipeline = printer.connect(
        {
            "head": head.output("head"),
            "hand_left": hands.output(HandsSource.LEFT),
            "hand_right": hands.output(HandsSource.RIGHT),
            "controller_left": controllers.output(ControllersSource.LEFT),
            "controller_right": controllers.output(ControllersSource.RIGHT),
        }
    )

    return OutputCombiner(
        {
            "head": head.output("head"),
            "hand_left": hands.output(HandsSource.LEFT),
            "hand_right": hands.output(HandsSource.RIGHT),
            "controller_left": controllers.output(ControllersSource.LEFT),
            "controller_right": controllers.output(ControllersSource.RIGHT),
            "printer_tick": printer_pipeline.output("tick"),
        }
    )


def print_header() -> None:
    print("\n" + "=" * 80)
    print("Simple Teleop Controls Example")
    print(
        "Bindings (LEFT controller): kill=B (any->stopped), "
        "run_toggle=A (stopped->paused->running->paused...), "
        "reset=thumbstick_click (state unchanged)"
    )
    print("Press Ctrl+C to exit")
    print("=" * 80 + "\n")


def print_frame(outputs, elapsed: float) -> None:
    head_present = not outputs["head"].is_none
    left_hand_present = not outputs["hand_left"].is_none
    right_hand_present = not outputs["hand_right"].is_none
    left_ctrl_present = not outputs["controller_left"].is_none
    right_ctrl_present = not outputs["controller_right"].is_none

    head_pos_str = "absent"
    if head_present:
        p = outputs["head"][HeadPoseIndex.POSITION]
        head_pos_str = f"[{p[0]:+.3f}, {p[1]:+.3f}, {p[2]:+.3f}]"

    left_wrist_str = "absent"
    if left_hand_present:
        wp = outputs["hand_left"][HandInputIndex.JOINT_POSITIONS][0]
        left_wrist_str = f"[{wp[0]:+.3f}, {wp[1]:+.3f}, {wp[2]:+.3f}]"

    right_wrist_str = "absent"
    if right_hand_present:
        wp = outputs["hand_right"][HandInputIndex.JOINT_POSITIONS][0]
        right_wrist_str = f"[{wp[0]:+.3f}, {wp[1]:+.3f}, {wp[2]:+.3f}]"

    print(
        f"[{elapsed:5.1f}s] "
        f"head={head_present} pos={head_pos_str} | "
        f"hands(L/R)={left_hand_present}/{right_hand_present} "
        f"wristL={left_wrist_str} wristR={right_wrist_str} | "
        f"ctrl(L/R)={left_ctrl_present}/{right_ctrl_present}"
    )
