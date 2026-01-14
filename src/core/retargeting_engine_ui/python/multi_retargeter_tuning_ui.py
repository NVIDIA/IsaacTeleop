# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Unified ImGui UI for retargeting engine - combines parameter tuning and visualization.

Provides an async ImGui window that displays:
- Parameter tuning controls for multiple retargeters
- 3D visualization of retargeting state
- Real-time graphs and plots
- Configurable layouts (tabs, vertical, horizontal, floating)

This is the main UI class that orchestrates all rendering modules.
"""

import threading
import time
from typing import TYPE_CHECKING, Dict, List, Optional

import numpy as np
import glfw  # type: ignore[import-not-found]
import imgui  # type: ignore[import-not-found]
from imgui.integrations.glfw import GlfwRenderer  # type: ignore[import-not-found]

try:
    import OpenGL.GL as gl  # type: ignore[import-not-found]
    HAS_OPENGL = True
except ImportError:
    HAS_OPENGL = False

# Local module imports
from .camera import CameraController, CameraState
from .graph_renderer import GraphRenderer
from .layouts import LayoutMode, LayoutRenderer
from .parameter_ui import ParameterRenderer
from .perf_stats_ui import PerfStatsRenderer
from .renderer_3d_gl import Renderer3DGL

if TYPE_CHECKING:
    from teleopcore.retargeting_engine.interface import (
        BaseRetargeter,
        ParameterState,
        RetargeterStats,
        VisualizationState,
    )


# Re-export LayoutMode for backwards compatibility
LayoutModeImGui = LayoutMode


class MultiRetargeterTuningUIImGui:
    """
    Unified ImGui UI for retargeting engine - combines parameter tuning and visualization.
    
    Runs automatically in a background thread. Supports RAII via context managers.
    
    Features:
    - Parameter tuning controls for multiple retargeters
    - 3D visualization of retargeting state (if available)
    - Real-time graphs and plots (if available)
    - Multiple layout modes: tabs, vertical, horizontal, floating windows
    
    Example:
        retargeters = [processor_a, processor_b, processor_c]
        
        # RAII style (recommended):
        with MultiRetargeterTuningUIImGui(retargeters, layout_mode=LayoutModeImGui.TABS) as ui:
            while running:
                # Process data - UI updates automatically in background
                processor_a(inputs, outputs)
        
        # Manual style:
        ui = MultiRetargeterTuningUIImGui(retargeters)
        ui.start()
        # ... use retargeters ...
        ui.stop()
    """
    
    def __init__(
        self,
        retargeters: List['BaseRetargeter'],
        title: str = "Multi-Retargeter Tuning",
        layout_mode: LayoutMode = LayoutMode.TABS
    ):
        """
        Initialize and start multi-retargeter tuning UI (RAII).
        
        The UI starts automatically in a background thread and stops when
        the object is destroyed or when used as a context manager.
        
        Args:
            retargeters: List of retargeter instances to tune
            title: Window title
            layout_mode: How to organize retargeters in the window
            
        Raises:
            ImportError: If imgui/glfw is not installed
            ValueError: If no retargeters provided or none have parameters
            
        Example:
            # RAII with context manager (recommended):
            with MultiRetargeterTuningUIImGui([proc_a, proc_b]) as ui:
                while running:
                    # Process data
                    pass
            # UI automatically stops here
            
            # Or direct construction (stops in destructor):
            ui = MultiRetargeterTuningUIImGui([proc_a, proc_b])
            # ... use retargeters ...
            # UI stops when ui goes out of scope
        """
        
        if not retargeters:
            raise ValueError("At least one retargeter must be provided")
        
        # Extract and store ParameterState and VisualizationState objects (thread-safe)
        self._parameter_states: Dict[str, 'ParameterState'] = {}
        self._visualization_states: Dict[str, 'VisualizationState'] = {}
        self._stats: Dict[str, 'RetargeterStats'] = {}
        
        for ret in retargeters:
            name = ret._name if hasattr(ret, '_name') else str(ret)
            
            # Extract parameter state
            param_state = ret.get_parameter_state() if hasattr(ret, 'get_parameter_state') else None
            if param_state is not None and len(param_state.get_all_parameter_specs()) > 0:
                self._parameter_states[name] = param_state
            
            # Extract visualization state
            viz_state = ret.get_visualization_state() if hasattr(ret, 'get_visualization_state') else None
            if viz_state is not None:
                self._visualization_states[name] = viz_state
            
            # Extract stats (always available)
            stats = ret.get_stats() if hasattr(ret, 'get_stats') else None
            if stats is not None:
                self._stats[name] = stats
        
        if not self._parameter_states and not self._visualization_states:
            raise ValueError("No retargeters with tunable parameters or visualization found")
        
        self._title = title
        self._layout_mode = layout_mode
        self._window = None
        self._impl = None
        self._is_open = False
        
        # Thread management
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_event = threading.Event()
        
        # Status message
        self._status_message = ""
        self._status_success = True
        self._status_time = 0.0
        
        # Initialize renderers
        self._renderer_3d_gl = Renderer3DGL()  # OpenGL 3D renderer
        self._graph_renderer = GraphRenderer()
        self._perf_stats_renderer = PerfStatsRenderer()
        self._param_renderer = ParameterRenderer(status_callback=self._set_status)
        self._layout_renderer = LayoutRenderer(
            render_retargeter_callback=self._render_retargeter_content,
            render_viz_only_callback=self._render_viz_only_content
        )
        
        # Camera state per-render-space (key = "viz_name::render_space_name")
        self._cameras: Dict[str, CameraState] = {}
        self._camera_controller = CameraController()
        self._init_cameras_from_viz_states()
        
        # Start UI automatically (RAII)
        self._start()
    
    # ========================================================================
    # Status Management
    # ========================================================================
    
    def _set_status(self, message: str, success: bool = True) -> None:
        """Set status message."""
        self._status_message = message
        self._status_success = success
        self._status_time = time.time()
    
    # ========================================================================
    # Retargeter Content Rendering
    # ========================================================================
    
    def _render_retargeter_content(self, name: str, inline_viz: bool = True) -> None:
        """Render full content for a retargeter (params + stats + viz).
        
        Args:
            name: Name of the retargeter
            inline_viz: If True, render visualization inline
        """
        if name in self._parameter_states:
            self._param_renderer.render_parameters(name, self._parameter_states[name])
        
        # Render performance stats (collapsible)
        if name in self._stats:
            self._perf_stats_renderer.render_stats(self._stats[name], name=name)
        
        # Render inline visualization if requested and available (collapsible sections)
        if inline_viz and name in self._visualization_states:
            viz_state = self._visualization_states[name]
            snapshot = viz_state.get_snapshot()
            
            # Render each 3D render space with its own collapsible header
            for render_space in snapshot.get('render_spaces', []):
                rs_name = render_space['name']
                rs_title = render_space.get('title', rs_name)
                imgui.spacing()
                expanded_3d, _ = imgui.collapsing_header(
                    f"{rs_title}##{name}_{rs_name}",
                    flags=imgui.TREE_NODE_DEFAULT_OPEN
                )
                # Update enabled state for next sync (skips compute overhead when collapsed)
                viz_state.set_render_space_enabled(rs_name, expanded_3d)
                if expanded_3d:
                    imgui.indent()
                    if render_space['nodes']:
                        self._render_3d_scene_inline(name, render_space)
                    else:
                        imgui.text("No 3D nodes")
                    imgui.unindent()
            
            # Render each graph with its own collapsible header
            for graph_name, graph_data in snapshot.get('graphs', {}).items():
                graph_title = graph_data.get('title', graph_name)
                imgui.spacing()
                expanded_graph, _ = imgui.collapsing_header(
                    f"{graph_title}##{name}_{graph_name}",
                    flags=imgui.TREE_NODE_DEFAULT_OPEN
                )
                if expanded_graph:
                    imgui.indent()
                    self._graph_renderer.render_single_graph(graph_data, f"_{name}_{graph_name}")
                    imgui.unindent()
    
    def _render_viz_only_content(self, name: str) -> None:
        """Render visualization-only content (no parameters).
        
        Args:
            name: Name of the retargeter
        """
        imgui.text("Visualization Only (No Parameters)")
        imgui.separator()
        
        # Show performance stats even for viz-only retargeters (collapsible)
        if name in self._stats:
            self._perf_stats_renderer.render_stats(self._stats[name], name=name)
        
        if name in self._visualization_states:
            viz_state = self._visualization_states[name]
            snapshot = viz_state.get_snapshot()
            
            # Render each 3D render space with its own collapsible header
            for render_space in snapshot.get('render_spaces', []):
                rs_name = render_space['name']
                rs_title = render_space.get('title', rs_name)
                imgui.spacing()
                expanded_3d, _ = imgui.collapsing_header(
                    f"{rs_title}##{name}_{rs_name}",
                    flags=imgui.TREE_NODE_DEFAULT_OPEN
                )
                # Update enabled state for next sync (skips compute overhead when collapsed)
                viz_state.set_render_space_enabled(rs_name, expanded_3d)
                if expanded_3d:
                    imgui.indent()
                    if render_space['nodes']:
                        self._render_3d_scene_inline(name, render_space)
                    else:
                        imgui.text("No 3D nodes")
                    imgui.unindent()
            
            # Render each graph with its own collapsible header
            for graph_name, graph_data in snapshot.get('graphs', {}).items():
                graph_title = graph_data.get('title', graph_name)
                imgui.spacing()
                expanded_graph, _ = imgui.collapsing_header(
                    f"{graph_title}##{name}_{graph_name}",
                    flags=imgui.TREE_NODE_DEFAULT_OPEN
                )
                if expanded_graph:
                    imgui.indent()
                    self._graph_renderer.render_single_graph(graph_data, f"_{name}_{graph_name}")
                    imgui.unindent()
    
    # ========================================================================
    # Camera Initialization
    # ========================================================================
    
    def _init_cameras_from_viz_states(self) -> None:
        """Initialize cameras for each render space from visualization states."""
        for viz_name, viz_state in self._visualization_states.items():
            snapshot = viz_state.get_snapshot()
            for rs in snapshot.get('render_spaces', []):
                camera_key = f"{viz_name}::{rs['name']}"
                # Create camera with initial settings from render space spec
                self._cameras[camera_key] = CameraState(
                    azimuth=rs.get('camera_azimuth', 45.0),
                    elevation=rs.get('camera_elevation', -45.0),
                    x=rs.get('camera_position', (2.0, 2.0, 2.0))[0],
                    y=rs.get('camera_position', (2.0, 2.0, 2.0))[1],
                    z=rs.get('camera_position', (2.0, 2.0, 2.0))[2],
                )
    
    def _get_camera(self, viz_name: str, render_space_name: str) -> CameraState:
        """Get camera for a specific render space, creating if needed."""
        camera_key = f"{viz_name}::{render_space_name}"
        if camera_key not in self._cameras:
            self._cameras[camera_key] = CameraState()
        return self._cameras[camera_key]
    
    # ========================================================================
    # 3D Scene Rendering
    # ========================================================================
    
    def _render_3d_scene_inline(self, viz_name: str, render_space: dict) -> None:
        """Render 3D scene inline within current window using FBO.
        
        Renders to an FBO texture and displays it as an ImGui image.
        
        Args:
            viz_name: Name of the visualization state
            render_space: Render space snapshot data (includes 'name', 'nodes', camera settings)
        """
        rs_name = render_space['name']
        camera = self._get_camera(viz_name, rs_name)
        
        imgui.text(f"Camera: Az:{camera.azimuth:.0f}° El:{camera.elevation:.0f}° Pos:({camera.x:.1f},{camera.y:.1f},{camera.z:.1f})")
        imgui.text("WASD: Move | Right-drag: Look | Middle-click: Reset")
        
        # Get available size for 3D view
        avail_width = imgui.get_content_region_available()[0] - 10
        view_width = max(int(avail_width), 100)
        view_height = 400  # Fixed height for inline view
        
        # Render to texture
        texture_id = self._renderer_3d_gl.render_to_texture(
            view_width, view_height, camera, render_space['nodes']
        )
        
        if texture_id is not None:
            # Display the rendered texture (flip Y for OpenGL texture orientation)
            # Debug: print texture info once
            if not hasattr(self, '_texture_debug_printed'):
                print(f"[UI] Displaying texture: id={texture_id}, size={view_width}x{view_height}")
                self._texture_debug_printed = True
            
            # Get image position before drawing
            image_pos = imgui.get_cursor_screen_pos()
            imgui.image(texture_id, view_width, view_height, uv0=(0, 1), uv1=(1, 0))
            
            # Overlay text using ImGui draw list
            self._draw_text_overlay(image_pos, view_width, view_height)
            
            # Check if image is hovered for input
            is_hovered = imgui.is_item_hovered()
            self._handle_camera_input(camera, is_hovered)
        else:
            # Fallback - just show placeholder
            imgui.text(f"[3D View: {len(render_space['nodes'])} nodes]")
            imgui.invisible_button(f"3d_view_{viz_name}_{rs_name}", view_width, view_height)
            is_hovered = imgui.is_item_hovered()
            self._handle_camera_input(camera, is_hovered)
    
    def _render_3d_scene_window(self, viz_name: str, render_space: dict) -> None:
        """Render 3D scene in a separate floating window using FBO.
        
        Renders to an FBO texture and displays it as an ImGui image.
        
        Args:
            viz_name: Name of the visualization state
            render_space: Render space snapshot data
        """
        rs_name = render_space['name']
        rs_title = render_space.get('title', rs_name)
        imgui.begin(f"{viz_name} - {rs_title}", True, imgui.WINDOW_NO_COLLAPSE)
        
        camera = self._get_camera(viz_name, rs_name)
        imgui.text(f"Camera: Az:{camera.azimuth:.0f}° El:{camera.elevation:.0f}° Pos:({camera.x:.1f},{camera.y:.1f},{camera.z:.1f})")
        imgui.text("WASD: Move | Right-drag: Look | Middle-click: Reset")
        imgui.separator()
        
        # Get window content size
        window_size = imgui.get_window_size()
        view_width = max(int(window_size[0] - 20), 100)
        view_height = max(int(window_size[1] - 100), 100)
        
        # Render to texture
        texture_id = self._renderer_3d_gl.render_to_texture(
            view_width, view_height, camera, render_space['nodes']
        )
        
        if texture_id is not None:
            # Display the rendered texture (flip Y for OpenGL texture orientation)
            # Get image position before drawing
            image_pos = imgui.get_cursor_screen_pos()
            imgui.image(texture_id, view_width, view_height, uv0=(0, 1), uv1=(1, 0))
            
            # Overlay text using ImGui draw list
            self._draw_text_overlay(image_pos, view_width, view_height)
            
            # Check if image is hovered for input
            is_hovered = imgui.is_item_hovered()
            self._handle_camera_input(camera, is_hovered)
        else:
            imgui.text(f"[3D View: {len(render_space['nodes'])} nodes]")
            imgui.invisible_button(f"3d_view_{viz_name}_{rs_name}", view_width, view_height)
            is_hovered = imgui.is_item_hovered()
            self._handle_camera_input(camera, is_hovered)
        
        imgui.end()
    
    def _draw_text_overlay(self, image_pos: tuple, view_width: int, view_height: int) -> None:
        """Draw projected text labels over the 3D view.
        
        Args:
            image_pos: Screen position (x, y) of the image top-left corner
            view_width: Width of the rendered view
            view_height: Height of the rendered view
        """
        projected_text = self._renderer_3d_gl.get_projected_text()
        if not projected_text:
            return
        
        draw_list = imgui.get_window_draw_list()
        
        for item in projected_text:
            # Calculate absolute screen position
            screen_x = image_pos[0] + item['x']
            screen_y = image_pos[1] + item['y']
            
            # Check bounds
            if screen_x < image_pos[0] or screen_x > image_pos[0] + view_width:
                continue
            if screen_y < image_pos[1] or screen_y > image_pos[1] + view_height:
                continue
            
            # Convert color to ImGui format (0xAABBGGRR)
            color = item.get('color', (1.0, 1.0, 1.0))
            r = int(color[0] * 255) if len(color) > 0 else 255
            g = int(color[1] * 255) if len(color) > 1 else 255
            b = int(color[2] * 255) if len(color) > 2 else 255
            color_u32 = 0xFF000000 | (b << 16) | (g << 8) | r
            
            # Draw text
            text = item.get('text', '')
            draw_list.add_text(screen_x, screen_y, color_u32, text)
    
    def _handle_camera_input(self, camera: CameraState, is_hovered: bool) -> None:
        """Handle mouse and keyboard input for camera control.
        
        Args:
            camera: Camera state to update
            is_hovered: Whether the 3D view is hovered
        """
        if is_hovered:
            # Middle click - reset
            if imgui.is_mouse_clicked(2):
                camera.reset()
            
            # Right click - start drag
            if imgui.is_mouse_clicked(1):
                self._camera_controller.start_drag(imgui.get_mouse_pos())
            
            # Drag to rotate
            if imgui.is_mouse_down(1) and self._camera_controller.is_dragging:
                self._camera_controller.update_drag(camera, imgui.get_mouse_pos())
            
            # Keyboard movement
            io = imgui.get_io()
            self._camera_controller.apply_keyboard_movement(
                camera,
                forward=io.keys_down[ord('W')],
                backward=io.keys_down[ord('S')],
                left=io.keys_down[ord('A')],
                right=io.keys_down[ord('D')],
                up=io.keys_down[ord('E')],
                down=io.keys_down[ord('Q')]
            )
        
        if imgui.is_mouse_released(1):
            self._camera_controller.stop_drag()
    
    # ========================================================================
    # Main UI Rendering
    # ========================================================================
    
    def _render_ui(self) -> None:
        """Render the main UI."""
        # For floating mode, render parameter windows AND visualization as separate floating windows
        if self._layout_mode == LayoutMode.FLOATING:
            # Render visualization windows (separate floating)
            for name, viz_state in self._visualization_states.items():
                snapshot = viz_state.get_snapshot()
                for render_space in snapshot.get('render_spaces', []):
                    if render_space.get('nodes'):
                        self._render_3d_scene_window(name, render_space)
                if snapshot['graphs']:
                    self._graph_renderer.render_graphs_window(name, snapshot['graphs'])
            
            # Render parameter windows (separate floating)
            self._layout_renderer.render_floating_layout(self._parameter_states, self._window)
            
            # Render global control bar
            self._render_global_controls_floating()
        else:
            # For other modes, render everything inline in main window
            self._render_main_window()
    
    def _render_global_controls_floating(self) -> None:
        """Render global controls as a floating window."""
        imgui.set_next_window_position(10, 10, imgui.FIRST_USE_EVER)
        imgui.set_next_window_size(650, 120, imgui.FIRST_USE_EVER)
        imgui.begin("Global Controls##floating", closable=False)
        
        imgui.text(f"{self._title} - Global Controls")
        imgui.separator()
        imgui.spacing()
        
        if imgui.button("Save All", width=100):
            for state in self._parameter_states.values():
                state.save_to_file()
            self._set_status("✓ All configurations saved successfully!", success=True)
        
        imgui.same_line()
        
        if imgui.button("Reset to Saved", width=120):
            for state in self._parameter_states.values():
                state.load_from_file()
            self._set_status("✓ All parameters reset to saved values", success=True)
        
        imgui.same_line()
        
        if imgui.button("Reset to Defaults", width=140):
            for state in self._parameter_states.values():
                state.reset_to_defaults()
            self._set_status("✓ All parameters reset to default values", success=True)
        
        imgui.same_line()
        
        if imgui.button("Snap to Fit", width=100):
            self._layout_renderer.trigger_auto_arrange()
            self._set_status("✓ Windows arranged in grid", success=True)
        
        # Status bar
        self._render_status_bar()
        
        imgui.end()
    
    def _render_main_window(self) -> None:
        """Render main window for tabs/vertical/horizontal layouts."""
        imgui.set_next_window_position(0, 0)
        imgui.set_next_window_size(*glfw.get_window_size(self._window))
        
        imgui.begin(
            self._title,
            closable=False,
            flags=imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_COLLAPSE
        )
        
        # Render layout based on mode
        content_height = imgui.get_window_height() - 150
        
        imgui.begin_child("parameters", height=content_height)
        
        if self._layout_mode == LayoutMode.TABS:
            self._layout_renderer.render_tabbed_layout(
                self._parameter_states, self._visualization_states
            )
        elif self._layout_mode == LayoutMode.VERTICAL:
            self._layout_renderer.render_vertical_layout(
                self._parameter_states, self._visualization_states
            )
        elif self._layout_mode == LayoutMode.HORIZONTAL:
            self._layout_renderer.render_horizontal_layout(
                self._parameter_states, self._visualization_states
            )
        
        imgui.end_child()
        
        # Global action buttons
        imgui.separator()
        imgui.spacing()
        
        if imgui.button("Save All", width=120):
            for state in self._parameter_states.values():
                state.save_to_file()
            self._set_status("✓ All configurations saved successfully!", success=True)
        
        imgui.same_line()
        
        if imgui.button("Reset All to Saved", width=150):
            for state in self._parameter_states.values():
                state.load_from_file()
            self._set_status("✓ All parameters reset to saved values", success=True)
        
        imgui.same_line()
        
        if imgui.button("Reset All to Defaults", width=170):
            for state in self._parameter_states.values():
                state.reset_to_defaults()
            self._set_status("✓ All parameters reset to default values", success=True)
        
        # Status bar
        self._render_status_bar()
        
        imgui.end()
    
    def _render_status_bar(self) -> None:
        """Render status message bar."""
        if self._status_message and (time.time() - self._status_time) < 3.0:
            imgui.spacing()
            imgui.separator()
            color = (0.3, 0.8, 0.3) if self._status_success else (0.8, 0.3, 0.3)
            imgui.text_colored(self._status_message, *color)
    
    # ========================================================================
    # Window Management
    # ========================================================================
    
    def _open(self) -> None:
        """Open the ImGui window (called on UI thread)."""
        if self._is_open:
            return
        
        # Initialize GLFW
        if not glfw.init():
            raise RuntimeError("Failed to initialize GLFW")
        
        # Create window with depth buffer
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)
        glfw.window_hint(glfw.DEPTH_BITS, 24)  # Enable depth buffer
        
        window_width = 900 if self._layout_mode == LayoutMode.HORIZONTAL else 700
        if self._layout_mode == LayoutMode.FLOATING:
            window_width = 1280
            window_height = 960
        else:
            window_height = 800
        
        self._window = glfw.create_window(window_width, window_height, self._title, None, None)
        if not self._window:
            glfw.terminate()
            raise RuntimeError("Failed to create GLFW window")
        
        glfw.make_context_current(self._window)
        glfw.swap_interval(1)  # Enable vsync
        
        # Initialize ImGui
        imgui.create_context()
        self._impl = GlfwRenderer(self._window)
        
        # Style
        style = imgui.get_style()
        style.window_rounding = 5.0
        style.frame_rounding = 3.0
        style.scrollbar_rounding = 3.0
        
        # Colors - dark theme
        imgui.style_colors_dark()
        
        self._is_open = True
    
    def _update(self) -> bool:
        """Update UI (called on UI thread)."""
        if not self._is_open or self._window is None:
            return False
        
        # Check if window should close
        if glfw.window_should_close(self._window):
            return False
        
        # Debug timing
        _DEBUG_UI_TIMING = False
        if _DEBUG_UI_TIMING:
            t0 = time.perf_counter()
        
        # Poll events
        glfw.poll_events()
        self._impl.process_inputs()
        
        if _DEBUG_UI_TIMING:
            t1 = time.perf_counter()
        
        # Clear the framebuffer
        import OpenGL.GL as gl  # type: ignore[import-not-found]
        gl.glClearColor(0.1, 0.1, 0.1, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        
        # Start new frame
        imgui.new_frame()
        
        if _DEBUG_UI_TIMING:
            t2 = time.perf_counter()
        
        # Render UI
        self._render_ui()
        
        if _DEBUG_UI_TIMING:
            t3 = time.perf_counter()
        
        # Render
        imgui.render()
        glfw.make_context_current(self._window)
        imgui_draw_data = imgui.get_draw_data()
        if imgui_draw_data:
            self._impl.render(imgui_draw_data)
        
        if _DEBUG_UI_TIMING:
            t4 = time.perf_counter()
        
        glfw.swap_buffers(self._window)
        
        if _DEBUG_UI_TIMING:
            t5 = time.perf_counter()
            if not hasattr(self, '_ui_timing_accum'):
                self._ui_timing_accum = {'poll': 0.0, 'setup': 0.0, 'render_ui': 0.0, 'imgui': 0.0, 'swap': 0.0}
                self._ui_timing_count = 0
            self._ui_timing_accum['poll'] += (t1 - t0)
            self._ui_timing_accum['setup'] += (t2 - t1)
            self._ui_timing_accum['render_ui'] += (t3 - t2)
            self._ui_timing_accum['imgui'] += (t4 - t3)
            self._ui_timing_accum['swap'] += (t5 - t4)
            self._ui_timing_count += 1
            if self._ui_timing_count >= 60:
                print(f"[UI TIMING] Over {self._ui_timing_count} frames (avg ms):")
                for k, v in self._ui_timing_accum.items():
                    print(f"  {k}: {1000 * v / self._ui_timing_count:.3f}ms")
                total = sum(self._ui_timing_accum.values())
                print(f"  TOTAL: {1000 * total / self._ui_timing_count:.3f}ms ({self._ui_timing_count / total:.1f} FPS)")
                self._ui_timing_accum = {'poll': 0.0, 'setup': 0.0, 'render_ui': 0.0, 'imgui': 0.0, 'swap': 0.0}
                self._ui_timing_count = 0
        
        return True
    
    def _close(self) -> None:
        """Close the ImGui window (called on UI thread)."""
        if self._impl is not None:
            self._impl.shutdown()
            self._impl = None
        
        if self._window is not None:
            glfw.destroy_window(self._window)
            self._window = None
        
        glfw.terminate()
        self._is_open = False
    
    # ========================================================================
    # Thread Management
    # ========================================================================
    
    def _start(self) -> None:
        """Start the UI thread (called automatically in __init__)."""
        if self._running:
            return
        
        try:
            self._stop_event.clear()
            self._running = True
            self._thread = threading.Thread(target=self._run_ui_loop, daemon=True)
            self._thread.start()
        
        except Exception as e:
            print(f"[MultiRetargeterTuningUIImGui] Failed to start: {e}")
            self._running = False
    
    def _run_ui_loop(self):
        """UI thread main loop."""
        try:
            # Open the window
            self._open()
            
            # Event loop - vsync handles rate limiting
            while self._running and not self._stop_event.is_set():
                if not self._update():
                    break
        
        finally:
            self._close()
            self._running = False
    
    def _stop(self) -> None:
        """Stop the async UI and wait for thread to finish."""
        if not self._running:
            return
        
        self._running = False
        self._stop_event.set()
        
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        
        self._thread = None
    
    def __del__(self):
        """Destructor - stops UI automatically (RAII)."""
        self._stop()
    
    def is_running(self) -> bool:
        """Check if the async UI is currently running."""
        return self._running
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - stops UI."""
        self._stop()
        return False
