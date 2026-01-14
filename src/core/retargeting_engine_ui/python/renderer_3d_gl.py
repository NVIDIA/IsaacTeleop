# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
OpenGL-based 3D renderer with instanced rendering and FBO support.

Uses GPU-accelerated transforms and instancing for efficient rendering
of large numbers of primitives (spheres, markers, lines, text).

Renders to a framebuffer object (FBO) that can be displayed in ImGui windows.
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import math
import ctypes
import time

from OpenGL.GL import *
from OpenGL.GL import shaders

from .camera import CameraState


# =============================================================================
# Embedded Shaders
# =============================================================================

SPHERE_VERTEX_SHADER = """
#version 330 core

// Per-vertex attributes (sphere geometry)
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;

// Per-instance attributes
layout(location = 2) in vec3 iPosition;      // World position
layout(location = 3) in float iSize;         // World-space radius
layout(location = 4) in vec3 iColor;         // RGB color
layout(location = 5) in vec4 iOrientation;   // Quaternion (x,y,z,w) - for batch transform

// Uniforms
uniform mat4 uView;
uniform mat4 uProjection;
uniform vec3 uBatchPosition;      // Batch origin position
uniform vec4 uBatchOrientation;   // Batch origin quaternion (x,y,z,w)
uniform int uUseBatchTransform;   // Whether to apply batch transform

out vec3 vNormal;
out vec3 vColor;
out vec3 vFragPos;

// Quaternion rotation
vec3 quat_rotate(vec4 q, vec3 v) {
    vec3 qvec = q.xyz;
    float qw = q.w;
    return v + 2.0 * cross(qvec, cross(qvec, v) + qw * v);
}

void main() {
    // Scale vertex by instance size
    vec3 scaledPos = aPos * iSize;
    
    // Apply instance orientation (for per-item rotation if needed)
    vec3 rotatedPos = quat_rotate(iOrientation, scaledPos);
    
    // Compute world position
    vec3 worldPos;
    if (uUseBatchTransform == 1) {
        // Apply batch transform: rotate item position, then add batch position
        vec3 batchRotatedItemPos = quat_rotate(uBatchOrientation, iPosition);
        worldPos = uBatchPosition + batchRotatedItemPos + rotatedPos;
    } else {
        worldPos = iPosition + rotatedPos;
    }
    
    // Transform normal (only rotation matters for normal)
    vec3 worldNormal = quat_rotate(iOrientation, aNormal);
    if (uUseBatchTransform == 1) {
        worldNormal = quat_rotate(uBatchOrientation, worldNormal);
    }
    
    vNormal = worldNormal;
    vColor = iColor;
    vFragPos = worldPos;
    
    gl_Position = uProjection * uView * vec4(worldPos, 1.0);
}
"""

SPHERE_FRAGMENT_SHADER = """
#version 330 core

in vec3 vNormal;
in vec3 vColor;
in vec3 vFragPos;

out vec4 FragColor;

uniform vec3 uLightDir;    // Unused, kept for compatibility
uniform vec3 uCameraPos;   // Unused, kept for compatibility

void main() {
    // Simple flat color - no lighting
    FragColor = vec4(vColor, 1.0);
}
"""

# Simple line shader (no lighting)
LINE_VERTEX_SHADER = """
#version 330 core

layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aColor;

uniform mat4 uView;
uniform mat4 uProjection;

out vec3 vColor;

void main() {
    vColor = aColor;
    gl_Position = uProjection * uView * vec4(aPos, 1.0);
}
"""

LINE_FRAGMENT_SHADER = """
#version 330 core

in vec3 vColor;
out vec4 FragColor;

void main() {
    FragColor = vec4(vColor, 1.0);
}
"""


# =============================================================================
# Geometry Generation
# =============================================================================

def generate_icosphere(subdivisions: int = 2) -> Tuple[np.ndarray, np.ndarray]:
    """
    Generate an icosphere with the given number of subdivisions.
    
    Returns:
        vertices: (N, 3) array of vertex positions
        normals: (N, 3) array of vertex normals (same as positions for unit sphere)
    """
    # Golden ratio
    phi = (1.0 + math.sqrt(5.0)) / 2.0
    
    # Initial icosahedron vertices
    verts = [
        (-1, phi, 0), (1, phi, 0), (-1, -phi, 0), (1, -phi, 0),
        (0, -1, phi), (0, 1, phi), (0, -1, -phi), (0, 1, -phi),
        (phi, 0, -1), (phi, 0, 1), (-phi, 0, -1), (-phi, 0, 1),
    ]
    
    # Normalize to unit sphere
    verts = [np.array(v) / np.linalg.norm(v) for v in verts]
    
    # Initial icosahedron faces (triangles)
    faces = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]
    
    # Subdivision
    def midpoint(v1, v2):
        mid = (np.array(v1) + np.array(v2)) / 2.0
        return tuple(mid / np.linalg.norm(mid))
    
    for _ in range(subdivisions):
        new_faces = []
        midpoint_cache = {}
        
        def get_midpoint(i1, i2):
            key = (min(i1, i2), max(i1, i2))
            if key in midpoint_cache:
                return midpoint_cache[key]
            v1, v2 = verts[i1], verts[i2]
            mid = midpoint(v1, v2)
            idx = len(verts)
            verts.append(mid)
            midpoint_cache[key] = idx
            return idx
        
        for f in faces:
            v1, v2, v3 = f
            a = get_midpoint(v1, v2)
            b = get_midpoint(v2, v3)
            c = get_midpoint(v3, v1)
            new_faces.extend([
                (v1, a, c),
                (v2, b, a),
                (v3, c, b),
                (a, b, c),
            ])
        faces = new_faces
    
    # Convert to triangle list
    triangle_verts = []
    for f in faces:
        for idx in f:
            triangle_verts.append(verts[idx])
    
    vertices = np.array(triangle_verts, dtype=np.float32)
    normals = vertices.copy()  # For unit sphere, normals = positions
    
    return vertices, normals


