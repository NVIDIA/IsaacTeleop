# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Keyboard Source Node - DeviceIO to Retargeting Engine converter.

Converts raw KeyboardOutput flatbuffer data (a set of held evdev key codes, see
linux/input-event-codes.h) to two standard outputs: the fixed 13-key subset used
by SE3 retargeting, and a 256-entry bitmap covering every standard key.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING
from .interface import IDeviceIOSource
from ..interface.retargeter_core_types import RetargeterIO, RetargeterIOType
from ..interface.tensor_group import TensorGroup
from ..tensor_types import KeyboardInput, KeyboardInputIndex, NDArrayType, DLDataType
from ..interface.tensor_group_type import OptionalType, TensorGroupType
from .deviceio_tensor_types import DeviceIOKeyboardOutputTracked

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker
    from isaacteleop.schema import KeyboardOutput

# Default collection_id matching the keyboard plugin and KeyboardTracker.
DEFAULT_KEYBOARD_COLLECTION_ID = "keyboard"

# Evdev key codes (linux/input-event-codes.h) for the fixed SE3-relevant subset.
KEY_CODES_BY_INDEX = {
    KeyboardInputIndex.KEY_W: 17,
    KeyboardInputIndex.KEY_A: 30,
    KeyboardInputIndex.KEY_S: 31,
    KeyboardInputIndex.KEY_D: 32,
    KeyboardInputIndex.KEY_Q: 16,
    KeyboardInputIndex.KEY_E: 18,
    KeyboardInputIndex.KEY_Z: 44,
    KeyboardInputIndex.KEY_X: 45,
    KeyboardInputIndex.KEY_T: 20,
    KeyboardInputIndex.KEY_G: 34,
    KeyboardInputIndex.KEY_C: 46,
    KeyboardInputIndex.KEY_V: 47,
    KeyboardInputIndex.KEY_K: 37,
}

# Every standard PC keyboard key (letters, digits, function keys, navigation,
# modifiers, numpad, punctuation) fits under evdev code 255; anything above that
# is an exotic/vendor key not tracked here.
ALL_KEYS_BITMAP_SIZE = 256


def KeyboardAllKeysType() -> TensorGroupType:
    """Type for the "keyboard_all_keys" output: a 256-entry uint8 bitmap indexed by evdev key code."""
    return TensorGroupType(
        "keyboard_all_keys",
        [
            NDArrayType(
                "bitmap",
                shape=(ALL_KEYS_BITMAP_SIZE,),
                dtype=DLDataType.UINT,
                dtype_bits=8,
            )
        ],
    )


class KeyboardSource(IDeviceIOSource):
    """
    Stateless converter: DeviceIO KeyboardOutput → KeyboardInput tensors.

    Inputs:
        - "deviceio_keyboard": Raw KeyboardOutput flatbuffer from KeyboardTracker

    Outputs (Optional — absent when the keyboard plugin has not yet streamed):
        - "keyboard": OptionalTensorGroup, the fixed 13-key SE3-relevant subset
          (check ``.is_none`` before access)
        - "keyboard_all_keys": OptionalTensorGroup, a 256-entry uint8 bitmap
          indexed by evdev key code (1 = held, 0 = released) covering every
          standard key, for consumers that want full keyboard visibility
          rather than the SE3-specific subset.

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
            Dict with "deviceio_keyboard" TensorGroup containing KeyboardOutput | None.
        """
        keys = self._keyboard_tracker.get_keyboard_data(deviceio_session)
        tg = TensorGroup(DeviceIOKeyboardOutputTracked())
        tg[0] = keys
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
            "keyboard_all_keys": OptionalType(KeyboardAllKeysType()),
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        """
        Convert DeviceIO KeyboardOutput to the standard keyboard outputs.

        Calls ``set_none()`` on both outputs when the keyboard plugin has not yet
        streamed.

        Args:
            inputs: Dict with "deviceio_keyboard" containing KeyboardOutput | None
            outputs: Dict with "keyboard" and "keyboard_all_keys" OptionalTensorGroups
            context: Shared ComputeContext for the current step (carries GraphTime).
        """
        import numpy as np

        keys: KeyboardOutput | None = inputs["deviceio_keyboard"][0]

        out = outputs["keyboard"]
        all_keys_out = outputs["keyboard_all_keys"]
        if keys is None:
            out.set_none()
            all_keys_out.set_none()
            return

        pressed = set(keys.pressed_keys)

        for index, code in KEY_CODES_BY_INDEX.items():
            out[index] = code in pressed

        bitmap = np.zeros(ALL_KEYS_BITMAP_SIZE, dtype=np.uint8)
        for code in pressed:
            if code < ALL_KEYS_BITMAP_SIZE:
                bitmap[code] = 1
        all_keys_out[0] = bitmap
