# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Video Stream Monitor

When frames stop arriving, displays "VIDEO STREAM UNAVAILABLE" after timeout.
"""

import time

import cv2
import cupy as cp
import numpy as np
from loguru import logger

from holoscan.core import ConditionType, IOSpec, Operator, OperatorSpec


NVIDIA_GREEN_BGR = (0, 185, 118)


def create_no_signal_frame(
    width: int, height: int, camera_name: str = ""
) -> cp.ndarray:
    """Create placeholder frame with 'VIDEO STREAM UNAVAILABLE' text."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = min(width, height) / 600
    thickness = max(2, int(font_scale * 2))

    # Main text
    main_text = "VIDEO STREAM UNAVAILABLE"
    (main_w, main_h), _ = cv2.getTextSize(main_text, font, font_scale, thickness)
    main_x = (width - main_w) // 2
    main_y = (height + main_h) // 2

    cv2.putText(
        frame,
        main_text,
        (main_x, main_y),
        font,
        font_scale,
        NVIDIA_GREEN_BGR,
        thickness,
        cv2.LINE_AA,
    )

    # Camera name (smaller, below main text)
    if camera_name:
        name_scale = font_scale * 0.6
        name_thickness = max(1, int(name_scale * 2))
        (name_w, name_h), _ = cv2.getTextSize(
            camera_name, font, name_scale, name_thickness
        )
        name_x = (width - name_w) // 2
        name_y = main_y + main_h + int(20 * font_scale)
        cv2.putText(
            frame,
            camera_name,
            (name_x, name_y),
            font,
            name_scale,
            NVIDIA_GREEN_BGR,
            name_thickness,
            cv2.LINE_AA,
        )

    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    return cp.asarray(np.ascontiguousarray(frame))


class VideoStreamMonitorOp(Operator):
    def __init__(
        self,
        fragment,
        *args,
        timeout_sec: float = 2.0,
        default_width: int = 1920,
        default_height: int = 1080,
        tensor_name: str = "",
        camera_name: str = "",
        verbose: bool = False,
        **kwargs,
    ):
        self._timeout_sec = timeout_sec
        self._width = default_width
        self._height = default_height
        self._tensor_name = tensor_name
        self._camera_name = camera_name
        self._verbose = verbose
        super().__init__(fragment, *args, **kwargs)

    def setup(self, spec: OperatorSpec):
        spec.input("frame_in", size=1, policy=IOSpec.QueuePolicy.POP).condition(
            ConditionType.NONE
        )
        spec.output("frame_out")

    def start(self):
        placeholder = create_no_signal_frame(
            self._width, self._height, self._camera_name
        )
        self._placeholder_tensor = {self._tensor_name: placeholder}

        self._last_frame_time = time.monotonic()
        self._frame_count = 0
        self._showing_placeholder = False

    def compute(self, op_input, op_output, context):
        frame_dict = op_input.receive("frame_in")

        if frame_dict is not None:
            self._last_frame_time = time.monotonic()
            self._frame_count += 1

            if self._showing_placeholder:
                self._showing_placeholder = False
                if self._verbose:
                    name_str = f" ({self._camera_name})" if self._camera_name else ""
                    logger.info(f"Stream recovered{name_str}")

            # Rename tensor if tensor_name is specified
            if self._tensor_name:
                # Get the first tensor value (usually keyed by "")
                tensor_value = next(iter(frame_dict.values()))
                frame_dict = {self._tensor_name: tensor_value}

            op_output.emit(frame_dict, "frame_out")
        else:
            if time.monotonic() - self._last_frame_time >= self._timeout_sec:
                if not self._showing_placeholder:
                    self._showing_placeholder = True
                    if self._verbose:
                        name_str = (
                            f" ({self._camera_name})" if self._camera_name else ""
                        )
                        logger.info(f"Stream timeout{name_str} - video unavailable")

                op_output.emit(self._placeholder_tensor, "frame_out")