# =============================================================================
# OpenGL Renderer with FBO Support
# =============================================================================

class Renderer3DGL:
    """
    OpenGL-based 3D renderer with instanced rendering and FBO support.
    
    Features:
    - GPU-accelerated transforms via shaders
    - Instanced rendering for batches of primitives
    - Proper depth testing
    - Flat color shading (no lighting)
    - FBO rendering for ImGui integration
    """
    
    def __init__(self):
        """Initialize the OpenGL renderer."""
        self._initialized = False
        
        # Shader programs
        self._sphere_program = None
        self._line_program = None
        
        # Sphere geometry
        self._sphere_vao = None
        self._sphere_vbo = None
        self._sphere_vertex_count = 0
        
        # Instance buffer (dynamic, resized as needed)
        self._instance_vbo = None
        self._instance_capacity = 0
        
        # Line buffers (dynamic)
        self._line_vao = None
        self._line_vbo = None
        self._line_capacity = 0
        
        # Grid geometry (static)
        self._grid_vao = None
        self._grid_vbo = None
        self._grid_vertex_count = 0
        
        # Axis markers (separate for bold rendering)
        self._axis_vao = None
        self._axis_vbo = None
        self._axis_vertex_count = 0
        
        # FBO for rendering to texture
        self._fbo = None
        self._fbo_texture = None
        self._fbo_depth = None
        self._fbo_width = 0
        self._fbo_height = 0
    
    def initialize(self) -> None:
        """Initialize OpenGL resources. Must be called with valid GL context."""
        if self._initialized:
            return
        
        # Compile shaders
        self._sphere_program = self._compile_program(
            SPHERE_VERTEX_SHADER, SPHERE_FRAGMENT_SHADER
        )
        self._line_program = self._compile_program(
            LINE_VERTEX_SHADER, LINE_FRAGMENT_SHADER
        )
        
        # Generate sphere geometry
        vertices, normals = generate_icosphere(subdivisions=2)
        self._sphere_vertex_count = len(vertices)
        
        # Create sphere VAO/VBO
        self._sphere_vao = glGenVertexArrays(1)
        self._sphere_vbo = glGenBuffers(1)
        
        glBindVertexArray(self._sphere_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._sphere_vbo)
        
        # Interleave position and normal
        interleaved = np.zeros((len(vertices), 6), dtype=np.float32)
        interleaved[:, 0:3] = vertices
        interleaved[:, 3:6] = normals
        glBufferData(GL_ARRAY_BUFFER, interleaved.nbytes, interleaved, GL_STATIC_DRAW)
        
        # Position attribute (location 0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        
        # Normal attribute (location 1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(12))
        glEnableVertexAttribArray(1)
        
        # Create instance VBO (will be resized as needed)
        self._instance_vbo = glGenBuffers(1)
        self._setup_instance_attributes()
        
        glBindVertexArray(0)
        
        # Create grid geometry
        self._create_grid()
        
        # Create line VAO
        self._line_vao = glGenVertexArrays(1)
        self._line_vbo = glGenBuffers(1)
        
        self._initialized = True
    
    def _compile_program(self, vertex_src: str, fragment_src: str) -> int:
        """Compile and link a shader program."""
        try:
            vertex_shader = shaders.compileShader(vertex_src, GL_VERTEX_SHADER)
            fragment_shader = shaders.compileShader(fragment_src, GL_FRAGMENT_SHADER)
            program = shaders.compileProgram(vertex_shader, fragment_shader)
            return program
        except Exception as e:
            print(f"[Renderer3DGL] Shader compilation error: {e}")
            raise
    
    def _setup_instance_attributes(self) -> None:
        """Set up instance attribute pointers for the sphere VAO."""
        glBindBuffer(GL_ARRAY_BUFFER, self._instance_vbo)
        
        # Instance data layout: position(3) + size(1) + color(3) + orientation(4) = 11 floats
        stride = 11 * 4  # 44 bytes
        
        # iPosition (location 2)
        glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(2)
        glVertexAttribDivisor(2, 1)
        
        # iSize (location 3)
        glVertexAttribPointer(3, 1, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
        glEnableVertexAttribArray(3)
        glVertexAttribDivisor(3, 1)
        
        # iColor (location 4)
        glVertexAttribPointer(4, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(16))
        glEnableVertexAttribArray(4)
        glVertexAttribDivisor(4, 1)
        
        # iOrientation (location 5)
        glVertexAttribPointer(5, 4, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(28))
        glEnableVertexAttribArray(5)
        glVertexAttribDivisor(5, 1)
    
    def _create_grid(self) -> None:
        """Create grid geometry for the ground plane and axis markers."""
        # Grid lines (gray)
        grid_lines = []
        grid_size = 10
        grid_step = 0.5
        color = (0.3, 0.3, 0.3)
        
        for i in range(-grid_size, grid_size + 1):
            x = i * grid_step
            # Line along Z
            grid_lines.extend([x, 0, -grid_size * grid_step, *color])
            grid_lines.extend([x, 0, grid_size * grid_step, *color])
            # Line along X
            z = i * grid_step
            grid_lines.extend([-grid_size * grid_step, 0, z, *color])
            grid_lines.extend([grid_size * grid_step, 0, z, *color])
        
        grid_data = np.array(grid_lines, dtype=np.float32)
        self._grid_vertex_count = len(grid_data) // 6
        
        self._grid_vao = glGenVertexArrays(1)
        self._grid_vbo = glGenBuffers(1)
        
        glBindVertexArray(self._grid_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._grid_vbo)
        glBufferData(GL_ARRAY_BUFFER, grid_data.nbytes, grid_data, GL_STATIC_DRAW)
        
        # Position (location 0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        
        # Color (location 1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(12))
        glEnableVertexAttribArray(1)
        glBindVertexArray(0)
        
        # Create separate axis markers (bold, rendered on top)
        axis_lines = []
        axis_length = 1.0  # Longer axis markers
        # X axis - red (bright)
        axis_lines.extend([0, 0.001, 0, 1.0, 0.3, 0.3])
        axis_lines.extend([axis_length, 0.001, 0, 1.0, 0.3, 0.3])
        # Y axis - green (bright)
        axis_lines.extend([0, 0.001, 0, 0.3, 1.0, 0.3])
        axis_lines.extend([0, axis_length, 0, 0.3, 1.0, 0.3])
        # Z axis - blue (bright)
        axis_lines.extend([0, 0.001, 0, 0.3, 0.3, 1.0])
        axis_lines.extend([0, 0.001, axis_length, 0.3, 0.3, 1.0])
        
        axis_data = np.array(axis_lines, dtype=np.float32)
        self._axis_vertex_count = len(axis_data) // 6
        
        self._axis_vao = glGenVertexArrays(1)
        self._axis_vbo = glGenBuffers(1)
        
        glBindVertexArray(self._axis_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._axis_vbo)
        glBufferData(GL_ARRAY_BUFFER, axis_data.nbytes, axis_data, GL_STATIC_DRAW)
        
        # Position (location 0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        
        # Color (location 1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(12))
        glEnableVertexAttribArray(1)
        
        glBindVertexArray(0)
    
    # =========================================================================
    # FBO Management
    # =========================================================================
    
    def _ensure_fbo(self, width: int, height: int) -> None:
        """Ensure FBO exists and is the correct size."""
        if width <= 0 or height <= 0:
            return
        
        # Check if we need to resize
        if self._fbo is not None and self._fbo_width == width and self._fbo_height == height:
            return
        
        # Delete old FBO if exists
        if self._fbo is not None:
            glDeleteFramebuffers(1, [self._fbo])
            glDeleteTextures(1, [self._fbo_texture])
            glDeleteRenderbuffers(1, [self._fbo_depth])
        
        # Create FBO
        self._fbo = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self._fbo)
        
        # Create color texture
        self._fbo_texture = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self._fbo_texture)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, self._fbo_texture, 0)
        
        # Create depth renderbuffer
        self._fbo_depth = glGenRenderbuffers(1)
        glBindRenderbuffer(GL_RENDERBUFFER, self._fbo_depth)
        glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, width, height)
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, self._fbo_depth)
        
        # Check completeness
        status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
        if status != GL_FRAMEBUFFER_COMPLETE:
            print(f"[Renderer3DGL] FBO incomplete: {status}")
            self._fbo = None
            return
        else:
            print(f"[Renderer3DGL] FBO created: {width}x{height}, texture={self._fbo_texture}")
        
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        
        self._fbo_width = width
        self._fbo_height = height
    
    def get_texture_id(self) -> Optional[int]:
        """Get the FBO texture ID for ImGui rendering."""
        return self._fbo_texture
    
    def get_projected_text(self) -> List[Dict[str, Any]]:
        """Get text items projected to screen coordinates after rendering.
        
        Returns:
            List of dicts with keys: 'x', 'y', 'text', 'color'
            x, y are screen coordinates relative to the rendered viewport.
        """
        return getattr(self, '_projected_text', [])
    
    def _project_text(
        self,
        node: Dict[str, Any],
        view: np.ndarray,
        proj: np.ndarray,
        width: int,
        height: int
    ) -> Optional[Dict[str, Any]]:
        """Project a text node to screen coordinates.
        
        Returns:
            Dict with 'x', 'y', 'text', 'color' or None if behind camera.
        """
        pos = np.asarray(node.get('position', [0., 0., 0.]), dtype=np.float32)
        text = node.get('text', '')
        color = node.get('color', (1.0, 1.0, 1.0))
        
        if not text:
            return None
        
        # Transform to clip space
        pos_h = np.array([pos[0], pos[1], pos[2], 1.0], dtype=np.float32)
        view_pos = view @ pos_h
        clip_pos = proj @ view_pos
        
        # Check if behind camera
        if clip_pos[3] <= 0:
            return None
        
        # Perspective divide to NDC
        ndc = clip_pos[:3] / clip_pos[3]
        
        # Check if outside view frustum
        if abs(ndc[0]) > 1.0 or abs(ndc[1]) > 1.0 or ndc[2] < 0 or ndc[2] > 1:
            return None
        
        # Convert to screen coordinates (origin at top-left)
        screen_x = (ndc[0] + 1.0) * 0.5 * width
        screen_y = (1.0 - ndc[1]) * 0.5 * height  # Flip Y for screen coords
        
        return {
            'x': screen_x,
            'y': screen_y,
            'text': text,
            'color': color
        }
    
    # =========================================================================
    # Matrix Computation
    # =========================================================================
    
    def _compute_view_matrix(self, camera: CameraState) -> np.ndarray:
        """Compute view matrix from camera state (FPS-style).
        
        Uses camera position (x, y, z) and orientation (azimuth, elevation)
        to create a proper FPS camera that moves through the scene.
        """
        # Camera position from camera state
        eye = np.array([camera.x, camera.y, camera.z], dtype=np.float32)
        
        # Compute forward direction from azimuth and elevation
        az_rad = math.radians(camera.azimuth)
        el_rad = math.radians(camera.elevation)
        
        # Forward vector (direction camera is looking)
        # At azimuth=0, elevation=0: looking toward -Z
        forward_x = -math.cos(el_rad) * math.sin(az_rad)
        forward_y = math.sin(el_rad)
        forward_z = -math.cos(el_rad) * math.cos(az_rad)
        forward = np.array([forward_x, forward_y, forward_z], dtype=np.float32)
        
        up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        
        # Look-at matrix
        f = forward
        f_len = np.linalg.norm(f)
        if f_len > 0.0001:
            f = f / f_len
        
        r = np.cross(f, up)
        r_len = np.linalg.norm(r)
        if r_len > 0.0001:
            r = r / r_len
        else:
            # Handle edge case: looking straight up/down
            r = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        
        u = np.cross(r, f)
        
        view = np.eye(4, dtype=np.float32)
        view[0, 0:3] = r
        view[1, 0:3] = u
        view[2, 0:3] = -f
        view[0, 3] = -np.dot(r, eye)
        view[1, 3] = -np.dot(u, eye)
        view[2, 3] = np.dot(f, eye)
        
        return view
    
    def _compute_projection_matrix(self, width: float, height: float, fov: float = 60.0) -> np.ndarray:
        """Compute perspective projection matrix."""
        aspect = width / height if height > 0 else 1.0
        near = 0.01
        far = 100.0
        
        fov_rad = math.radians(fov)
        f = 1.0 / math.tan(fov_rad / 2.0)
        
        proj = np.zeros((4, 4), dtype=np.float32)
        proj[0, 0] = f / aspect
        proj[1, 1] = f
        proj[2, 2] = (far + near) / (near - far)
        proj[2, 3] = (2 * far * near) / (near - far)
        proj[3, 2] = -1.0
        
        return proj
    
    def _compute_model_matrix(
        self,
        node_name: str,
        nodes: Dict[str, Any],
        model_cache: Dict[str, np.ndarray]
    ) -> np.ndarray:
        """Compute model matrix for a node by walking up its parent chain (with caching).
        
        This avoids pre-computing world transforms in Python by computing them
        lazily with caching during rendering.
        """
        # Check cache first
        if node_name in model_cache:
            return model_cache[node_name]
        
        node = nodes.get(node_name)
        if node is None:
            model_cache[node_name] = np.eye(4, dtype=np.float32)
            return model_cache[node_name]
        
        # Get local transform
        pos = np.asarray(node.get('position', [0., 0., 0.]), dtype=np.float32)
        orient = np.asarray(node.get('orientation', [0., 0., 0., 1.]), dtype=np.float32)
        
        # Build local model matrix from position and orientation
        local_model = self._build_model_matrix(pos, orient)
        
        # If no parent, local = world
        parent_name = node.get('parent')
        if parent_name is None:
            model_cache[node_name] = local_model
            return local_model
        
        # Get parent's world matrix (recursive with caching)
        parent_model = self._compute_model_matrix(parent_name, nodes, model_cache)
        
        # World = parent_world * local
        world_model = parent_model @ local_model
        model_cache[node_name] = world_model
        return world_model
    
    def _build_model_matrix(self, pos: np.ndarray, orient: np.ndarray) -> np.ndarray:
        """Build a 4x4 model matrix from position and quaternion orientation."""
        # Quaternion to rotation matrix
        x, y, z, w = orient
        
        # Rotation matrix from quaternion
        rot = np.eye(4, dtype=np.float32)
        rot[0, 0] = 1 - 2*(y*y + z*z)
        rot[0, 1] = 2*(x*y - z*w)
        rot[0, 2] = 2*(x*z + y*w)
        rot[1, 0] = 2*(x*y + z*w)
        rot[1, 1] = 1 - 2*(x*x + z*z)
        rot[1, 2] = 2*(y*z - x*w)
        rot[2, 0] = 2*(x*z - y*w)
        rot[2, 1] = 2*(y*z + x*w)
        rot[2, 2] = 1 - 2*(x*x + y*y)
        
        # Translation
        rot[0, 3] = pos[0]
        rot[1, 3] = pos[1]
        rot[2, 3] = pos[2]
        
        return rot
    
    # =========================================================================
    # Main Render Method
    # =========================================================================
    
    def render_to_texture(
        self,
        width: int,
        height: int,
        camera: CameraState,
        nodes: Dict[str, Any]
    ) -> Optional[int]:
        """
        Render the 3D scene to an FBO texture.
        
        Args:
            width: Viewport width in pixels
            height: Viewport height in pixels
            camera: Camera state
            nodes: Dictionary of node data to render
            
        Returns:
            OpenGL texture ID that can be used with ImGui.Image()
        """
        if width <= 0 or height <= 0:
            return None
        
        if not self._initialized:
            self.initialize()
        
        # Ensure FBO is correct size
        self._ensure_fbo(width, height)
        
        if self._fbo is None:
            return None
        
        # Bind FBO and set viewport
        glBindFramebuffer(GL_FRAMEBUFFER, self._fbo)
        glViewport(0, 0, width, height)
        
        # Clear
        glClearColor(0.1, 0.1, 0.12, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        
        # Enable depth testing
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)
        
        # Compute matrices
        view = self._compute_view_matrix(camera)
        proj = self._compute_projection_matrix(width, height)
        
        # Camera position for lighting
        cam_pos = np.array([camera.x, camera.y, camera.z], dtype=np.float32)
        
        # Light direction (from top-right-front)
        light_dir = np.array([0.3, -0.8, 0.5], dtype=np.float32)
        light_dir = light_dir / np.linalg.norm(light_dir)
        
        # Render grid
        self._render_grid(view, proj)
        
        # Debug: count nodes by type
        _DEBUG_RENDER = True
        if _DEBUG_RENDER and not hasattr(self, '_debug_nodes_printed'):
            type_counts = {}
            for name, node in nodes.items():
                if isinstance(node, dict):
                    t = node.get('type', 'unknown')
                    type_counts[t] = type_counts.get(t, 0) + 1
            print(f"[Renderer3DGL] Rendering {len(nodes)} nodes: {type_counts}")
            print(f"[Renderer3DGL] Camera: pos=({camera.x:.2f},{camera.y:.2f},{camera.z:.2f}) az={camera.azimuth:.0f} el={camera.elevation:.0f}")
            self._debug_nodes_printed = True
        
        # Collect text items for ImGui overlay
        text_items = []
        
        # Model matrix cache for hierarchical rendering (avoids recomputing parent chains)
        model_cache: Dict[str, np.ndarray] = {}
        
        # Render nodes by type
        for name, node in nodes.items():
            if not isinstance(node, dict):
                continue
            
            node_type = node.get('type', '')
            if not node.get('visible', True):
                continue
            
            # Skip transform-only nodes (they don't render, just provide transforms)
            if node_type == 'transform':
                continue
            
            # Compute world transform via model matrix (with caching)
            model = self._compute_model_matrix(name, nodes, model_cache)
            world_pos = model[0:3, 3].copy()  # Extract translation from model matrix
            
            # Create a node dict with world position for rendering
            render_node = dict(node)
            render_node['position'] = world_pos
            # Note: orientation from model matrix is more complex, but for spheres we don't need it
            
            if node_type == 'sphere_list':
                self._render_sphere_list(render_node, view, proj, cam_pos, light_dir)
            elif node_type == 'marker':
                self._render_marker(render_node, view, proj, cam_pos, light_dir)
            elif node_type == 'marker_list':
                self._render_marker_list(render_node, view, proj, cam_pos, light_dir)
            elif node_type == 'line':
                self._render_line(render_node, view, proj)
            elif node_type == 'line_list':
                self._render_line_list(render_node, view, proj)
            elif node_type == 'arrow':
                self._render_arrow(render_node, view, proj, cam_pos)
            elif node_type == 'text':
                # Collect text for ImGui overlay (rendered after FBO)
                text_items.append(self._project_text(render_node, view, proj, width, height))
        
        # Store projected text for later retrieval
        self._projected_text = [t for t in text_items if t is not None]
        
        # Disable depth testing
        glDisable(GL_DEPTH_TEST)
        
        # Check for GL errors
        err = glGetError()
        if err != GL_NO_ERROR:
            print(f"[Renderer3DGL] OpenGL error after render: {err}")
        
        # Unbind FBO
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        
        return self._fbo_texture
    
    # =========================================================================
    # Node Type Renderers
    # =========================================================================
    
    def _render_sphere_list(
        self,
        node: Dict[str, Any],
        view: np.ndarray,
        proj: np.ndarray,
        cam_pos: np.ndarray,
        light_dir: np.ndarray
    ) -> None:
        """Render a sphere_list node."""
        count = node.get('count', 0)
        item_positions = node.get('item_positions')
        sizes = node.get('sizes')
        colors = node.get('colors')
        batch_pos = np.asarray(node.get('position', np.zeros(3)), dtype=np.float32)
        batch_orient = np.asarray(node.get('orientation', [0., 0., 0., 1.]), dtype=np.float32)
        
        if item_positions is None or count == 0:
            if not hasattr(self, '_debug_sphere_warned'):
                print(f"[Renderer3DGL] sphere_list: count={count}, item_positions={item_positions is not None}")
                self._debug_sphere_warned = True
            return
        
        n = min(count, len(item_positions))
        if n == 0:
            return
        
        # Debug: print size info once
        if not hasattr(self, '_debug_size_printed'):
            if sizes is not None and len(sizes) > 0:
                print(f"[Renderer3DGL] sphere_list sizes: min={np.min(sizes[:n]):.4f}, max={np.max(sizes[:n]):.4f}, n={n}")
            else:
                print(f"[Renderer3DGL] sphere_list sizes: None or empty, using default 0.02")
            self._debug_size_printed = True
        
        # Build instance data
        instance_data = np.zeros((n, 11), dtype=np.float32)
        instance_data[:, 0:3] = item_positions[:n]
        
        if sizes is not None and len(sizes) >= n:
            instance_data[:, 3] = sizes[:n]
        else:
            instance_data[:, 3] = 0.02
        
        if colors is not None and len(colors) >= n:
            instance_data[:, 4:7] = colors[:n]
        else:
            instance_data[:, 4:7] = 1.0
        
        instance_data[:, 7:10] = 0.0
        instance_data[:, 10] = 1.0
        
        self._draw_instanced_spheres(instance_data, batch_pos, batch_orient, True, view, proj, cam_pos, light_dir)
    
    def _pixel_to_world_size(self, pixel_size: float, distance: float) -> float:
        """Convert pixel size to world-space size based on camera distance.
        
        This ensures markers appear the same screen-space size regardless of distance.
        Uses a scale factor calibrated for typical FOV (~60°) and screen dimensions.
        
        Args:
            pixel_size: Size in screen-space pixels
            distance: Distance from camera to object
            
        Returns:
            World-space size (radius in meters)
        """
        # Scale factor: at 1 meter distance, 1 pixel ≈ 0.001 meters
        # This is calibrated for ~60° FOV on typical screen sizes
        PIXEL_SCALE = 0.001
        MIN_DISTANCE = 0.1  # Prevent division issues at very close range
        
        effective_distance = max(distance, MIN_DISTANCE)
        return pixel_size * PIXEL_SCALE * effective_distance
    
    def _render_marker(
        self,
        node: Dict[str, Any],
        view: np.ndarray,
        proj: np.ndarray,
        cam_pos: np.ndarray,
        light_dir: np.ndarray
    ) -> None:
        """Render a single marker as a sphere with screen-space sizing.
        
        Marker sizes are in screen-space pixels. The world-space size is
        computed based on distance from camera to maintain consistent
        apparent size on screen.
        """
        pos = np.asarray(node.get('position', [0., 0., 0.]), dtype=np.float32)
        pixel_size = float(node.get('size', 10.0))
        color = np.asarray(node.get('color', [1., 1., 1.]), dtype=np.float32)
        
        # Compute distance from camera to marker for screen-space sizing
        distance = np.linalg.norm(pos - cam_pos)
        size = self._pixel_to_world_size(pixel_size, distance)
        
        instance_data = np.zeros((1, 11), dtype=np.float32)
        instance_data[0, 0:3] = pos
        instance_data[0, 3] = size
        instance_data[0, 4:7] = color[:3] if len(color) >= 3 else 1.0
        instance_data[0, 7:10] = 0.0
        instance_data[0, 10] = 1.0
        
        self._draw_instanced_spheres(
            instance_data,
            np.zeros(3, dtype=np.float32),
            np.array([0., 0., 0., 1.], dtype=np.float32),
            False, view, proj, cam_pos, light_dir
        )
    
    def _render_marker_list(
        self,
        node: Dict[str, Any],
        view: np.ndarray,
        proj: np.ndarray,
        cam_pos: np.ndarray,
        light_dir: np.ndarray
    ) -> None:
        """Render a marker_list node as spheres with screen-space sizing.
        
        Marker sizes are in screen-space pixels. World-space size is computed
        per-marker based on distance from camera.
        """
        count = node.get('count', 0)
        item_positions = node.get('item_positions')
        sizes = node.get('sizes')
        colors = node.get('colors')
        batch_pos = np.asarray(node.get('position', np.zeros(3)), dtype=np.float32)
        batch_orient = np.asarray(node.get('orientation', [0., 0., 0., 1.]), dtype=np.float32)
        
        if item_positions is None or count == 0:
            return
        
        n = min(count, len(item_positions))
        if n == 0:
            return
        
        instance_data = np.zeros((n, 11), dtype=np.float32)
        instance_data[:, 0:3] = item_positions[:n]
        
        # Convert pixel sizes to world-space with distance-based scaling
        # Compute world positions for distance calculation
        world_positions = item_positions[:n] + batch_pos  # Approximate (ignores batch rotation for perf)
        distances = np.linalg.norm(world_positions - cam_pos, axis=1)
        distances = np.maximum(distances, 0.1)  # Prevent issues at close range
        
        if sizes is not None and len(sizes) >= n:
            pixel_sizes = sizes[:n]
        else:
            pixel_sizes = np.full(n, 10.0)  # default 10 pixels
        
        # Screen-space sizing: world_size = pixel_size * distance * scale_factor
        instance_data[:, 3] = pixel_sizes * distances * 0.001
        
        if colors is not None and len(colors) >= n:
            instance_data[:, 4:7] = colors[:n]
        else:
            instance_data[:, 4:7] = 1.0
        
        instance_data[:, 7:10] = 0.0
        instance_data[:, 10] = 1.0
        
        self._draw_instanced_spheres(instance_data, batch_pos, batch_orient, True, view, proj, cam_pos, light_dir)
    
    def _render_line(
        self,
        node: Dict[str, Any],
        view: np.ndarray,
        proj: np.ndarray
    ) -> None:
        """Render a single line.
        
        Note: end_point is a relative offset from position, not an absolute position.
        """
        start = np.asarray(node.get('position', [0., 0., 0.]), dtype=np.float32)
        end_offset = np.asarray(node.get('end_point', [1., 0., 0.]), dtype=np.float32)
        end = start + end_offset  # end_point is relative to position
        color = np.asarray(node.get('color', [1., 1., 1.]), dtype=np.float32)
        
        line_data = np.zeros((2, 6), dtype=np.float32)
        line_data[0, 0:3] = start
        line_data[0, 3:6] = color[:3] if len(color) >= 3 else 1.0
        line_data[1, 0:3] = end
        line_data[1, 3:6] = color[:3] if len(color) >= 3 else 1.0
        
        self._draw_lines(line_data, view, proj)
    
    def _render_line_list(
        self,
        node: Dict[str, Any],
        view: np.ndarray,
        proj: np.ndarray
    ) -> None:
        """Render a line_list node."""
        count = node.get('count', 0)
        item_positions = node.get('item_positions')
        end_points = node.get('end_points')
        colors = node.get('colors')
        batch_pos = np.asarray(node.get('position', np.zeros(3)), dtype=np.float32)
        batch_orient = np.asarray(node.get('orientation', [0., 0., 0., 1.]), dtype=np.float32)
        
        if item_positions is None or end_points is None or count == 0:
            return
        
        n = min(count, len(item_positions), len(end_points))
        if n == 0:
            return
        
        # Build line data with batch transform applied
        # Note: end_points are relative offsets from item_positions (local end points)
        line_data = np.zeros((n * 2, 6), dtype=np.float32)
        
        for i in range(n):
            start = self._apply_batch_transform(item_positions[i], batch_pos, batch_orient)
            # end_point is relative to item_position
            end_local = item_positions[i] + end_points[i]
            end = self._apply_batch_transform(end_local, batch_pos, batch_orient)
            color = colors[i] if colors is not None and i < len(colors) else np.array([1., 1., 1.])
            
            line_data[i*2, 0:3] = start
            line_data[i*2, 3:6] = color[:3] if len(color) >= 3 else 1.0
            line_data[i*2+1, 0:3] = end
            line_data[i*2+1, 3:6] = color[:3] if len(color) >= 3 else 1.0
        
        self._draw_lines(line_data, view, proj)
    
    def _render_arrow(
        self,
        node: Dict[str, Any],
        view: np.ndarray,
        proj: np.ndarray,
        cam_pos: np.ndarray
    ) -> None:
        """Render an arrow as a line with arrowhead lines.
        
        Arrow direction is +Z in local space (orientation rotates +Z to arrow direction).
        Arrowhead size is in screen-space (constant apparent size regardless of distance).
        """
        pos = np.asarray(node.get('position', [0., 0., 0.]), dtype=np.float32)
        orient = np.asarray(node.get('orientation', [0., 0., 0., 1.]), dtype=np.float32)
        length = float(node.get('length', 0.1))
        color = np.asarray(node.get('color', [1., 1., 1.]), dtype=np.float32)
        
        # Arrow direction from orientation (forward is +Z in local space)
        direction = self._quat_rotate(orient, np.array([0., 0., 1.], dtype=np.float32))
        end = pos + direction * length
        
        # Arrowhead with screen-space sizing (constant apparent size)
        # Use distance from camera to arrowhead tip for sizing
        distance = max(np.linalg.norm(end - cam_pos), 0.1)
        # 50 pixels arrowhead at any distance, but clamped to not exceed arrow length
        head_size = self._pixel_to_world_size(50.0, distance)
        head_size = min(head_size, length * 0.5)  # Don't let arrowhead exceed 50% of shaft
        
        perp1 = self._quat_rotate(orient, np.array([1., 0., 0.], dtype=np.float32))
        perp2 = self._quat_rotate(orient, np.array([0., 1., 0.], dtype=np.float32))
        
        head1 = end - direction * head_size + perp1 * head_size * 0.5
        head2 = end - direction * head_size - perp1 * head_size * 0.5
        head3 = end - direction * head_size + perp2 * head_size * 0.5
        head4 = end - direction * head_size - perp2 * head_size * 0.5
        
        # Build line data (shaft + 4 arrowhead lines)
        line_data = np.zeros((10, 6), dtype=np.float32)
        c = color[:3] if len(color) >= 3 else np.array([1., 1., 1.])
        
        # Shaft
        line_data[0, 0:3] = pos
        line_data[0, 3:6] = c
        line_data[1, 0:3] = end
        line_data[1, 3:6] = c
        
        # Arrowhead
        line_data[2, 0:3] = end; line_data[2, 3:6] = c
        line_data[3, 0:3] = head1; line_data[3, 3:6] = c
        line_data[4, 0:3] = end; line_data[4, 3:6] = c
        line_data[5, 0:3] = head2; line_data[5, 3:6] = c
        line_data[6, 0:3] = end; line_data[6, 3:6] = c
        line_data[7, 0:3] = head3; line_data[7, 3:6] = c
        line_data[8, 0:3] = end; line_data[8, 3:6] = c
        line_data[9, 0:3] = head4; line_data[9, 3:6] = c
        
        self._draw_lines(line_data, view, proj)
    
    # =========================================================================
    # Low-Level Draw Methods
    # =========================================================================
    
    def _draw_instanced_spheres(
        self,
        instance_data: np.ndarray,
        batch_pos: np.ndarray,
        batch_orient: np.ndarray,
        use_batch_transform: bool,
        view: np.ndarray,
        proj: np.ndarray,
        cam_pos: np.ndarray,
        light_dir: np.ndarray
    ) -> None:
        """Draw instanced spheres."""
        n = len(instance_data)
        if n == 0:
            return
        
        glBindVertexArray(self._sphere_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._instance_vbo)
        
        if n > self._instance_capacity:
            glBufferData(GL_ARRAY_BUFFER, instance_data.nbytes, instance_data, GL_DYNAMIC_DRAW)
            self._instance_capacity = n
            self._setup_instance_attributes()
        else:
            glBufferSubData(GL_ARRAY_BUFFER, 0, instance_data.nbytes, instance_data)
        
        glUseProgram(self._sphere_program)
        
        glUniformMatrix4fv(glGetUniformLocation(self._sphere_program, "uView"), 1, GL_TRUE, view)
        glUniformMatrix4fv(glGetUniformLocation(self._sphere_program, "uProjection"), 1, GL_TRUE, proj)
        glUniform3fv(glGetUniformLocation(self._sphere_program, "uCameraPos"), 1, cam_pos)
        glUniform3fv(glGetUniformLocation(self._sphere_program, "uLightDir"), 1, light_dir)
        glUniform1i(glGetUniformLocation(self._sphere_program, "uUseBatchTransform"), 1 if use_batch_transform else 0)
        glUniform3fv(glGetUniformLocation(self._sphere_program, "uBatchPosition"), 1, batch_pos)
        glUniform4fv(glGetUniformLocation(self._sphere_program, "uBatchOrientation"), 1, batch_orient)
        
        glDrawArraysInstanced(GL_TRIANGLES, 0, self._sphere_vertex_count, n)
        glBindVertexArray(0)
    
    def _draw_lines(
        self,
        line_data: np.ndarray,
        view: np.ndarray,
        proj: np.ndarray
    ) -> None:
        """Draw lines."""
        n = len(line_data)
        if n == 0:
            return
        
        glBindVertexArray(self._line_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._line_vbo)
        
        if n > self._line_capacity:
            glBufferData(GL_ARRAY_BUFFER, line_data.nbytes, line_data, GL_DYNAMIC_DRAW)
            self._line_capacity = n
        else:
            glBufferSubData(GL_ARRAY_BUFFER, 0, line_data.nbytes, line_data)
        
        # Set up attributes
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(12))
        glEnableVertexAttribArray(1)
        
        glUseProgram(self._line_program)
        glUniformMatrix4fv(glGetUniformLocation(self._line_program, "uView"), 1, GL_TRUE, view)
        glUniformMatrix4fv(glGetUniformLocation(self._line_program, "uProjection"), 1, GL_TRUE, proj)
        
        glDrawArrays(GL_LINES, 0, n)
        glBindVertexArray(0)
    
    def _render_grid(self, view: np.ndarray, proj: np.ndarray) -> None:
        """Render the ground grid and axis markers."""
        glUseProgram(self._line_program)
        glUniformMatrix4fv(glGetUniformLocation(self._line_program, "uView"), 1, GL_TRUE, view)
        glUniformMatrix4fv(glGetUniformLocation(self._line_program, "uProjection"), 1, GL_TRUE, proj)
        
        # Render grid
        glBindVertexArray(self._grid_vao)
        glDrawArrays(GL_LINES, 0, self._grid_vertex_count)
        glBindVertexArray(0)
        
        # Render axis markers on top (disable depth test to always be visible)
        glDisable(GL_DEPTH_TEST)
        glBindVertexArray(self._axis_vao)
        glDrawArrays(GL_LINES, 0, self._axis_vertex_count)
        glBindVertexArray(0)
        glEnable(GL_DEPTH_TEST)
    
    # =========================================================================
    # Utilities
    # =========================================================================
    
    def _apply_batch_transform(
        self,
        local_pos: np.ndarray,
        batch_pos: np.ndarray,
        batch_orient: np.ndarray
    ) -> np.ndarray:
        """Apply batch transform to a local position (CPU fallback for lines)."""
        if np.allclose(batch_pos, 0) and np.allclose(batch_orient, [0, 0, 0, 1]):
            return np.asarray(local_pos, dtype=np.float32)
        
        rotated = self._quat_rotate(batch_orient, np.asarray(local_pos, dtype=np.float32))
        return batch_pos + rotated
    
    def _quat_rotate(self, q: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Rotate vector by quaternion."""
        qvec = q[:3]
        qw = q[3]
        return v + 2.0 * np.cross(qvec, np.cross(qvec, v) + qw * v)
    
    # =========================================================================
    # Cleanup
    # =========================================================================
    
    def cleanup(self) -> None:
        """Clean up OpenGL resources."""
        if self._fbo:
            glDeleteFramebuffers(1, [self._fbo])
        if self._fbo_texture:
            glDeleteTextures(1, [self._fbo_texture])
        if self._fbo_depth:
            glDeleteRenderbuffers(1, [self._fbo_depth])
        if self._sphere_vao:
            glDeleteVertexArrays(1, [self._sphere_vao])
        if self._sphere_vbo:
            glDeleteBuffers(1, [self._sphere_vbo])
        if self._instance_vbo:
            glDeleteBuffers(1, [self._instance_vbo])
        if self._grid_vao:
            glDeleteVertexArrays(1, [self._grid_vao])
        if self._grid_vbo:
            glDeleteBuffers(1, [self._grid_vbo])
        if self._axis_vao:
            glDeleteVertexArrays(1, [self._axis_vao])
        if self._axis_vbo:
            glDeleteBuffers(1, [self._axis_vbo])
        if self._line_vao:
            glDeleteVertexArrays(1, [self._line_vao])
        if self._line_vbo:
            glDeleteBuffers(1, [self._line_vbo])
        if self._sphere_program:
            glDeleteProgram(self._sphere_program)
        if self._line_program:
            glDeleteProgram(self._line_program)
        
        self._initialized = False
