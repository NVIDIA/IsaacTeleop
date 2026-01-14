# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Math utilities for 3D visualization.

Provides helper functions for:
- Quaternion operations
- 3D to 2D projection
"""

import numpy as np
from dataclasses import dataclass
from typing import Tuple


@dataclass
class CachedCameraTransform:
    """Pre-computed camera transform values to avoid redundant trig calls."""
    cos_az: float
    sin_az: float
    cos_el: float
    sin_el: float
    focal_length: float
    half_width: float
    half_height: float
    cam_x: float
    cam_y: float
    cam_z: float
    near_plane: float
    
    # Cache key to detect when camera changed
    _key: Tuple[float, ...] = None
    
    @classmethod
    def create(cls, azimuth: float, elevation: float, width: float, height: float,
               cam_x: float, cam_y: float, cam_z: float, fov: float = 60.0,
               near_plane: float = 0.1) -> 'CachedCameraTransform':
        """Create a cached transform, computing trig only once."""
        azimuth_rad = np.radians(azimuth)
        elevation_rad = np.radians(elevation)
        fov_rad = np.radians(fov)
        tan_half_fov = np.tan(fov_rad / 2.0)
        focal_length = (height / 2.0) / tan_half_fov if tan_half_fov > 0 else height
        
        return cls(
            cos_az=np.cos(azimuth_rad),
            sin_az=np.sin(azimuth_rad),
            cos_el=np.cos(elevation_rad),
            sin_el=np.sin(elevation_rad),
            focal_length=focal_length,
            half_width=width / 2.0,
            half_height=height / 2.0,
            cam_x=cam_x,
            cam_y=cam_y,
            cam_z=cam_z,
            near_plane=near_plane,
            _key=(azimuth, elevation, width, height, cam_x, cam_y, cam_z, fov, near_plane)
        )


def project_3d_to_2d_fast(pos: np.ndarray, cam: CachedCameraTransform) -> Tuple[float, float, float]:
    """Fast projection using pre-computed camera transform.
    
    Args:
        pos: 3D position [x, y, z]
        cam: Pre-computed camera transform
        
    Returns:
        Tuple of (screen_x, screen_y, depth)
    """
    # Translate to camera-relative
    dx = pos[0] - cam.cam_x
    dy = pos[1] - cam.cam_y
    dz = pos[2] - cam.cam_z
    
    # Rotate by azimuth (around Y)
    x1 = dx * cam.cos_az - dz * cam.sin_az
    z1 = dx * cam.sin_az + dz * cam.cos_az
    
    # Rotate by elevation (around X)
    y2 = dy * cam.cos_el + z1 * cam.sin_el
    z2 = -dy * cam.sin_el + z1 * cam.cos_el
    
    depth = -z2
    depth_clamped = depth if depth > cam.near_plane else cam.near_plane
    
    # Project
    screen_x = (x1 / depth_clamped) * cam.focal_length + cam.half_width
    screen_y = -(y2 / depth_clamped) * cam.focal_length + cam.half_height
    
    return (screen_x, screen_y, depth)


def quat_rotate_vector(quat: np.ndarray, vec: np.ndarray) -> np.ndarray:
    """Rotate a vector by a quaternion.
    
    Args:
        quat: Quaternion [x, y, z, w]
        vec: Vector [x, y, z]
        
    Returns:
        Rotated vector [x, y, z]
    """
    qx, qy, qz, qw = quat
    qxyz = np.array([qx, qy, qz])
    cross1 = np.cross(qxyz, vec) + qw * vec
    cross2 = np.cross(qxyz, cross1)
    return vec + 2.0 * cross2


def project_3d_to_2d(
    pos: np.ndarray,
    azimuth: float,
    elevation: float,
    width: float,
    height: float,
    cam_x: float = 0.0,
    cam_y: float = 0.5,
    cam_z: float = 3.0,
    fov: float = 60.0,
    near_plane: float = 0.1
) -> tuple:
    """Perspective projection with FPS-style camera.
    
    Uses standard graphics convention:
    - X points right
    - Y points up
    - Z points toward viewer (out of screen)
    - Forward is -Z (into screen)
    
    Camera position in world space:
    - cam_x: X position
    - cam_y: Y position (height)
    - cam_z: Z position (default +3.0, toward viewer)
    
    Azimuth: 0 = looking toward -Z, 90 = looking toward -X
    Elevation: negative = looking down, positive = looking up
    
    Args:
        pos: 3D position [x, y, z]
        azimuth: Horizontal rotation in degrees
        elevation: Vertical rotation in degrees
        width: Viewport width in pixels
        height: Viewport height in pixels
        cam_x: Camera X position
        cam_y: Camera Y position (height)
        cam_z: Camera Z position
        fov: Field of view in degrees
        near_plane: Near clipping plane distance
        
    Returns:
        Tuple of (screen_x, screen_y, depth)
    """
    # Step 1: Translate point to camera-relative coordinates
    dx = pos[0] - cam_x
    dy = pos[1] - cam_y
    dz = pos[2] - cam_z
    
    # Step 2: Apply camera rotation (view matrix)
    # We rotate the world by the INVERSE of the camera rotation
    # Azimuth rotates around world Y axis
    # Elevation rotates around camera's local X axis
    
    azimuth_rad = np.radians(azimuth)
    elevation_rad = np.radians(elevation)
    
    cos_az = np.cos(azimuth_rad)
    sin_az = np.sin(azimuth_rad)
    cos_el = np.cos(elevation_rad)
    sin_el = np.sin(elevation_rad)
    
    # First rotate by azimuth around Y axis (yaw)
    # Camera looks toward -Z at azimuth=0, so we transform world to align with that
    x1 = dx * cos_az - dz * sin_az
    z1 = dx * sin_az + dz * cos_az
    y1 = dy
    
    # Then rotate by elevation around X axis (pitch)
    # Rotation matrix for pitch (inverse of camera rotation):
    # For positive elevation (looking up), rotate world down
    x2 = x1
    y2 = y1 * cos_el + z1 * sin_el
    z2 = -y1 * sin_el + z1 * cos_el
    
    # Now in camera space: X right, Y up, Z toward camera (out of screen)
    # Camera looks toward -Z (into screen), so depth is -z2
    # Points with negative z2 are in front of camera (along -Z direction)
    depth = -z2
    
    # Clip near plane to prevent division by zero or negative depth
    # Use clamped depth for projection only
    depth_for_projection = max(depth, near_plane)
    
    # Step 3: Perspective projection
    # Using standard perspective projection formula
    # For a given vertical FOV: tan(vfov/2) = (viewport_height/2) / focal_length
    # Therefore: focal_length = (viewport_height/2) / tan(vfov/2)
    # 
    # Projection: screen_x = (camera_x / camera_z) * focal_length + viewport_center_x
    #             screen_y = (camera_y / camera_z) * focal_length + viewport_center_y
    #
    # For square pixels, use the same focal length for both X and Y
    fov_rad = np.radians(fov)
    tan_half_fov = np.tan(fov_rad / 2.0)
    
    # Calculate focal length in pixels based on vertical FOV
    focal_length = (height / 2.0) / tan_half_fov if tan_half_fov > 0 else height
    
    # Project to screen coordinates centered at (width/2, height/2)
    # In camera space: X is right, Y is up, Z is toward camera (positive depth means in front)
    # We project using: screen = (camera_xy / depth) * focal_length + center
    screen_x = (x2 / depth_for_projection) * focal_length + (width / 2.0)
    screen_y = -(y2 / depth_for_projection) * focal_length + (height / 2.0)  # Negate y2 because screen Y is down
    
    return (screen_x, screen_y, depth)  # Return UNCLAMPED depth for culling checks

