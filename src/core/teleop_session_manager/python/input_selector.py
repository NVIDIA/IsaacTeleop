# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Debounced one-input selector utility for teleop-control graphs."""

import math
from numbers import Real
from typing import Callable, Optional, Union

from isaacteleop.retargeting_engine.interface import (
    BaseRetargeter,
    RetargeterIOType,
    GraphExecutable,
    OutputSelector,
)
from isaacteleop.retargeting_engine.interface.tensor_group import OptionalTensorGroup
from isaacteleop.retargeting_engine.interface.retargeter_core_types import RetargeterIO
from isaacteleop.retargeting_engine.interface.tensor_group_type import TensorGroupType
from isaacteleop.retargeting_engine.interface.tensor_group_type import OptionalType

from .teleop_state_manager_types import bool_signal


class _BoolSelectorRetargeter(BaseRetargeter):
    """Compute one debounced bool output from one selected input tensor group."""

    INPUT_VALUE = "selected_input"

    def __init__(
        self,
        name: str,
        selected_type: TensorGroupType,
        selector_fn: Callable[[OptionalTensorGroup], Optional[Union[bool, float]]],
        output_name: str,
        threshold: float,
        release_threshold: float,
        activate_frames: int,
        deactivate_frames: int,
        initial_state: bool,
    ) -> None:
        self._selected_type = selected_type
        self._selector_fn = selector_fn
        self._output_name = output_name
        self._threshold = threshold
        self._release_threshold = release_threshold
        self._activate_frames = activate_frames
        self._deactivate_frames = deactivate_frames
        self._initial_state = bool(initial_state)
        self._debounced_state = self._initial_state
        self._activate_count = 0
        self._deactivate_count = 0
        super().__init__(name=name)

    def input_spec(self) -> RetargeterIOType:
        return {self.INPUT_VALUE: OptionalType(self._selected_type)}

    def output_spec(self) -> RetargeterIOType:
        return {self._output_name: OptionalType(bool_signal(self._output_name))}

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context) -> None:
        del context
        selected_input = inputs[self.INPUT_VALUE]
        if selected_input.is_none:
            self._debounced_state = self._initial_state
            self._activate_count = 0
            self._deactivate_count = 0
            outputs[self._output_name].set_none()
            return

        value = self._selector_fn(selected_input)
        if value is None:
            self._debounced_state = self._initial_state
            self._activate_count = 0
            self._deactivate_count = 0
            outputs[self._output_name].set_none()
            return

        raw_state = self._normalize_raw_value(value)
        debounced = self._update_debounced_state(raw_state)
        outputs[self._output_name][0] = debounced

    def _normalize_raw_value(self, value: Union[bool, float]) -> bool:
        if isinstance(value, bool):
            return value
        if not isinstance(value, Real):
            raise TypeError(
                f"selector_fn must return bool/float/None, got {type(value).__name__}"
            )
        scalar = float(value)
        if self._debounced_state:
            return scalar >= self._release_threshold
        return scalar >= self._threshold

    def _update_debounced_state(self, raw_state: bool) -> bool:
        if raw_state == self._debounced_state:
            self._activate_count = 0
            self._deactivate_count = 0
            return self._debounced_state

        if raw_state:
            self._activate_count += 1
            self._deactivate_count = 0
            if self._activate_count >= self._activate_frames:
                self._debounced_state = True
                self._activate_count = 0
        else:
            self._deactivate_count += 1
            self._activate_count = 0
            if self._deactivate_count >= self._deactivate_frames:
                self._debounced_state = False
                self._deactivate_count = 0

        return self._debounced_state


def create_bool_selector(
    source_output_selector: OutputSelector,
    *,
    name: str,
    selector_fn: Callable[[OptionalTensorGroup], Optional[Union[bool, float]]],
    output_name: str = "value",
    threshold: float = 0.5,
    release_threshold: Optional[float] = None,
    activate_frames: int = 2,
    deactivate_frames: int = 2,
    initial_state: bool = False,
) -> GraphExecutable:
    """Build one debounced bool signal from one selected input tensor group.

    The utility handles ``None`` automatically:
    - if upstream input is absent, output is set to ``None``
    - if ``selector_fn`` returns ``None``, output is set to ``None``

    ``selector_fn`` receives the selected input tensor group directly and should
    return either:
    - ``bool`` for directly interpreted digital signals, or
    - ``float`` for analog signals thresholded into bool.

    For float signals, hysteresis is applied:
    - transition to True when value >= ``threshold``
    - transition to False when value < ``release_threshold``
    If ``release_threshold`` is omitted, it is set to ``threshold``.
    """
    if not callable(selector_fn):
        raise TypeError(
            "create_bool_selector requires selector_fn to be callable, "
            f"got {type(selector_fn).__name__}"
        )
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise TypeError(
            "create_bool_selector requires threshold to be numeric (int or float), "
            f"got {type(threshold).__name__}"
        )
    threshold = float(threshold)
    if not math.isfinite(threshold):
        raise ValueError(
            f"create_bool_selector requires threshold to be finite, got {threshold}"
        )
    if threshold < 0.0:
        raise ValueError(
            "create_bool_selector requires threshold to be non-negative, "
            f"got {threshold}"
        )
    if release_threshold is None:
        release_threshold = threshold
    else:
        if isinstance(release_threshold, bool) or not isinstance(
            release_threshold, (int, float)
        ):
            raise TypeError(
                "create_bool_selector requires release_threshold to be numeric "
                "(int or float) when provided, "
                f"got {type(release_threshold).__name__}"
            )
        release_threshold = float(release_threshold)
    if not math.isfinite(release_threshold):
        raise ValueError(
            "create_bool_selector requires release_threshold to be finite, "
            f"got {release_threshold}"
        )
    if release_threshold < 0.0:
        raise ValueError(
            "create_bool_selector requires release_threshold to be non-negative, "
            f"got {release_threshold}"
        )

    if not isinstance(source_output_selector, OutputSelector):
        raise TypeError(
            "source_output_selector must be OutputSelector, "
            f"got {type(source_output_selector).__name__}"
        )
    if activate_frames < 1:
        raise ValueError("activate_frames must be >= 1")
    if deactivate_frames < 1:
        raise ValueError("deactivate_frames must be >= 1")
    if release_threshold > threshold:
        raise ValueError("release_threshold must be <= threshold")

    module_outputs = source_output_selector.module.output_types()
    if source_output_selector.output_name not in module_outputs:
        available_outputs = sorted(module_outputs.keys())
        raise ValueError(
            "Invalid output selector for create_bool_selector: "
            f"module '{source_output_selector.module.name}' has no output "
            f"'{source_output_selector.output_name}'. "
            f"Available outputs: {available_outputs}"
        )
    selected_type = module_outputs[source_output_selector.output_name]
    selector = _BoolSelectorRetargeter(
        name=name,
        selected_type=selected_type,
        selector_fn=selector_fn,
        output_name=output_name,
        threshold=threshold,
        release_threshold=release_threshold,
        activate_frames=activate_frames,
        deactivate_frames=deactivate_frames,
        initial_state=initial_state,
    )
    return selector.connect(
        {_BoolSelectorRetargeter.INPUT_VALUE: source_output_selector}
    )
