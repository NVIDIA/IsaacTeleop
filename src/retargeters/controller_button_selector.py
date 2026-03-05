# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
ControllerButtonSelector — maps a single VR controller button to a BoolValue wire.

Pure stateless converter. Takes both controller inputs (Optional) and outputs
a single bool based on the configured hand and button field. The threshold
parameter allows analog axes (squeeze_value, trigger_value) to be treated as
digital buttons.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TYPE_CHECKING

from ..interface.base_retargeter import BaseRetargeter
from ..interface.retargeter_core_types import ComputeContext, RetargeterIO, RetargeterIOType
from ..interface.tensor_group_type import OptionalType
from ..tensor_types import BoolValue, ControllerInput, ControllerInputIndex

if TYPE_CHECKING:
    pass


# Map button name → ControllerInputIndex member name
_BUTTON_TO_INDEX = {
    "primary_click":    "PRIMARY_CLICK",
    "secondary_click":  "SECONDARY_CLICK",
    "thumbstick_click": "THUMBSTICK_CLICK",
    "squeeze_value":    "SQUEEZE_VALUE",
    "trigger_value":    "TRIGGER_VALUE",
}

ButtonField = Literal[
    "primary_click",
    "secondary_click",
    "thumbstick_click",
    "squeeze_value",
    "trigger_value",
]


@dataclass
class ControllerButtonSelectorConfig:
    """Configuration for ControllerButtonSelector.

    Attributes:
        hand:      Which controller to read from ("left" or "right").
        button:    Which button/axis field to read.
        threshold: Value at or above which the bool output is True.
                   Useful for analog axes (squeeze_value, trigger_value).
                   Binary buttons (primary_click etc.) are already 0.0 or 1.0,
                   so the default threshold of 0.5 works for all fields.
    """

    hand: Literal["left", "right"] = "left"
    button: ButtonField = "secondary_click"
    threshold: float = 0.5


class ControllerButtonSelector(BaseRetargeter):
    """Pure stateless converter: one controller button → BoolValue wire.

    Takes both controller_left and controller_right as Optional inputs
    (so a single ControllersSource can feed it without extra wiring), reads
    only the configured hand, and applies a threshold comparison.

    Inputs (both Optional):
        controller_left  — OptionalType(ControllerInput())
        controller_right — OptionalType(ControllerInput())

    Output:
        bool_value — BoolValue() — True when the configured button >= threshold

    Outputs False when the configured controller is absent (is_none=True).

    Example::

        ctrl_src = ControllersSource("controllers")
        selector = ControllerButtonSelector(
            "start_btn",
            ControllerButtonSelectorConfig(hand="right", button="secondary_click"),
        )
        graph = selector.connect({
            "controller_left":  ctrl_src.output("controller_left"),
            "controller_right": ctrl_src.output("controller_right"),
        })
        # graph.output("bool_value") → wire a BoolValue to TeleopEventRetargeter
    """

    def __init__(self, name: str, config: ControllerButtonSelectorConfig) -> None:
        """Initialize ControllerButtonSelector.

        Args:
            name:   Unique name for this retargeter node.
            config: Configuration (hand, button, threshold).
        """
        self._config = config
        self._input_key = f"controller_{config.hand}"
        self._button_idx: int = ControllerInputIndex[_BUTTON_TO_INDEX[config.button]]
        super().__init__(name)

    def input_spec(self) -> RetargeterIOType:
        return {
            "controller_left": OptionalType(ControllerInput()),
            "controller_right": OptionalType(ControllerInput()),
        }

    def output_spec(self) -> RetargeterIOType:
        return {"bool_value": BoolValue()}

    def _compute_fn(
        self, inputs: RetargeterIO, outputs: RetargeterIO, context: ComputeContext
    ) -> None:
        controller = inputs[self._input_key]
        if controller.is_none:
            outputs["bool_value"][0] = False
            return
        value = float(controller[self._button_idx])
        outputs["bool_value"][0] = value >= self._config.threshold
