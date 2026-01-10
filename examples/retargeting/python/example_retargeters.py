# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Shared retargeter examples for demos.

Provides reusable example retargeters that can be used across multiple demos.
"""

from typing import Optional

import numpy as np

from teleopcore.retargeting_engine.interface import (
    BaseRetargeter,
    BoolParameter,
    FloatParameter,
    IntParameter,
    ParameterState,
    TensorGroup,
    TensorGroupType,
    VectorParameter,
)
from teleopcore.retargeting_engine.tensor_types import FloatType


class GainOffsetRetargeter(BaseRetargeter):
    """
    Simple retargeter that applies gain and offset to input values.
    
    Output = (Input * gain) + offset
    
    This retargeter is useful for demonstrations and testing the tuning UI.
    """
    
    def __init__(self, name: str, config_file: Optional[str] = None):
        """
        Initialize the gain+offset retargeter.
        
        Args:
            name: Name identifier for this retargeter
            config_file: Optional path to config file for parameter persistence
        """
        self._input_types = {
            "value": TensorGroupType("value", [FloatType("x")])
        }
        
        self._output_types = {
            "value": TensorGroupType("value", [FloatType("x")])
        }
        
        # Create parameters with sync functions
        parameters = [
            FloatParameter(
                "gain", 
                "Multiply input by this factor", 
                default_value=1.0, 
                min_value=0.0, 
                max_value=5.0,
                sync_fn=lambda val: setattr(self, 'gain', val)
            ),
            FloatParameter(
                "offset", 
                "Add this value to result", 
                default_value=0.0, 
                min_value=-5.0, 
                max_value=5.0,
                sync_fn=lambda val: setattr(self, 'offset', val)
            )
        ]
        param_state = ParameterState(name, parameters=parameters, config_file=config_file)
        
        # Initialize base retargeter with parameter state
        super().__init__(name, parameter_state=param_state)
    
    def input_spec(self) -> dict:
        """Define input specification."""
        return self._input_types
    
    def output_spec(self) -> dict:
        """Define output specification."""
        return self._output_types
    
    def compute(self, inputs: dict, outputs: dict) -> None:
        """Apply gain and offset transformation."""
        input_val = inputs["value"][0]
        outputs["value"][0] = (input_val * self.gain) + self.offset


class SimpleTunableRetargeter(BaseRetargeter):
    """
    A simple retargeter demonstrating various tunable parameter types.
    
    Includes bool, float, int, and vector parameters for UI testing.
    """
    
    def __init__(self, name: str, config_file: Optional[str] = None):
        """
        Initialize the simple tunable retargeter.
        
        Args:
            name: Name identifier for this retargeter
            config_file: Optional path to config file for parameter persistence
        """
        parameters = [
            BoolParameter(
                "enable_processing", 
                "Enable/disable processing", 
                default_value=True,
                sync_fn=lambda v: setattr(self, 'enable_processing', v)
            ),
            FloatParameter(
                "gain", 
                "Gain multiplier", 
                default_value=1.0, 
                min_value=0.0, 
                max_value=10.0,
                sync_fn=lambda v: setattr(self, 'gain', v)
            ),
            FloatParameter(
                "bias", 
                "Bias offset", 
                default_value=0.0,
                min_value=-10.0,
                max_value=10.0,
                sync_fn=lambda v: setattr(self, 'bias', v)
            ),
            IntParameter(
                "sample_count", 
                "Number of samples", 
                default_value=5, 
                min_value=1, 
                max_value=100,
                sync_fn=lambda v: setattr(self, 'sample_count', v)
            ),
            VectorParameter(
                "rgb_color", 
                "RGB color", 
                element_names=["R", "G", "B"],
                default_value=np.array([1.0, 0.5, 0.0]), 
                min_value=0.0, 
                max_value=1.0,
                sync_fn=lambda v: setattr(self, 'rgb_color', v)
            )
        ]
        param_state = ParameterState(name, parameters=parameters, config_file=config_file)
        
        super().__init__(name, parameter_state=param_state)
    
    def input_spec(self):
        """Define input specification."""
        return {"input_value": TensorGroupType("input_value", [FloatType("value")])}
    
    def output_spec(self):
        """Define output specification."""
        return {"result": TensorGroupType("result", [FloatType("processed_value")])}
    
    def compute(self, inputs, outputs):
        """Apply processing based on parameters."""
        input_val = float(inputs["input_value"][0])
        
        if self.enable_processing:
            outputs["result"][0] = input_val * self.gain + self.bias
        else:
            outputs["result"][0] = input_val

