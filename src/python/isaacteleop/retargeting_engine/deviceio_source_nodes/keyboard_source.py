# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Keyboard Source Node - DeviceIO to Retargeting Engine converter.

Converts raw KeyboardOutput flatbuffer data to standard KeyboardInput tensor format.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING
from .interface import IDeviceIOSource
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import KeyboardInput, KeyboardInputIndex
from ..interface.tensor_group_type import OptionalType
from .deviceio_tensor_types import DeviceIOKeyboardOutputTracked

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.schema import (
        KeyboardOutput,
        KeyboardOutputTrackedT,
    )

# Default collection_id matching the keyboard plugin and KeyboardTracker.
DEFAULT_KEYBOARD_COLLECTION_ID = "keyboard"


class KeyboardSource(IDeviceIOSource):
    """
    Stateless converter: DeviceIO KeyboardOutput → KeyboardInput tensors.

    Inputs:
        - "deviceio_keyboard": Raw KeyboardOutput flatbuffer from KeyboardTracker

    Outputs (Optional — absent when the keyboard plugin has not yet streamed):
        - "keyboard": OptionalTensorGroup (check ``.is_none`` before access)

    Usage:
        # In TeleopSession, the keyboard tracker is discovered from the pipeline;
        # data is polled via poll_tracker. Or manually:
        tracked = keyboard_tracker.get_keyboard_data(session)
        result = keyboard_source_node({
            "deviceio_keyboard": TensorGroup(DeviceIOKeyboardOutputTracked(), [tracked])
        })
    """

    def __init__(
        self, name: str, collection_id: str = DEFAULT_KEYBOARD_COLLECTION_ID
    ) -> None:
        """Initialize stateless keyboard source node.

        Creates a KeyboardTracker instance for TeleopSession to discover and use.

        Args:
            name: Unique name for this source node
            collection_id: Tensor collection ID for keyboard data (must match the keyboard plugin).
        """
        import isaacteleop.deviceio as deviceio

        self._keyboard_tracker = deviceio.KeyboardTracker(collection_id)
        self._collection_id = collection_id
        super().__init__(name)

    def get_tracker(self) -> "ITracker":
        """Get the KeyboardTracker instance.

        Returns:
            The KeyboardTracker instance for TeleopSession to initialize
        """
        return self._keyboard_tracker

    def poll_tracker(self, deviceio_session: Any) -> RetargeterIO:
        """Poll the keyboard tracker and return input data.

        Args:
            deviceio_session: The active DeviceIO session.

        Returns:
            Dict with "deviceio_keyboard" TensorGroup containing KeyboardOutputTrackedT.
        """
        tracked = self._keyboard_tracker.get_keyboard_data(deviceio_session)
        tg = TensorGroup(DeviceIOKeyboardOutputTracked())
        tg[0] = tracked
        return {"deviceio_keyboard": tg}

    def input_spec(self) -> RetargeterIOType:
        """Declare DeviceIO keyboard input."""
        return {
            "deviceio_keyboard": DeviceIOKeyboardOutputTracked(),
        }

    def output_spec(self) -> RetargeterIOType:
        """Declare standard keyboard input output (Optional — may be absent)."""
        return {
            "keyboard": OptionalType(KeyboardInput()),
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        """
        Convert DeviceIO KeyboardOutputTrackedT to standard KeyboardInput tensor.

        Calls ``set_none()`` on the output when the keyboard plugin has not yet streamed.

        Args:
            inputs: Dict with "deviceio_keyboard" containing KeyboardOutputTrackedT wrapper
            outputs: Dict with "keyboard" OptionalTensorGroup
            context: Shared ComputeContext for the current step (carries GraphTime).
        """
        tracked: "KeyboardOutputTrackedT" = inputs["deviceio_keyboard"][0]
        keys: KeyboardOutput | None = tracked.data

        out = outputs["keyboard"]
        if keys is None:
            out.set_none()
            return

        out[KeyboardInputIndex.KEY_W] = bool(keys.key_w)
        out[KeyboardInputIndex.KEY_A] = bool(keys.key_a)
        out[KeyboardInputIndex.KEY_S] = bool(keys.key_s)
        out[KeyboardInputIndex.KEY_D] = bool(keys.key_d)
        out[KeyboardInputIndex.KEY_Q] = bool(keys.key_q)
        out[KeyboardInputIndex.KEY_E] = bool(keys.key_e)
        out[KeyboardInputIndex.KEY_Z] = bool(keys.key_z)
        out[KeyboardInputIndex.KEY_X] = bool(keys.key_x)
        out[KeyboardInputIndex.KEY_T] = bool(keys.key_t)
        out[KeyboardInputIndex.KEY_G] = bool(keys.key_g)
        out[KeyboardInputIndex.KEY_C] = bool(keys.key_c)
        out[KeyboardInputIndex.KEY_V] = bool(keys.key_v)
        out[KeyboardInputIndex.KEY_K] = bool(keys.key_k)
