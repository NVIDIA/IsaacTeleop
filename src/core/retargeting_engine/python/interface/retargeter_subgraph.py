# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
RetargeterSubgraph - Represents a connected subgraph of retargeters.

A subgraph wraps a target retargeter module with its input connections,
enabling composition of retargeters into larger computational graphs.
"""

from typing import Dict, List, Optional
from .retargeter_core_types import (
    GraphExecutable,
    BaseExecutable,
    RetargeterIOType,
    ExecutionCache,
    OutputSelector,
    RetargeterIO,
    ComputeContext,
    _default_compute_context,
)


class RetargeterSubgraph(GraphExecutable):
    """
    A subgraph of retargeters with resolved input connections.

    This class wraps a target retargeter module along with its input connections,
    enabling it to be executed as part of a larger computational graph. It handles:
    - Resolving inputs from connected source modules
    - Caching computation results to avoid redundant executions
    - Executing the target module with resolved inputs

    The subgraph is created automatically by calling connect() on a BaseRetargeter.
    """

    def __init__(
        self,
        target_module: BaseExecutable,
        input_connections: Dict[str, OutputSelector],
        output_types: RetargeterIOType,
    ) -> None:
        """
        Initialize a retargeter subgraph.

        Args:
            target_module: The retargeter module to execute with connected inputs
            input_connections: Dict mapping input names to their source OutputSelectors
            output_types: Type specification for the outputs (from target module)
        """
        self._target_module = target_module
        self._input_connections = input_connections
        self._output_types = output_types

    def output_types(self) -> RetargeterIOType:
        """
        Return the output type specification for this subgraph.

        The output types match those of the wrapped target module.

        Returns:
            Dict[str, TensorGroupType] - Output type specification
        """
        return self._output_types

    def _compute_with_cache(self, cache: ExecutionCache) -> RetargeterIO:
        """
        Compute the subgraph within an ExecutionCache.

        1. Returns cached result immediately on a cache hit.
        2. Recursively resolves inputs by executing connected source modules
           (each of which also goes through the cache for deduplication).
        3. Allocates outputs via ``_target_module._allocate_outputs()``, then
           executes via ``compute``, forwarding ``cache.context``
           so the target node receives the same shared ``ComputeContext``.
        4. Stores the result in the cache and returns it.

        Args:
            cache: The per-step execution cache carrying leaf inputs and context.

        Returns:
            Dict[str, TensorGroup] - The computed output tensor groups
        """
        cached_outputs = cache.get_cached(id(self))
        if cached_outputs is not None:
            return cached_outputs

        # Resolve inputs from connected upstream modules
        inputs = {}
        for input_name, input_selector in self._input_connections.items():
            source_outputs = input_selector.module._compute_with_cache(cache)
            inputs[input_name] = source_outputs[input_selector.output_name]

        # Execute target module with the shared context from the cache.
        # Key output buffers by id(self) so two subgraphs wrapping the same
        # target module never share the same output buffer.
        # target node receives the same shared ``ComputeContext``.
        # _compute_with_cache handles optional-input filling and validation.
        outputs = self._target_module._allocate_outputs()
        self._target_module.compute(inputs, outputs, cache.context)
        cache.cache(id(self), outputs)
        return outputs

    # ========================================================================
    # External API
    # ========================================================================

    def execute_pipeline(
        self,
        inputs: Dict[str, RetargeterIO],
        context: Optional[ComputeContext] = None,
    ) -> RetargeterIO:
        """
        Execute the subgraph and return its outputs.

        Args:
            inputs: Dict mapping leaf module names to their input tensor groups.
            context: ComputeContext for this step. Auto-generated from the monotonic
                     clock when not provided.

        Returns:
            Dict[str, TensorGroup] - The computed output tensor groups
        """
        if context is None:
            context = _default_compute_context()
        return self._compute_with_cache(ExecutionCache(inputs, context))

    def __call__(
        self,
        inputs: Dict[str, RetargeterIO],
        context: Optional[ComputeContext] = None,
    ) -> RetargeterIO:
        return self.execute_pipeline(inputs, context)

    def get_leaf_nodes(self) -> List[BaseExecutable]:
        """
        Get all leaf nodes (sources) in this subgraph.

        This method walks the graph to find all leaf retargeter modules.

        Returns:
            List of module instances that are leaf nodes (sources)
        """
        leaves: List[BaseExecutable] = []
        visited = set()

        for output_selector in self._input_connections.values():
            sub_leaves = output_selector.module.get_leaf_nodes()
            for leaf in sub_leaves:
                if id(leaf) not in visited:
                    leaves.append(leaf)
                    visited.add(id(leaf))

        return leaves
