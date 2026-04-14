# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tests for CommandTeleopStateManager and OpaqueDataChannelSource._parse_command.

Tests state transitions, priority ordering, and JSON teleop command parsing
without requiring OpenXR hardware.
"""

import json

from isaacteleop.retargeting_engine.interface.tensor_group import (
    OptionalTensorGroup,
)
from isaacteleop.retargeting_engine.interface.tensor_group_type import OptionalType
from isaacteleop.retargeting_engine.interface.execution_events import (
    ExecutionState,
    ExecutionEvents,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (
    ComputeContext,
    RetargeterIO,
)
from isaacteleop.teleop_session_manager.teleop_state_manager_types import bool_signal
from isaacteleop.teleop_session_manager.command_teleop_state_manager import (
    CommandTeleopStateManager,
)
from isaacteleop.retargeting_engine.deviceio_source_nodes.opaque_data_channel_source import (
    OpaqueDataChannelSource,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_inputs(
    start: bool | None = None,
    stop: bool | None = None,
    reset: bool | None = None,
) -> RetargeterIO:
    """Build a RetargeterIO matching CommandTeleopStateManager.input_spec.

    None means the input is absent (OptionalTensorGroup.set_none()).
    """
    spec = {
        CommandTeleopStateManager.INPUT_START: OptionalType(
            bool_signal(CommandTeleopStateManager.INPUT_START)
        ),
        CommandTeleopStateManager.INPUT_STOP: OptionalType(
            bool_signal(CommandTeleopStateManager.INPUT_STOP)
        ),
        CommandTeleopStateManager.INPUT_RESET: OptionalType(
            bool_signal(CommandTeleopStateManager.INPUT_RESET)
        ),
    }
    inputs: RetargeterIO = {}
    for key, tgt in spec.items():
        tg = OptionalTensorGroup(tgt)
        val = {"start_command": start, "stop_command": stop, "reset_command": reset}[
            key
        ]
        if val is None:
            tg.set_none()
        else:
            tg[0] = val
        inputs[key] = tg
    return inputs


def _make_context() -> ComputeContext:
    return ComputeContext(
        graph_time=0.0,
        execution_events=ExecutionEvents(
            reset=False, execution_state=ExecutionState.UNKNOWN
        ),
    )


# ---------------------------------------------------------------------------
# CommandTeleopStateManager tests
# ---------------------------------------------------------------------------


class TestCommandTeleopStateManagerInitialState:
    def test_initial_state_is_stopped(self):
        sm = CommandTeleopStateManager("sm")
        events = sm._compute_execution_events(_make_inputs(), _make_context())
        assert events.execution_state == ExecutionState.STOPPED
        assert events.reset is False


class TestCommandTeleopStateManagerTransitions:
    def test_start_transitions_to_running(self):
        sm = CommandTeleopStateManager("sm")
        events = sm._compute_execution_events(_make_inputs(start=True), _make_context())
        assert events.execution_state == ExecutionState.RUNNING

    def test_stop_transitions_to_stopped(self):
        sm = CommandTeleopStateManager("sm")
        sm._compute_execution_events(_make_inputs(start=True), _make_context())
        events = sm._compute_execution_events(_make_inputs(stop=True), _make_context())
        assert events.execution_state == ExecutionState.STOPPED

    def test_reset_does_not_change_state(self):
        sm = CommandTeleopStateManager("sm")
        sm._compute_execution_events(_make_inputs(start=True), _make_context())
        events = sm._compute_execution_events(_make_inputs(reset=True), _make_context())
        assert events.execution_state == ExecutionState.RUNNING
        assert events.reset is True

    def test_no_inputs_holds_state(self):
        sm = CommandTeleopStateManager("sm")
        sm._compute_execution_events(_make_inputs(start=True), _make_context())
        events = sm._compute_execution_events(_make_inputs(), _make_context())
        assert events.execution_state == ExecutionState.RUNNING
        assert events.reset is False


class TestCommandTeleopStateManagerPriority:
    def test_stop_beats_start(self):
        sm = CommandTeleopStateManager("sm")
        events = sm._compute_execution_events(
            _make_inputs(start=True, stop=True), _make_context()
        )
        assert events.execution_state == ExecutionState.STOPPED

    def test_stop_beats_reset(self):
        sm = CommandTeleopStateManager("sm")
        sm._compute_execution_events(_make_inputs(start=True), _make_context())
        events = sm._compute_execution_events(
            _make_inputs(stop=True, reset=True), _make_context()
        )
        assert events.execution_state == ExecutionState.STOPPED
        assert events.reset is True

    def test_reset_with_start(self):
        sm = CommandTeleopStateManager("sm")
        events = sm._compute_execution_events(
            _make_inputs(start=True, reset=True), _make_context()
        )
        assert events.execution_state == ExecutionState.RUNNING
        assert events.reset is True


# ---------------------------------------------------------------------------
# OpaqueDataChannelSource._parse_command tests
# ---------------------------------------------------------------------------


class TestParseCommand:
    def test_start_command(self):
        raw = json.dumps(
            {"type": "teleop_command", "message": {"command": "start teleop"}}
        ).encode()
        assert OpaqueDataChannelSource._parse_command(raw) == "start_command"

    def test_stop_command(self):
        raw = json.dumps(
            {"type": "teleop_command", "message": {"command": "stop teleop"}}
        ).encode()
        assert OpaqueDataChannelSource._parse_command(raw) == "stop_command"

    def test_reset_command(self):
        raw = json.dumps(
            {"type": "teleop_command", "message": {"command": "reset teleop"}}
        ).encode()
        assert OpaqueDataChannelSource._parse_command(raw) == "reset_command"

    def test_unknown_command_returns_none(self):
        raw = json.dumps(
            {"type": "teleop_command", "message": {"command": "fly away"}}
        ).encode()
        assert OpaqueDataChannelSource._parse_command(raw) is None

    def test_malformed_json_returns_none(self):
        assert OpaqueDataChannelSource._parse_command(b"not json") is None

    def test_non_dict_payload_returns_none(self):
        assert OpaqueDataChannelSource._parse_command(b'"just a string"') is None

    def test_flat_message_string(self):
        """Handles legacy payload where message is a plain string."""
        raw = json.dumps({"type": "teleop_command", "message": "start teleop"}).encode()
        assert OpaqueDataChannelSource._parse_command(raw) == "start_command"

    def test_empty_bytes(self):
        assert OpaqueDataChannelSource._parse_command(b"") is None

    def test_missing_message_key(self):
        raw = json.dumps({"type": "teleop_command"}).encode()
        assert OpaqueDataChannelSource._parse_command(raw) is None
