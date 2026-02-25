# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Retargeting module interfaces and base classes.

Defines the common API for retargeting modules with flat (unkeyed) outputs.

API layers:
    _compute_fn(inputs, outputs, context)          -- abstract, what subclasses implement
    compute(inputs, outputs, context=None)         -- external API, fills outputs in-place
    __call__(inputs, context=None)                 -- convenience API, allocates and returns outputs
    execute_pipeline({name: inputs}, context=None) -- GraphExecutable pipeline API (single-node graph)
"""

from abc import abstractmethod
from typing import Dict, List, Optional
from .tensor_group import TensorGroup, OptionalTensorGroup
from .tensor_group_type import TensorGroupType, OptionalTensorGroupType
from .retargeter_core_types import (
    OutputSelector,
    RetargeterIO,
    ExecutionCache,
    GraphExecutable,
    BaseExecutable,
    RetargeterIOType,
    ComputeContext,
    _default_compute_context,
)
from .retargeter_subgraph import RetargeterSubgraph
from .parameter_state import ParameterState


def _make_output_group(group_type: TensorGroupType) -> OptionalTensorGroup:
    """Create a TensorGroup or OptionalTensorGroup based on the spec type."""
    if isinstance(group_type, OptionalTensorGroupType):
        return OptionalTensorGroup(group_type)
    return TensorGroup(group_type)


class BaseRetargeter(BaseExecutable, GraphExecutable):
    """
    Abstract base class for base retargeting modules.

    A base retargeter defines:
    - Input tensor collections: Dict[str, TensorGroupType] (unkeyed - by input name)
    - Output tensor collections: Dict[str, TensorGroupType] (unkeyed - by output name)
    - Compute logic that transforms inputs to outputs via _compute_fn()
    - Optional tunable parameters for real-time adjustment via GUI

    Base retargeters can be composed using connect() to create ConnectedModules.

    Subclasses implement _compute_fn(inputs, outputs, context) where *context*
    carries the current GraphTime and is extensible for future metadata.

    External callers use one of:
        compute(inputs, outputs, context=None)  -- fills outputs in-place
        __call__(inputs, context=None)          -- allocates fresh outputs each call
        execute_pipeline(inputs, context=None)  -- pipeline API

    Tunability:
    Subclasses can create a ParameterState with tunable parameters and pass it
    to super().__init__(). The base class will automatically sync parameter values
    to member variables before each _compute_fn() call.

    Example:
        class MyRetargeter(BaseRetargeter):
            def __init__(self, name: str, config_file: Optional[str] = None):
                param_state = ParameterState(name, config_file=config_file)
                param_state.register_parameter(
                    FloatParameter("smoothing", "Smoothing factor", default_value=0.5),
                    sync_fn=lambda v: setattr(self, 'smoothing', v)
                )

                super().__init__(name, parameter_state=param_state)

            def _compute_fn(self, inputs, outputs, context):
                # self.smoothing is synced from ParameterState before this runs
                # context.graph_time is available for time-dependent logic
                outputs["result"][0] = inputs["x"][0] * self.smoothing
    """

    def __init__(
        self, name: str, parameter_state: Optional[ParameterState] = None
    ) -> None:
        """
        Initialize a base retargeter.

        Args:
            name: Name identifier for this retargeter.
            parameter_state: Optional ParameterState for tunable parameters.
        """
        self._name = name
        self._inputs: RetargeterIOType = self.input_spec()
        self._outputs: RetargeterIOType = self.output_spec()
        self._parameter_state: Optional[ParameterState] = parameter_state

    @property
    def name(self) -> str:
        """Get the name of this retargeter."""
        return self._name

    # ========================================================================
    # Subclass contract — subclasses must implement these
    # ========================================================================

    @abstractmethod
    def input_spec(self) -> RetargeterIOType:
        """
        Define input tensor collections.

        Returns:
            Dict[str, TensorGroupType] - Input specification
        """
        pass

    @abstractmethod
    def output_spec(self) -> RetargeterIOType:
        """
        Define output tensor collections.

        Returns:
            Dict[str, TensorGroupType] - Output specification
        """
        pass

    @abstractmethod
    def _compute_fn(
        self, inputs: RetargeterIO, outputs: RetargeterIO, context: ComputeContext
    ) -> None:
        """
        Execute retargeting computation.

        This is the core method that subclasses implement. It is called by the
        framework after parameter sync. ``context`` is the same shared object
        for every node in a graph step. Time information is available via
        ``context.graph_time``.

        ``outputs`` arrives pre-populated with one ``TensorGroup`` per key from
        ``output_spec()``.  Implementations may either write into the existing
        groups in-place (``outputs["key"][i] = value``) or replace a group
        entirely (``outputs["key"] = new_group``).  Both are valid — the
        framework makes no guarantee about whether the incoming groups are
        freshly allocated or reused from a prior step.

        .. warning::
            Do **not** read from ``outputs`` to carry state across steps — the
            groups contain ``UNSET_VALUE`` on the first call and reading any
            tensor will raise ``ValueError``.  Use instance variables
            (``self._foo``) for cross-step state.

        Args:
            inputs: Input tensor groups (Dict[str, TensorGroup])
            outputs: Output tensor groups to populate (Dict[str, TensorGroup])
            context: Compute context containing graph time and future metadata
        """
        pass

    # ========================================================================
    # Public convenience API — not part of any abstract contract
    # ========================================================================

    def __call__(
        self,
        inputs: RetargeterIO,
        context: Optional[ComputeContext] = None,
    ) -> RetargeterIO:
        """
        Convenience API: allocate fresh outputs and return them.

        Args:
            inputs: Input tensor groups.
            context: ComputeContext for this step. Auto-generated from the monotonic
                     clock when not provided.

        Returns:
            Dict[str, TensorGroup] — freshly allocated, independently owned outputs.
        """
        if context is None:
            context = _default_compute_context()
        outputs = self._allocate_outputs()
        self.compute(inputs, outputs, context)
        return outputs

    def connect(
        self, input_connections: Dict[str, OutputSelector]
    ) -> RetargeterSubgraph:
        """
        Connect this retargeter's inputs to outputs from other retargeters.

        Required inputs must all be present in *input_connections*.
        Optional inputs may be omitted — they will receive an absent
        ``OptionalTensorGroup`` at runtime (check ``.is_none`` before access).

        Args:
            input_connections: Dict mapping this retargeter's input names to
                OutputSelectors.

        Returns:
            A RetargeterSubgraph (compound retargeter)

        Example:
            processor.connect({
                "left_hand": source.output("left"),
                "right_hand": right.output("pose")
            })
        """

        # Check for extra inputs that don't exist in the spec
        extra = set(input_connections.keys()) - set(self._inputs.keys())
        if extra:
            raise ValueError(f"Input mismatch for {self.name}: Extra inputs: {extra}")

        # Check that all required inputs are provided; optional may be omitted
        missing_required = set()
        for input_name, input_type in self._inputs.items():
            if input_name not in input_connections and not input_type.is_optional:
                missing_required.add(input_name)

        if missing_required:
            raise ValueError(
                f"Input mismatch for {self.name}: "
                f"Missing required inputs: {missing_required}"
            )

        # Validate type compatibility for connected inputs
        for input_name, output_selector in input_connections.items():
            expected_type = self._inputs[input_name]
            actual_type = output_selector.module.output_types()[
                output_selector.output_name
            ]
            expected_type.check_compatibility(actual_type)

        return RetargeterSubgraph(
            target_module=self,
            input_connections=input_connections,
            output_types=self._outputs,
        )

    # ========================================================================
    # GraphExecutable implementation
    # ========================================================================

    def execute_pipeline(
        self,
        inputs: Dict[str, RetargeterIO],
        context: Optional[ComputeContext] = None,
    ) -> RetargeterIO:
        """
        Implements ``GraphExecutable.execute_pipeline``.

        Satisfies the ``GraphExecutable.execute_pipeline`` contract so a standalone
        ``BaseRetargeter`` can be used wherever a pipeline is expected. The caller
        must supply inputs keyed by this node's name: ``{self.name: {...}}``.

        Args:
            inputs: Dict mapping this node's name to its flat input tensor groups.
            context: ComputeContext for this step. Auto-generated from the monotonic
                     clock when not provided.

        Returns:
            Dict[str, TensorGroup] — freshly allocated populated output groups.
        """
        if context is None:
            context = _default_compute_context()
        node_inputs = inputs.get(self.name, {})
        outputs = self._allocate_outputs()
        self.compute(node_inputs, outputs, context)
        return outputs

    def output_types(self) -> RetargeterIOType:
        """
        Implements ``GraphExecutable.output_types``.

        Returns:
            Dict[str, TensorGroupType] - Output type specification
        """
        return self._outputs

    def get_leaf_nodes(self) -> List[BaseExecutable]:
        """
        Implements ``GraphExecutable.get_leaf_nodes``.

        A ``BaseRetargeter`` is always a leaf node — it has no upstream dependencies.

        Returns:
            List containing only ``self``.
        """
        return [self]

    def _compute_with_cache(self, cache: ExecutionCache) -> RetargeterIO:
        """
        Implements ``GraphExecutable._compute_with_cache``.

        Retrieves this node's leaf inputs from ``cache`` by name, delegates to
        ``compute`` with the cache's shared context, then stores
        the result for DAG deduplication.

        Args:
            cache: The per-step execution cache carrying leaf inputs and context.
        """
        cached = cache.get_cached(id(self))
        if cached is not None:
            return cached

        if len(self._inputs) > 0:
            inputs = cache.get_leaf_input(self.name)
            if inputs is None:
                has_required = any(not t.is_optional for t in self._inputs.values())
                if has_required:
                    raise ValueError(f"Input '{self.name}' not found in cache")
                inputs = {}
        else:
            inputs = {}

        outputs = self._allocate_outputs()
        self.compute(inputs, outputs, cache.context)
        cache.cache(id(self), outputs)
        return outputs

    # ========================================================================
    # BaseExecutable implementation
    # ========================================================================

    def compute(
        self,
        inputs: RetargeterIO,
        outputs: RetargeterIO,
        context: Optional[ComputeContext] = None,
    ) -> None:
        """
        Implements ``BaseExecutable.compute``.

        Fills optional inputs, validates, syncs parameters, then calls
        ``_compute_fn``. Fills ``outputs`` in-place; does not return anything.

        Args:
            inputs: Input tensor groups (raw; optional entries filled here).
            outputs: Pre-allocated output tensor groups to fill in-place.
            context: The shared ComputeContext for this compute step.
                     Auto-generated from the monotonic clock when not provided.
        """
        if context is None:
            context = _default_compute_context()
        inputs = self._fill_optional_inputs(inputs)
        self._validate_inputs(inputs)
        self._execute_compute(inputs, outputs, context)

    def _allocate_outputs(self) -> RetargeterIO:
        """
        Implements ``BaseExecutable._allocate_outputs``.

        Allocates a fresh output tensor group dict matching this node's output spec.
        """
        return {
            name: _make_output_group(group_type)
            for name, group_type in self._outputs.items()
        }

    # ========================================================================
    # Internal helpers
    # ========================================================================

    def _fill_optional_inputs(self, inputs: RetargeterIO) -> RetargeterIO:
        """Return a new dict with absent OptionalTensorGroups for missing optional inputs.

        Required inputs that are missing raise ``ValueError``.
        The caller's dict is never mutated.
        """
        filled: RetargeterIO | None = None
        for name, input_type in self._inputs.items():
            if name not in inputs:
                if input_type.is_optional:
                    if filled is None:
                        filled = dict(inputs)
                    filled[name] = OptionalTensorGroup(input_type.inner_type)
                else:
                    raise ValueError(
                        f"Required input '{name}' missing for '{self.name}'"
                    )
        return filled if filled is not None else inputs

    def _validate_inputs(self, inputs: RetargeterIO) -> None:
        """
        Validate the inputs to the retargeter.

        Absent ``OptionalTensorGroup`` entries are permitted for Optional inputs.
        Missing keys are permitted for Optional inputs (filled with absent groups).

        Args:
            inputs: The inputs to the retargeter
        """
        # Check for unexpected extra keys
        extra = set(inputs.keys()) - set(self._inputs.keys())
        if extra:
            raise ValueError(
                f"Unexpected inputs {extra} (expected {set(self._inputs.keys())})"
            )

        for name, expected_type in self._inputs.items():
            if name not in inputs:
                if not expected_type.is_optional:
                    raise ValueError(f"Required input '{name}' is missing")
                continue

            input_group = inputs[name]

            if expected_type.is_optional and input_group.is_none:
                continue

            inner_expected = expected_type.inner_type
            inner_expected.check_compatibility(input_group.group_type)

    def _execute_compute(
        self, inputs: RetargeterIO, outputs: RetargeterIO, context: ComputeContext
    ) -> None:
        """Sync parameters then dispatch to ``_compute_fn``."""
        self._sync_parameters_from_state()
        self._compute_fn(inputs, outputs, context)

    def _sync_parameters_from_state(self) -> None:
        """Flush ``ParameterState`` values to member variables before ``_compute_fn`` runs."""
        if self._parameter_state is None:
            return
        self._parameter_state.sync_all()

    # ========================================================================
    # Tunable parameters API
    # ========================================================================

    def get_parameter_state(self) -> Optional["ParameterState"]:
        """
        Get the ParameterState instance (thread-safe parameter storage).

        Returns:
            ParameterState instance, or None if retargeter has no tunable parameters
        """
        return self._parameter_state
