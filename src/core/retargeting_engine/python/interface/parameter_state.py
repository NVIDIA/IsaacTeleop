# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Thread-safe parameter state for retargeter tuning.

Stores parameter values and sync functions. The UI thread writes values,
and the main thread calls sync_all() to apply them to member variables.
"""

import json
import threading
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List
from .tunable_parameter import ParameterSpec


class ParameterState:
    """
    Thread-safe parameter state storage with sync functions.
    
    Manages parameter values and syncs them to retargeter member variables.
    - UI thread: Calls set() to update values
    - Main thread: Calls sync_all() to apply sync functions
    - Handles config load/save to JSON
    
    Example:
        # Create parameters with sync functions
        parameters = [
            FloatParameter("gain", "Gain value", default_value=1.0, 
                          sync_fn=lambda v: setattr(self, 'gain', v)),
            BoolParameter("enabled", "Enable feature", default_value=True,
                         sync_fn=lambda v: setattr(self, 'enabled', v))
        ]
        
        # Create state in retargeter __init__
        param_state = ParameterState("MyRetargeter", parameters, config_file="config.json")
        # sync_fn is called immediately with initial/loaded value
        
        # Pass to BaseRetargeter
        super().__init__(name, parameter_state=param_state)
        
        # BaseRetargeter calls sync_all() before each compute()
    """
    
    def __init__(self, 
                 name: str, 
                 parameters: List[ParameterSpec],
                 config_file: Optional[str] = None):
        """
        Initialize parameter state.
        
        Args:
            name: Name for this parameter state (for logging)
            parameters: List of parameter specifications to register (must have at least one)
            config_file: Optional path to config file for auto-load/save
            
        Raises:
            ValueError: If parameters list is empty
        """
        if not parameters:
            raise ValueError("ParameterState requires at least one parameter")
        
        self._name = name
        self._parameters: Dict[str, ParameterSpec] = {}
        self._values: Dict[str, Any] = {}  # Store actual parameter values separately
        self._config_file = Path(config_file) if config_file else None
        self._lock = threading.Lock()
        self._loaded_config: Dict[str, Any] = {}
        
        # Try to load from config file if it exists
        if self._config_file and self._config_file.exists():
            self._load_config_values()
        
        # Register all parameters
        for param in parameters:
            self._register_parameter(param)
    
    def _load_config_values(self) -> None:
        """Load config values into cache (called before parameters are registered)."""
        if self._config_file is None or not self._config_file.exists():
            return
        
        try:
            with open(self._config_file, 'r') as f:
                self._loaded_config = json.load(f)
            print(f"[ParameterState:{self._name}] Loaded config from {self._config_file}")
        except Exception as e:
            print(f"[ParameterState:{self._name}] Failed to load config: {e}")
    
    def _register_parameter(self, parameter: ParameterSpec) -> None:
        """
        Register a parameter (internal, called from __init__).
        
        The sync function from parameter.sync_fn is called:
        - Immediately with the initial value (or loaded config value)
        - On every sync_all() call to update member variables
        
        Args:
            parameter: Parameter specification with optional sync_fn
        """
        self._parameters[parameter.name] = parameter
        
        # Initialize value from default or loaded config
        if parameter.name in self._loaded_config:
            try:
                self._values[parameter.name] = parameter.deserialize(self._loaded_config[parameter.name])
            except Exception as e:
                print(f"[ParameterState:{self._name}] Failed to apply config for {parameter.name}: {e}")
                self._values[parameter.name] = parameter.get_default_value()
        else:
            self._values[parameter.name] = parameter.get_default_value()
        
        # Call sync_fn immediately with current value
        if parameter.sync_fn is not None:
            parameter.sync_fn(self._values[parameter.name])
    
    def sync_all(self) -> None:
        """
        Call all sync functions with current parameter values (main thread only).
        
        This is called by BaseRetargeter before each compute() to sync
        parameter values to member variables.
        """
        with self._lock:
            for param_name, param_spec in self._parameters.items():
                if param_spec.sync_fn is not None:
                    param_spec.sync_fn(self._values[param_name])
    
    def get(self, names: List[str]) -> Dict[str, Any]:
        """
        Get values for specified parameters (thread-safe deep snapshot).
        
        Args:
            names: List of parameter names to get
            
        Returns:
            Dictionary mapping parameter names to their current values (deep copy)
            
        Raises:
            KeyError: If any parameter name is not found
        """
        import copy
        with self._lock:
            result = {}
            for name in names:
                if name not in self._parameters:
                    raise KeyError(f"Parameter '{name}' not found")
                result[name] = copy.deepcopy(self._values[name])
            return result
    
    def set(self, updates: Dict[str, Any]) -> None:
        """
        Set multiple parameter values atomically (thread-safe).
        
        All updates are applied within a single lock acquisition.
        
        Args:
            updates: Dictionary mapping parameter names to new values
            
        Raises:
            KeyError: If any parameter name is not found
            ValueError: If any value is invalid for its parameter
        """
        with self._lock:
            for name, value in updates.items():
                if name not in self._parameters:
                    raise KeyError(f"Parameter '{name}' not found")
                param_spec = self._parameters[name]
                if not param_spec.validate(value):
                    raise ValueError(f"Invalid value for parameter '{name}': {value}")
                self._values[name] = value
    
    def get_all_parameter_specs(self) -> Dict[str, ParameterSpec]:
        """Get all parameter specifications (immutable, no copy needed)."""
        return self._parameters
    
    def get_all_values(self) -> Dict[str, Any]:
        """
        Get all parameter values as a dictionary (thread-safe deep snapshot).
        
        This method acquires the lock once and returns a deep copy of all values,
        avoiding race conditions when multiple parameters need to be read together.
        Values are deep-copied to prevent external modification (especially for numpy arrays).
        
        Returns:
            Dictionary mapping parameter names to their current values (deep copy)
        """
        import copy
        with self._lock:
            return copy.deepcopy(self._values)
    
    def save_to_file(self, file_path: Optional[str] = None) -> bool:
        """Save current parameter values to JSON config file."""
        if file_path is None:
            file_path = str(self._config_file) if self._config_file else None
        
        if file_path is None:
            print(f"[ParameterState:{self._name}] No config file path specified")
            return False
        
        try:
            with self._lock:
                config = {}
                for param_name, param_spec in self._parameters.items():
                    if param_spec.saveable:
                        config[param_name] = param_spec.serialize(self._values[param_name])
            
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(path, 'w') as f:
                json.dump(config, f, indent=2)
            
            print(f"[ParameterState:{self._name}] Saved to {path}")
            return True
            
        except Exception as e:
            print(f"[ParameterState:{self._name}] Failed to save: {e}")
            return False
    
    def load_from_file(self, file_path: Optional[str] = None) -> bool:
        """Load parameter values from JSON config file."""
        if file_path is None:
            file_path = str(self._config_file) if self._config_file else None
        
        if file_path is None or not Path(file_path).exists():
            return False
        
        try:
            with open(file_path, 'r') as f:
                config = json.load(f)
            
            with self._lock:
                for param_name, value in config.items():
                    if param_name in self._parameters:
                        self._values[param_name] = self._parameters[param_name].deserialize(value)
            
            print(f"[ParameterState:{self._name}] Loaded from {file_path}")
            return True
            
        except Exception as e:
            print(f"[ParameterState:{self._name}] Failed to load: {e}")
            return False
    
    def reset_to_defaults(self) -> None:
        """Reset all parameters to their default values."""
        with self._lock:
            for param_name, param_spec in self._parameters.items():
                self._values[param_name] = param_spec.get_default_value()

