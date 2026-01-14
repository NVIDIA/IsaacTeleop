# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Camera state management for 3D visualization.

Provides an FPS-style camera with:
- Position (X, Y, Z)
- Orientation (azimuth, elevation)
- Mouse and keyboard input handling
"""

from dataclasses import dataclass, field
from typing import Dict, Tuple

import numpy as np


@dataclass
class CameraState:
    """FPS-style camera state.
    
    Uses standard graphics convention:
    - X points right
    - Y points up
    - Z points toward viewer (out of screen)
    - Forward is -Z (into screen)
    
    Attributes:
        azimuth: Horizontal rotation in degrees (0 = looking toward -Z, 90 = looking toward -X)
        elevation: Vertical rotation in degrees (negative = looking down, positive = looking up)
        x: Camera X position
        y: Camera Y position (height)
        z: Camera Z position (positive = toward viewer)
    """
    azimuth: float = 45.0
    elevation: float = -45.0
    x: float = 2.0
    y: float = 2.0
    z: float = 2.0
    
    def reset(self) -> None:
        """Reset camera to default position and orientation."""
        self.azimuth = 45.0
        self.elevation = -45.0
        self.x = 2.0
        self.y = 2.0
        self.z = 2.0
    
    def get_forward_vector(self) -> Tuple[float, float]:
        """Get forward direction on XZ plane based on azimuth.
        
        Forward is -Z at azimuth=0.
        At azimuth=0: forward = (0, -1) → looking toward -Z
        At azimuth=90: forward = (-1, 0) → looking toward -X
        
        Returns:
            Tuple of (forward_x, forward_z)
        """
        azimuth_rad = np.radians(self.azimuth)
        forward_x = -np.sin(azimuth_rad)
        forward_z = -np.cos(azimuth_rad)
        return forward_x, forward_z
    
    def get_right_vector(self) -> Tuple[float, float]:
        """Get right direction on XZ plane (perpendicular to forward).
        
        Right is +X at azimuth=0.
        
        Returns:
            Tuple of (right_x, right_z)
        """
        azimuth_rad = np.radians(self.azimuth)
        right_x = np.cos(azimuth_rad)
        right_z = -np.sin(azimuth_rad)
        return right_x, right_z
    
    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary representation."""
        return {
            'azimuth': self.azimuth,
            'elevation': self.elevation,
            'x': self.x,
            'y': self.y,
            'z': self.z,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> 'CameraState':
        """Create from dictionary representation."""
        return cls(
            azimuth=data.get('azimuth', 45.0),
            elevation=data.get('elevation', -45.0),
            x=data.get('x', 2.0),
            y=data.get('y', 2.0),
            z=data.get('z', 2.0),
        )


class CameraController:
    """Handles camera input and movement.
    
    Provides:
    - Mouse drag for rotation (right-click)
    - WASD for horizontal movement
    - Q/E for vertical movement
    - Middle-click for reset
    """
    
    def __init__(self):
        """Initialize camera controller."""
        self._mouse_right_dragging = False
        self._last_mouse_pos = (0.0, 0.0)
        self._move_speed = 0.05  # Units per frame
        self._look_sensitivity = 0.5  # Degrees per pixel
    
    @property
    def is_dragging(self) -> bool:
        """Check if currently dragging with right mouse button."""
        return self._mouse_right_dragging
    
    def start_drag(self, mouse_pos: Tuple[float, float]) -> None:
        """Start mouse drag for camera rotation.
        
        Args:
            mouse_pos: Current mouse position (x, y)
        """
        self._mouse_right_dragging = True
        self._last_mouse_pos = mouse_pos
    
    def stop_drag(self) -> None:
        """Stop mouse drag for camera rotation."""
        self._mouse_right_dragging = False
    
    def update_drag(self, camera: CameraState, mouse_pos: Tuple[float, float]) -> None:
        """Update camera rotation based on mouse movement.
        
        Args:
            camera: Camera state to update
            mouse_pos: Current mouse position (x, y)
        """
        if not self._mouse_right_dragging:
            return
        
        dx = mouse_pos[0] - self._last_mouse_pos[0]
        dy = mouse_pos[1] - self._last_mouse_pos[1]
        
        camera.azimuth = (camera.azimuth - dx * self._look_sensitivity) % 360.0
        camera.elevation = np.clip(camera.elevation - dy * self._look_sensitivity, -89.0, 89.0)
        
        self._last_mouse_pos = mouse_pos
    
    def apply_keyboard_movement(
        self,
        camera: CameraState,
        forward: bool = False,
        backward: bool = False,
        left: bool = False,
        right: bool = False,
        up: bool = False,
        down: bool = False
    ) -> None:
        """Apply keyboard movement to camera.
        
        WASD moves on XZ plane, Q/E moves vertically.
        
        Args:
            camera: Camera state to update
            forward: W key pressed
            backward: S key pressed
            left: A key pressed
            right: D key pressed
            up: E key pressed
            down: Q key pressed
        """
        forward_x, forward_z = camera.get_forward_vector()
        right_x, right_z = camera.get_right_vector()
        
        move_dx = 0.0
        move_dy = 0.0
        move_dz = 0.0
        
        # WASD - horizontal movement only (XZ plane)
        if forward:
            move_dx += forward_x * self._move_speed
            move_dz += forward_z * self._move_speed
        if backward:
            move_dx -= forward_x * self._move_speed
            move_dz -= forward_z * self._move_speed
        if left:
            move_dx -= right_x * self._move_speed
            move_dz -= right_z * self._move_speed
        if right:
            move_dx += right_x * self._move_speed
            move_dz += right_z * self._move_speed
        
        # Q/E - vertical movement only (Y axis)
        if down:
            move_dy -= self._move_speed
        if up:
            move_dy += self._move_speed
        
        # Apply movement
        if abs(move_dx) > 0.001 or abs(move_dy) > 0.001 or abs(move_dz) > 0.001:
            camera.x += move_dx
            camera.y += move_dy
            camera.z += move_dz

