# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional
import time

from .tensor_group_type import TensorGroupType
from .tensor_group import OptionalTensorGroup


RetargeterIOType = Dict[str, TensorGroupType]
RetargeterIO = Dict[str, OptionalTensorGroup]


@dataclass(frozen=True)
class GraphTime:
    """Timestamps for a single compute step, in nanoseconds."""

    sim_time_ns: int
    real_time_ns: int


@dataclass
class ComputeContext:
    """Context passed to _compute_fn. Extensible for future per-step metadata."""

    graph_time: GraphTime


def _default_compute_context() -> "ComputeContext":
    """Return a ComputeContext stamped with the current monotonic clock."""
    now = time.monotonic_ns()
    return ComputeContext(graph_time=GraphTime(sim_time_ns=now, real_time_ns=now))


class ExecutionCache:
    """Internal per-step cache for DAG deduplication.

    Carries the ``ComputeContext`` for the current step — created once and shared
    across all nodes — and stores already-computed outputs keyed by node ``id()``
    so shared nodes in a diamond graph are only executed once.
    """

    def __init__(
        self,
        leaf_inputs: Dict[str, RetargeterIO],
        context: "ComputeContext",
    ):
        self.leaf_inputs: Dict[str, RetargeterIO] = leaf_inputs
        self.cached_outputs: Dict[int, RetargeterIO] = {}
        self.context: "ComputeContext" = context

    def get_cached(self, id: int) -> RetargeterIO | None:
        return self.cached_outputs.get(id, None)

    def cache(self, id: int, outputs: RetargeterIO) -> None:
        self.cached_outputs[id] = outputs

    def get_leaf_input(self, name: str) -> RetargeterIO | None:
        return self.leaf_inputs.get(name, None)


class OutputSelector:
    def __init__(self, module: "GraphExecutable", output_name: str):
        self.module = module
        self.output_name = output_name


class BaseExecutable(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Get the name of this executable."""

    @abstractmethod
    def _allocate_outputs(self) -> RetargeterIO:
        """Allocate and return an empty output tensor group dict."""

    @abstractmethod
    def compute(
        self,
        inputs: RetargeterIO,
        outputs: RetargeterIO,
        context: Optional["ComputeContext"] = None,
    ) -> None:
        """
        Execute with pre-resolved inputs and pre-allocated outputs.

        ``outputs`` must be allocated by the caller (e.g. via
        ``_allocate_outputs()``) before this is called. Fills ``outputs``
        in-place; does not return anything.

        ``context`` is the shared per-step ``ComputeContext`` (carrying
        ``GraphTime`` and any future metadata). When called from inside a cache
        execution (e.g. by ``RetargeterSubgraph``), the cache's context is
        forwarded here so every node in the graph receives the same context.
        When ``None``, implementations should auto-generate a context from the
        monotonic clock.

        Args:
            inputs: Pre-resolved input tensor groups.
            outputs: Pre-allocated output tensor groups to fill in-place.
            context: The shared ComputeContext for this compute step.
        """


class GraphExecutable(ABC):
    """
    Interface for graph-executable nodes: internal DAG protocol + public pipeline API.

    The internal side (``_compute_with_cache``, ``output_types``, ``output``,
    ``get_leaf_nodes``) powers DAG traversal and caching.

    The public side (``execute_pipeline``) is the contract used by
    ``TeleopSession`` and any external runner: drive one step given leaf-keyed
    inputs and receive the combined outputs back. ``BaseRetargeter``,
    ``RetargeterSubgraph``, and ``OutputCombiner`` all satisfy this interface
    and can be used interchangeably wherever a pipeline is expected.
    """

    # -------------------------------------------------------------------------
    # Public pipeline API
    # -------------------------------------------------------------------------

    @abstractmethod
    def execute_pipeline(
        self,
        inputs: Dict[str, RetargeterIO],
        context: Optional["ComputeContext"] = None,
    ) -> RetargeterIO:
        """
        Execute the pipeline for one step and return the outputs.

        Args:
            inputs: Dict mapping leaf node names to their input tensor groups.
            context: Per-step context (GraphTime + any future metadata). A context
                     is auto-generated from the monotonic clock when not provided.

        Returns:
            Dict[str, OptionalTensorGroup] - Freshly allocated computed output tensor groups.
        """

    @abstractmethod
    def get_leaf_nodes(self) -> List["BaseExecutable"]:
        """
        Get all leaf nodes (sources) in this graph.

        Returns:
            List[BaseExecutable] - List of module instances that are leaf nodes (sources)
        """

    # -------------------------------------------------------------------------
    # Internal DAG protocol
    # -------------------------------------------------------------------------

    @abstractmethod
    def _compute_with_cache(self, cache: ExecutionCache) -> RetargeterIO:
        pass

    @abstractmethod
    def output_types(self) -> RetargeterIOType:
        """
        Return the output type specification for this executable.

        Returns:
            Dict[str, TensorGroupType] - Output type specification
        """

    def output(self, output_name: str) -> "OutputSelector":
        return OutputSelector(self, output_name)
