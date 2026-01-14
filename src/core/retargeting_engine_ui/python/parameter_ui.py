# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Parameter controls UI using ImGui.

Provides rendering for:
- Boolean parameters (checkboxes)
- Float parameters (sliders)
- Integer parameters (sliders)
- Vector parameters (multi-element sliders)
"""

from typing import TYPE_CHECKING, Any, Tuple

import imgui  # type: ignore[import-not-found]

from teleopcore.retargeting_engine.interface import (
    BoolParameter,
    FloatParameter,
    IntParameter,
    ParameterSpec,
    VectorParameter,
)

if TYPE_CHECKING:
    from teleopcore.retargeting_engine.interface import ParameterState


def render_parameter_control(
    param_name: str,
    param_spec: ParameterSpec,
    current_value: Any
) -> Tuple[bool, Any]:
    """Render ImGui controls for a single parameter.
    
    Args:
        param_name: Name of the parameter
        param_spec: Parameter specification
        current_value: Current value of the parameter (from snapshot)
    
    Returns:
        Tuple of (changed, new_value) - changed is True if value was modified
    """
    changed = False
    new_value = current_value
    
    if isinstance(param_spec, BoolParameter):
        changed, new_value = imgui.checkbox(
            f"{param_name}: {param_spec.description}",
            current_value
        )
    
    elif isinstance(param_spec, FloatParameter):
        imgui.text(f"{param_name}:")
        imgui.text_colored(param_spec.description, 0.6, 0.6, 0.6)
        imgui.push_item_width(-1)
        changed, new_value = imgui.slider_float(
            f"##{param_name}",
            current_value,
            param_spec.min_value,
            param_spec.max_value,
            format="%.3f"
        )
        imgui.pop_item_width()
        # Clamp to avoid floating-point precision issues from ImGui
        if changed:
            new_value = max(param_spec.min_value, min(param_spec.max_value, new_value))
    
    elif isinstance(param_spec, IntParameter):
        imgui.text(f"{param_name}:")
        imgui.text_colored(param_spec.description, 0.6, 0.6, 0.6)
        imgui.push_item_width(-1)
        changed, new_value = imgui.slider_int(
            f"##{param_name}",
            current_value,
            param_spec.min_value,
            param_spec.max_value
        )
        imgui.pop_item_width()
    
    elif isinstance(param_spec, VectorParameter):
        imgui.text(f"{param_name}:")
        imgui.text_colored(param_spec.description, 0.6, 0.6, 0.6)
        
        assert param_spec.element_names is not None, "VectorParameter must have element_names"
        current_vector = list(current_value)
        vector_changed = False
        
        for i, elem_name in enumerate(param_spec.element_names):
            elem_min = float(param_spec.min_value[i]) if param_spec.min_value is not None else 0.0  # type: ignore[index]
            elem_max = float(param_spec.max_value[i]) if param_spec.max_value is not None else 1.0  # type: ignore[index]
            
            imgui.text(f"  {elem_name}:")
            imgui.same_line()
            imgui.push_item_width(-100)
            elem_changed, new_elem_value = imgui.slider_float(
                f"##{param_name}_{i}",
                current_vector[i],
                elem_min,
                elem_max,
                format="%.3f"
            )
            imgui.pop_item_width()
            
            if elem_changed:
                # Clamp to avoid floating-point precision issues from ImGui
                current_vector[i] = max(elem_min, min(elem_max, new_elem_value))
                vector_changed = True
        
        if vector_changed:
            changed = True
            new_value = current_vector
    
    return changed, new_value


class ParameterRenderer:
    """Renders parameter controls for a retargeter.
    
    Handles:
    - Parameter editing controls
    - Save/Load/Reset buttons
    - Status messages
    """
    
    def __init__(self, status_callback=None):
        """Initialize parameter renderer.
        
        Args:
            status_callback: Optional callback for status messages: (message, success) -> None
        """
        self._status_callback = status_callback
    
    def _set_status(self, message: str, success: bool = True) -> None:
        """Set status message via callback."""
        if self._status_callback:
            self._status_callback(message, success)
    
    def render_parameters(
        self,
        name: str,
        param_state: 'ParameterState',
        show_buttons: bool = True
    ) -> None:
        """Render parameter controls for a single retargeter.
        
        Args:
            name: Name of the retargeter
            param_state: Parameter state to render
            show_buttons: Whether to show Save/Load/Reset buttons
        """
        parameters = param_state.get_all_parameter_specs()
        
        if not parameters:
            imgui.text("No tunable parameters")
            return
        
        # Collapsible section - skip rendering if collapsed
        expanded, _ = imgui.collapsing_header(
            f"Parameters##{name}",
            flags=imgui.TREE_NODE_DEFAULT_OPEN
        )
        if not expanded:
            return
        
        imgui.indent()
        
        # Get snapshot of all values
        values = param_state.get_all_values()
        
        # Collect all changes
        updates = {}
        for param_name, param_spec in parameters.items():
            changed, new_value = render_parameter_control(param_name, param_spec, values[param_name])
            if changed:
                updates[param_name] = new_value
            imgui.separator()
        
        # Apply all changes in one batch (UI clamps values so validation should pass)
        if updates:
            param_state.set(updates)
        
        # Individual action buttons
        if show_buttons:
            imgui.spacing()
            
            if imgui.button(f"Save##{name}", width=100):
                if param_state.save_to_file():
                    self._set_status(f"✓ {name}: Configuration saved!", success=True)
                else:
                    self._set_status(f"✗ {name}: Failed to save", success=False)
            
            imgui.same_line()
            
            if imgui.button(f"Reset to Saved##{name}", width=130):
                if param_state.load_from_file():
                    self._set_status(f"✓ {name}: Reset to saved values", success=True)
                else:
                    self._set_status(f"✗ {name}: No saved config", success=False)
            
            imgui.same_line()
            
            if imgui.button(f"Reset to Defaults##{name}", width=150):
                param_state.reset_to_defaults()
                self._set_status(f"✓ {name}: Reset to defaults", success=True)
        
        imgui.unindent()

