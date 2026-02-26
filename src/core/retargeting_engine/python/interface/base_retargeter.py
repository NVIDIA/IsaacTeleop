# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Retargeting module interfaces and base classes.

Defines the common API for retargeting modules with flat (unkeyed) outputs.
"""

from abc import abstractmethod
from typing import Dict, List, Optional
from .tensor_group import TensorGroup, OptionalTensorGroup
from .tensor_group_type import TensorGroupType, OptionalTensorGroupType
from .retargeter_core_types import (
    OutputSelector,
    RetargeterIO,
    ExecutionContext,
    GraphExecutable,
    BaseExecutable,
    RetargeterIOType,
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
    - Compute logic that transforms inputs to outputs
    - Optional tunable parameters for real-time adjustment via GUI

    Base retargeters can be composed using connect() to create ConnectedModules.

    Tunability:
    Subclasses can create a ParameterState with tunable parameters and pass it
    to super().__init__(). The base class will automatically sync parameter values
    to member variables before each compute() call.

    Example:
        class MyRetargeter(BaseRetargeter):
            def __init__(self, name: str, config_file: Optional[str] = None):
                # Create ParameterState with parameters and sync functions
                param_state = ParameterState(name, config_file=config_file)
                param_state.register_parameter(
                    FloatParameter("smoothing", "Smoothing factor", default_value=0.5),
                    sync_fn=lambda v: setattr(self, 'smoothing', v)
                )

                super().__init__(name, parameter_state=param_state)

                # Member var initialized by sync_fn during register_parameter
                # self.smoothing is now 0.5 (or loaded value from config)

            def compute(self, inputs, outputs):
                # self.smoothing is synced from ParameterState before this runs
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

    def _sync_parameters_from_state(self) -> None:
        """
        Sync parameter values from ParameterState (main thread only).

        Called automatically before compute() to apply parameter sync functions.
        """
        if self._parameter_state is None:
            return

        # Let ParameterState apply all sync functions
        self._parameter_state.sync_all()

    def _execute_compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Execute compute with parameter synchronization.

        This wrapper:
        1. Syncs parameters from ParameterState to member vars (before compute)
        2. Calls user's compute() implementation

        Only called when cache miss occurs, ensuring sync happens once per computation.

        Args:
            inputs: Input tensor groups
            outputs: Output tensor groups to populate
        """
        # Sync parameters from state to member vars (main thread only)
        self._sync_parameters_from_state()

        # Call user's compute implementation
        self.compute(inputs, outputs)

    @abstractmethod
    def input_spec(self) -> RetargeterIOType:
        """
        Define input tensor collections.

        Returns a dictionary mapping input names to TensorGroupType.

        Returns:
            Dict[str, TensorGroupType] - Input specification
        """
        pass

    @abstractmethod
    def output_spec(self) -> RetargeterIOType:
        """
        Define output tensor collections.

        Returns a dictionary mapping output names to TensorGroupType.

        Returns:
            Dict[str, TensorGroupType] - Output specification
        """
        pass

    @abstractmethod
    def compute(self, inputs: RetargeterIO, outputs: RetargeterIO) -> None:
        """
        Execute retargeting computation.

        This is the core method that transforms inputs to outputs.

        Args:
            inputs: Input tensor groups (Dict[str, TensorGroup])
            outputs: Output tensor groups to populate (Dict[str, TensorGroup])
        """
        pass

    def output_types(self) -> RetargeterIOType:
        """
        Return the output type specification for this retargeter.

        Returns:
            Dict[str, TensorGroupType] - Output type specification
        """
        return self._outputs

    def get_leaf_nodes(self) -> List[BaseExecutable]:
        """
        Get all leaf nodes (sources) in this graph.

        For a BaseRetargeter, it is a leaf node itself.

        Returns:
            List[BaseExecutable] - List containing this instance
        """
        return [self]

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

    # implements GraphExecutable interface.
    def _compute_in_graph(self, context: ExecutionContext) -> RetargeterIO:
        """
        Compute the retargeter in a graph context.

        Args:
            context: The execution context
        """
        # Check cache first
        cached = context.get_cached(id(self))
        if cached is not None:
            return cached

        # Get inputs from context (if any are needed)
        if len(self._inputs) > 0:  # Only look for inputs if this module has any
            inputs = context.get_leaf_input(self.name)
            if inputs is None:
                raise ValueError(f"Input '{self.name}' not found in context")

            inputs = self._fill_optional_inputs(inputs)
        else:
            # Source modules with no inputs use empty dict
            inputs = {}

        # Create output tensor groups.
        outputs: RetargeterIO = {
            name: _make_output_group(group_type)
            for name, group_type in self._outputs.items()
        }

        # Execute compute with parameter sync (only on cache miss)
        self._validate_inputs(inputs)
        self._execute_compute(inputs, outputs)
        context.cache(id(self), outputs)
        return outputs

    # implements BaseExecutable interface.
    def _compute_without_context(self, inputs: RetargeterIO) -> RetargeterIO:
        """
        Execute the retargeter as a callable (for running outside of a graph context).

        Args:
            inputs: Input tensor groups (Optional entries use OptionalTensorGroup)

        Returns:
            Dict[str, TensorGroup] - Output tensor groups
        """
        inputs = self._fill_optional_inputs(inputs)

        self._validate_inputs(inputs)

        # Create output tensor groups.
        outputs: RetargeterIO = {
            name: _make_output_group(group_type)
            for name, group_type in self._outputs.items()
        }

        # Execute compute with parameter sync
        self._execute_compute(inputs, outputs)

        return outputs

    # For end-user convenience to invoke the retargeter as a callable.
    def __call__(self, inputs: RetargeterIO) -> RetargeterIO:
        return self._compute_without_context(inputs)

    # ========================================================================
    # Tunable Parameters API
    # ========================================================================

    def get_parameter_state(self) -> Optional["ParameterState"]:
        """
        Get the ParameterState instance (thread-safe parameter storage).

        Returns:
            ParameterState instance, or None if retargeter has no tunable parameters

        Example:
            state = retargeter.get_parameter_state()
            state.save_to_file("config.json")
            state.reset_to_defaults()
        """
        return self._parameter_state
