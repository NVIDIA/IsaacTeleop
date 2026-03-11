# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
OutputCombiner - Combines outputs from multiple retargeters into a single output collection.

This is a GraphExecutable that can be used as a source in further connections.
"""

from typing import Dict, List, Optional
from .retargeter_core_types import (
    GraphExecutable,
    ExecutionCache,
    OutputSelector,
    RetargeterIO,
    RetargeterIOType,
    BaseExecutable,
    ComputeContext,
    _default_compute_context,
)


class OutputCombiner(GraphExecutable):
    """
    A graph executable that combines outputs from multiple retargeters with custom names.

    OutputCombiner is itself a GraphExecutable, so it can be used as a source in further
    connections and benefits from execution caching.

    Example:
        # Create retargeters
        left = LeftHandRetargeter("left")
        right = RightHandRetargeter("right")

        # Combine their outputs with custom names
        combiner = OutputCombiner({
            "left_pose": left.output("pose"),
            "right_pose": right.output("pose")
        })

        # Use it in execution
        outputs = combiner({"left": {...}, "right": {...}})
        left_pose = outputs["left_pose"]
        right_pose = outputs["right_pose"]

        # Can also be used as a source for further connections
        next_module = NextModule("next")
        connected = next_module.connect({
            "combined": combiner.output("left_pose")
        })
    """

    def __init__(self, output_mapping: Dict[str, OutputSelector]):
        """
        Initialize an output combiner.

        Args:
            output_mapping: Dict mapping custom output names to OutputSelectors
                           e.g., {"left_pose": left.output("pose")}

        Raises:
            ValueError: If output_mapping is empty
            TypeError: If any value is not an OutputSelector
        """
        if not output_mapping:
            raise ValueError("Must provide at least one output to combine")

        for key, selector in output_mapping.items():
            if not isinstance(selector, OutputSelector):
                raise TypeError(
                    f"Output '{key}': Expected OutputSelector, got {type(selector).__name__}"
                )

        self.output_mapping = output_mapping

        # Build output types from the source modules
        self._output_types: RetargeterIOType = {}
        for custom_name, selector in output_mapping.items():
            source_types = selector.module.output_types()
            if selector.output_name not in source_types:
                raise ValueError(
                    f"Output '{selector.output_name}' not found in source module. "
                    f"Available outputs: {list(source_types.keys())}"
                )
            self._output_types[custom_name] = source_types[selector.output_name]

    def output_types(self) -> RetargeterIOType:
        """
        Return the output type specification for this combiner.

        Returns:
            Dict[str, TensorGroupType] - Output type specification
        """
        return self._output_types

    def _compute_with_cache(self, cache: ExecutionCache) -> RetargeterIO:
        """
        Compute the combiner within an ExecutionCache.

        Executes each source module (with deduplication via the cache) and
        gathers their outputs under the custom names.

        Args:
            cache: The per-step execution cache carrying leaf inputs and context.

        Returns:
            Dict[str, TensorGroup] - Combined outputs with custom names
        """
        outputs = cache.get_cached(id(self))
        if outputs is not None:
            return outputs

        outputs = dict()
        for custom_name, selector in self.output_mapping.items():
            source_outputs = selector.module._compute_with_cache(cache)
            outputs[custom_name] = source_outputs[selector.output_name]

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
        Execute the combiner and return combined outputs.

        Args:
            inputs: Dict[module_name, Dict[str, TensorGroup]] - Inputs for leaf modules.
            context: ComputeContext for this step. Auto-generated from the monotonic
                     clock when not provided.

        Returns:
            Dict[str, TensorGroup] - Combined outputs with custom names
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
        Get all leaf nodes (sources) in this graph.

        This method walks the graph to find all leaf retargeter modules.

        Returns:
            List of module instances that are leaf nodes (sources)
        """
        leaves: List[BaseExecutable] = []
        visited = set()

        for selector in self.output_mapping.values():
            sub_leaves = selector.module.get_leaf_nodes()
            for leaf in sub_leaves:
                if id(leaf) not in visited:
                    leaves.append(leaf)
                    visited.add(id(leaf))

        return leaves
