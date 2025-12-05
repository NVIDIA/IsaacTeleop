#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Helper utilities for creating input nodes and retargeters.
"""

try:
    from teleopcore.retargeting_engine.xrio import HandsInput, ControllersInput, HeadInput
except ImportError:
    HandsInput = None
    ControllersInput = None
    HeadInput = None


def create_standard_inputs(xrio_session_builder):
    """Create standard input nodes that automatically register trackers.
    
    This is a convenience function that creates HandsInput, ControllersInput,
    and HeadInput nodes, which automatically create and register their trackers
    with the provided session builder.
    
    Args:
        xrio_session_builder: XrioSessionBuilder to register trackers with
        
    Returns:
        Dictionary mapping input names to input node instances
        
    Example:
        builder = xrio.XrioSessionBuilder()
        inputs = create_standard_inputs(builder)
        # Returns: {"hands": HandsInput(builder), "controllers": ControllersInput(builder), ...}
    """
    inputs = {}
    
    # Create standard input nodes (they automatically create and register trackers)
    if HandsInput is not None:
        inputs["hands"] = HandsInput(xrio_session_builder, name="hands")
    
    if ControllersInput is not None:
        inputs["controllers"] = ControllersInput(xrio_session_builder, name="controllers")
    
    if HeadInput is not None:
        inputs["head"] = HeadInput(xrio_session_builder, name="head")
    
    return inputs


