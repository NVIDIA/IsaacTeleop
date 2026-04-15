# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Command-driven teleop state manager.

Translates explicit start/stop/reset command pulses (e.g. from a WebXR UI
via an opaque data channel) into ExecutionEvents.  Unlike
DefaultTeleopStateManager which uses edge-detected button toggles, this
manager treats each command as a direct state transition.
"""

from isaacteleop.retargeting_engine.interface import RetargeterIOType
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (
    ComputeContext,
    RetargeterIO,
)
from isaacteleop.retargeting_engine.interface.tensor_group_type import OptionalType
from isaacteleop.retargeting_engine.interface.execution_events import (
    ExecutionState,
    ExecutionEvents,
)

from .teleop_state_manager_retargeter import TeleopStateManager
from .teleop_state_manager_types import bool_signal


class CommandTeleopStateManager(TeleopStateManager):
    """Teleop state manager driven by explicit start/stop/reset commands.

    All inputs are optional.  When no command is received in a frame the
    manager holds its current state.  Initial state is STOPPED.

    Inputs (all OptionalType):
        - start_command: pulse sets state to RUNNING.
        - stop_command: pulse sets state to STOPPED.
        - reset_command: pulse emits ``reset=True`` without changing state.

    Priority when multiple commands arrive in the same frame:
        stop > reset > start.
    """

    INPUT_START = "start_command"
    INPUT_STOP = "stop_command"
    INPUT_RESET = "reset_command"

    def __init__(self, name: str) -> None:
        self._state = ExecutionState.STOPPED
        super().__init__(name=name)

    def input_spec(self) -> RetargeterIOType:
        return {
            self.INPUT_START: OptionalType(bool_signal(self.INPUT_START)),
            self.INPUT_STOP: OptionalType(bool_signal(self.INPUT_STOP)),
            self.INPUT_RESET: OptionalType(bool_signal(self.INPUT_RESET)),
        }

    def _compute_execution_events(
        self, inputs: RetargeterIO, context: ComputeContext
    ) -> ExecutionEvents:
        del context

        start = self._read_pulse(inputs, self.INPUT_START)
        stop = self._read_pulse(inputs, self.INPUT_STOP)
        reset = self._read_pulse(inputs, self.INPUT_RESET)

        if stop:
            self._state = ExecutionState.STOPPED
        elif start:
            self._state = ExecutionState.RUNNING

        return ExecutionEvents(reset=reset, execution_state=self._state)

    @staticmethod
    def _read_pulse(inputs: RetargeterIO, key: str) -> bool:
        group = inputs[key]
        if group.is_none:
            return False
        return bool(group[0])
