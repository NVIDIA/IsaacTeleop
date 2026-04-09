# TeleopViz — Teleop Visual Streaming Renderer

**Author:** Farbod Motlagh
**Status:** Draft
**Created:** April 2026

---

## Overview

TeleopViz (`isaacteleop.viz`) is a lightweight C++ compositor module for Isaac
Teleop that renders 2D sensor feeds and 3D reconstruction content into XR or
windowed displays. It replaces the Holoscan-based camera streaming app with a
self-contained Vulkan compositor that integrates directly with Isaac Teleop's
device tracking and retargeting pipeline.

The current camera streaming solution pulls in the full Holoscan SDK, HoloHub
XR operators, GXF entity model, and HolovizOp. TeleopViz removes these
dependencies and provides a purpose-built module (~2000 lines of Vulkan code)
covering 2D plane, RGBD projection, and combined rendering.

No third-party rendering library provides the combination of CUDA-Vulkan
interop, OpenXR swapchain management, and simple tensor submission APIs that
this module requires. Vulkan is the only viable graphics API (required by
OpenXR on NVIDIA, by CUDA interop, and by nvblox_renderer).

## Goals

- C++ core with Python bindings (`isaacteleop.viz`) for compositing 2D
  textures and RGBD content into XR and windowed displays.
- Self-contained Vulkan infrastructure — no shared code dependency on
  nvblox_renderer, Holoscan, or HoloHub.
- Zero-copy integration with external renderers via Vulkan render targets.
- Expose XR runtime info (resolution, FOV, frame timing, view poses) to
  content producers.
- Reference examples: multi-camera plane streaming and 3D reconstruction
  visualization.

## Non-Goals

- Camera capture and network streaming (GStreamer, StreamSDK, V4L2 remain
  separate — TeleopViz consumes frames, not produces them).
- Retargeting, device I/O, or teleop session management (remain in Isaac
  Teleop Core).
- General-purpose rendering engine (no lighting, shadows, PBR, scene graphs).
  Complex 3D content is rendered by external engines and submitted as a layer.

---

## Architecture

TeleopViz sits between content producers (cameras, reconstruction engines,
any renderer) and display targets (OpenXR devices, desktop windows, headless).
It is a compositor — it assembles content from multiple sources into a final
frame.

The module lives under `src/teleopviz/` in the IsaacTeleop tree as
`isaacteleop.viz`. It repackages the same OpenXR + Vulkan + CUDA interop
patterns used by HoloHub's XR operators into a standalone library with a
frame-loop API — no Holoscan operator graph, no GXF, no external framework.

### Module Layout

```
IsaacTeleop/
└── src/
    └── teleopviz/
        ├── CMakeLists.txt
        ├── include/teleopviz/
        │   ├── viz_session.h
        │   ├── viz_compositor.h
        │   ├── layers/
        │   │   ├── layer_base.h
        │   │   ├── quad_layer.h
        │   │   ├── projection_layer.h
        │   │   └── overlay_layer.h
        │   └── core/
        │       ├── vk_context.h
        │       ├── cuda_texture.h
        │       ├── render_target.h
        │       ├── frame_sync.h
        │       └── frame_info.h
        ├── src/
        ├── shaders/
        │   ├── textured_quad.vert/frag
        │   ├── fullscreen_blit.vert/frag
        │   └── overlay.vert/frag
        ├── python/
        │   └── viz_bindings.cpp
        └── tests/
```

### Vulkan Infrastructure

TeleopViz owns its own Vulkan context and CUDA interop rather than sharing
with nvblox_renderer. This is deliberate: the two libraries have different
Vulkan init paths (standalone vs XR-negotiated), different dependency
directions (nvblox is optional), and different development schedules.
Integration between them happens at the Vulkan API contract level
(`VkCommandBuffer`, `VkRenderPass`), not through shared code.

| Component | Purpose |
|-----------|---------|
| `vk_context` | Instance/device creation: standalone (enumerate GPU) or XR-negotiated (`xrCreateVulkanDeviceKHR`). `VK_KHR_external_memory_fd` extensions. |
| `cuda_texture` | Import CUDA device pointer as VkImage via external memory. Semaphore export/import for GPU sync. |
| `render_target` | Color + depth VkImage pairs, VkRenderPass, VkFramebuffer. XR path wraps XrSwapchain images; window path wraps GLFW swapchain. |
| `frame_sync` | Per-frame fences, submit semaphores, double-buffer swap. |
| Fixed pipelines | 2-3 hardcoded VkPipeline (textured quad, fullscreen blit, overlay). Precompiled SPIR-V shaders. |

---

## Core API

### VizSession

The central object. Manages the Vulkan context, OpenXR session (if XR),
display target, and layer registry.

```cpp
class VizSession {
public:
    struct Config {
        DisplayMode mode;           // kXR, kWindow, kHeadless
        uint32_t window_width;
        uint32_t window_height;
        bool window_stereo = false; // SBS stereo in window (debug)
    };

    // Creates session with its own Vulkan context + display target.
    static std::unique_ptr<VizSession> create(const Config& config);

    // Future: receive session from extended OXR module.
    static std::unique_ptr<VizSession> createWithXrSession(
        XrSession xr_session, VkDevice vk_device,
        VkQueue vk_queue, uint32_t queue_family_index);

    // Layer management.
    QuadLayer*       addQuadLayer(const QuadLayer::Config& config);
    ProjectionLayer* addProjectionLayer(const ProjectionLayer::Config& config);
    OverlayLayer*    addOverlayLayer(const OverlayLayer::Config& config);
    void removeLayer(LayerBase* layer);

    // Frame loop.
    FrameInfo beginFrame();
    void endFrame();

    // Runtime queries.
    Resolution getRecommendedResolution() const;
    FrameTimingStats getFrameTimingStats() const;

    // Handle access (for external renderer integration and session sharing).
    VkDevice getVkDevice() const;
    VkPhysicalDevice getVkPhysicalDevice() const;
    uint32_t getVkQueueFamilyIndex() const;
    OpenXRSessionHandles getOxrHandles() const;  // XR mode only
};
```

### FrameInfo

Returned by `beginFrame()`. Provides per-frame state to content producers.

```cpp
struct ViewInfo {
    float view_matrix[16];          // Column-major 4x4
    float projection_matrix[16];
    float view_projection[16];      // Precomputed V*P
    XrFovf fov;
    XrPosef pose;
};

struct FrameInfo {
    uint64_t frame_index;
    int64_t predicted_display_time; // XR predicted display time (ns)
    float delta_time;
    bool should_render;
    std::vector<ViewInfo> views;    // Per-eye (typically 2)
    Resolution resolution;
};

struct FrameTimingStats {
    float render_fps;
    float target_fps;
    uint64_t missed_frames;
    float avg_frame_time_ms;
    float gpu_time_ms;
};
```

In windowed mode, `FrameInfo` is populated with synthetic values (vsync
timing, identity view for mono, window resolution).

---

## Layer Types

### QuadLayer

A 2D texture placed in 2D or 3D space. Accepts a CUDA device pointer.

```cpp
class QuadLayer : public LayerBase {
public:
    struct Config {
        std::string name;
        float width_meters;
        float height_meters;
        PlacementMode placement;    // kWorldLocked, kHeadLocked, kLazyLocked
        int32_t priority;
    };

    void submitTexture(const void* cuda_ptr, uint32_t width, uint32_t height,
                       PixelFormat format, cudaStream_t stream);
    void setPose(const Pose3D& pose);
    void setSize(float width_meters, float height_meters);
    void setVisible(bool visible);
    void setOpacity(float opacity);
};
```

**Placement modes:** `kWorldLocked` (fixed in space), `kHeadLocked` (follows
headset), `kLazyLocked` (follows headset with damping — good for primary
camera feeds). In windowed mode, planes are tiled as 2D rectangles.

**Stale content:** If no new texture arrives within a timeout (default 2s), a
placeholder is displayed and a warning is emitted through the stats API.

Use cases: camera feeds, depth maps, sensor visualizations.

### ProjectionLayer

A full stereo RGBD view. Supports push (CUDA buffers) and pull (Vulkan render
target callback) content submission.

```cpp
class ProjectionLayer : public LayerBase {
public:
    struct Config {
        std::string name;
        int32_t priority;
    };

    // Push: submit pre-rendered CUDA buffers.
    void submitFrame(const void* cuda_color, const void* cuda_depth,
                     uint32_t width, uint32_t height, cudaStream_t stream);

    // Pull: register callback invoked each frame with render target + views.
    using RenderCallback = std::function<void(
        const RenderTarget& target, const std::vector<ViewInfo>& views,
        VkCommandBuffer cmd)>;
    void setRenderCallback(RenderCallback callback);

    const RenderTarget& getRenderTarget() const;
    void setVisible(bool visible);
};
```

Use cases: nvblox 3D reconstruction, depth-enhanced camera rendering.

### OverlayLayer

A 2D texture composited in screen space after all world-space content. No
depth testing.

```cpp
class OverlayLayer : public LayerBase {
public:
    struct Config {
        std::string name;
        float x, y;                 // Normalized screen position [0,1]
        float width, height;        // Normalized screen size [0,1]
        int32_t priority;
    };

    void submitTexture(const void* cuda_ptr, uint32_t width, uint32_t height,
                       PixelFormat format, cudaStream_t stream);
    void setRect(float x, float y, float width, float height);
    void setVisible(bool visible);
    void setOpacity(float opacity);
};
```

Use cases: telemetry HUD, connection status, battery indicators.

---

## Content Submission: Push vs Pull

| | Push Model | Pull Model |
|---|---|---|
| **How** | Producer calls `submitTexture`/`submitFrame` with CUDA pointers | TeleopViz invokes callback with VkCommandBuffer + RenderTarget |
| **Copy** | One copy (CUDA → Vulkan import) | Zero copy (external renderer draws directly into framebuffer) |
| **Latency** | Up to one frame of staleness | Minimal (rendered for current predicted time) |
| **Coupling** | Loose — any CUDA source | Tight — callback runs on render thread |
| **Use case** | Camera frames, remote RGBD, async pipelines | nvblox_renderer, any local Vulkan renderer |

**Pull model render target:**

```cpp
struct RenderTarget {
    VkImage color_image;
    VkImageView color_view;
    VkImage depth_image;
    VkImageView depth_view;
    VkRenderPass render_pass;
    VkFramebuffer framebuffer;
    uint32_t width, height, num_views;
    VkFormat color_format;          // VK_FORMAT_R8G8B8A8_SRGB
    VkFormat depth_format;          // VK_FORMAT_D32_SFLOAT
};
```

External renderers must create pipelines compatible with this render pass
(RGBA8_SRGB color, D32_SFLOAT depth, 1 sample, 1 subpass). TeleopViz exposes
this via `RenderTarget::render_pass`. Both libraries remain independent — the
integration lives in the example application.

---

## IsaacTeleop Integration

### Package Name

`isaacteleop.viz` — follows the pattern of `isaacteleop.oxr`,
`isaacteleop.mcap`, `isaacteleop.schema`.

### Current OXR Module State

IsaacTeleop's `OpenXRSession` creates a **headless** session for device
tracking. It exposes only OpenXR handles — no Vulkan device, no swapchains,
no frame submission:

```cpp
struct OpenXRSessionHandles {
    XrInstance instance{};
    XrSession session{};            // Headless — no Vulkan binding
    XrSpace space{};                // Stage reference space only
    PFN_xrGetInstanceProcAddr xrGetInstanceProcAddr{};
};
```

This session cannot be used for rendering.

### Session Ownership Options

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| **A: Separate sessions** (start here) | TeleopViz creates its own graphics-bound session. OXR keeps headless. | No changes to existing code. Works today. | Two CloudXR connections. |
| **B: TeleopViz owns, trackers attach** (future) | TeleopViz creates session. Trackers attach via `oxr_handles`. | Single connection. No timing discrepancy. | Requires trackers to accept external session. |
| **C: Extended OXR module** (future) | OXR optionally creates Vulkan-bound session, passes handles to TeleopViz. | OXR retains ownership. | Requires OXR module changes. |

**Start with Option A**, migrate to **Option B** using TeleopSession's
existing `oxr_handles` config:

```python
# Option A (now): two sessions
viz_session = isaacteleop.viz.VizSession.create(config)
teleop_config = TeleopSessionConfig(pipeline=pipeline)

# Option B (future): unified session
viz_session = isaacteleop.viz.VizSession.create(config)
teleop_config = TeleopSessionConfig(
    pipeline=pipeline,
    oxr_handles=viz_session.get_oxr_handles(),  # trackers use viz session
)
```

### Application-Level Integration

TeleopViz integrates alongside `TeleopSession`, not inside it. Both run in
the application's main loop:

```python
import isaacteleop.viz as viz
from isaacteleop import TeleopSession, TeleopSessionConfig

viz_session = viz.VizSession.create(viz.Config(mode=viz.DisplayMode.XR))
cam_layer = viz_session.add_quad_layer(name="front_cam", ...)
recon_layer = viz_session.add_projection_layer(name="recon", ...)
recon_layer.set_render_callback(nvblox_render_fn)

teleop_config = TeleopSessionConfig(app_name="teleop", pipeline=pipeline)
with TeleopSession(teleop_config) as teleop:
    while running:
        frame = viz_session.begin_frame()
        teleop.step()
        cam_layer.submit_texture(camera_ptr, 1920, 1080, viz.RGBA8, stream)
        viz_session.end_frame()

viz_session.destroy()
```

---

## Rendering Strategy

### Single Render Pass (recommended)

All layers composited into one stereo framebuffer per frame, submitted as a
single `XrCompositionLayerProjection` with depth.

Per frame: `xrWaitFrame` → `xrBeginFrame` → `xrLocateViews` → acquire
swapchain → begin render pass (ProjectionLayer pull → QuadLayers → 
ProjectionLayer push → OverlayLayers) → end render pass → copy to swapchain
→ `xrEndFrame`.

**Pros:** Unlimited layers. Correct depth compositing between 2D planes and
3D content. Full control over blending.
**Cons:** No per-layer runtime reprojection.

### OpenXR Quad Layers (alternative)

Each QuadLayer → `XrCompositionLayerQuad`. Each ProjectionLayer →
`XrCompositionLayerProjection`. Runtime composites.

**Pros:** Simpler. Per-layer reprojection.
**Cons:** ~16 layer limit. No depth compositing between layers. Cannot
embed 2D planes in 3D space.

**Recommendation:** Single render pass. It is the only approach that supports
combined 2D + 3D with correct depth. Head-locked overlays can optionally use
quad layers for reprojection benefits in the future.

---

## XR Runtime Information

Content producers need resolution, FOV, and timing. TeleopViz exposes:

**Session-level (stable):** recommended per-eye resolution
(`xrEnumerateViewConfigurationViews`), view count, refresh rate.

**Per-frame (`FrameInfo`):** per-eye pose + FOV + view-projection matrices
(`xrLocateViews`), predicted display time, `should_render` flag.

**Performance stats (polled):** render FPS, target FPS, missed frames,
average frame time, GPU time, stale layer count.

---

## External Renderer Integration

TeleopViz and external renderers (nvblox_renderer) are independent libraries.
Integration happens at the Vulkan API contract level.

**Pull model (zero-copy):** TeleopViz provides a VkCommandBuffer + render
target. The external renderer records draw commands into it. No buffer
copies, no shared Vulkan context needed.

For nvblox_renderer specifically: `MeshVisualizer::render(cmd, view_proj, x,
y, w, h)` already accepts an external command buffer. The only requirement is
render pass compatibility (RGBA8_SRGB + D32_SFLOAT, 1 sample). Mesh data
updates use nvblox's own `SharedBuffer`/`SharedTexture` — only the final draw
targets TeleopViz's framebuffer.

**Vulkan device sharing:** Pull-model pipelines must be created on
TeleopViz's VkDevice (via `VizSession::getVkDevice()`). nvblox_renderer's own
VkContext is unused in this path.

**Push model (fallback):** For sources that can't share a Vulkan device
(remote RGBD, separate process), submit CUDA color + depth pointers. One
extra copy via CUDA-Vulkan external memory import.

---

## Implementation Decisions

Based on analysis of the HoloHub XR operator implementation.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Stereo layout | Side-by-side in one 2D swapchain (width = 2x recommended) | Proven pattern from HoloHub XR. Multiview possible later. |
| Color format | `VK_FORMAT_R8G8B8A8_SRGB` | Matches HoloHub. Correct gamma for XR. |
| Depth format | `VK_FORMAT_D32_SFLOAT` | Required by `XR_KHR_composition_layer_depth`. |
| Shaders | Precompiled SPIR-V at CMake time | 3 trivial shader pairs. No runtime compilation needed. |
| CUDA-Vulkan interop | Opaque FD external memory + semaphores | Same pattern as `XrSwapchainCuda`. |
| Rendering pipeline | Intermediate framebuffer → copy to XR swapchain | Swapchains use TRANSFER_DST only. Intermediate FB allows VkRenderPass. |
| Thread model | Single render thread, multi-threaded producers | Atomic double-buffer swap per layer. |
| Windowed stereo | Mono default, SBS stereo as config option | Mono for dev, SBS for debugging XR layout. |
| OpenXR extensions | `COMPOSITION_LAYER_DEPTH`, `VULKAN_ENABLE2`, `CONVERT_TIMESPEC_TIME` | Matches HoloHub. |
| Vulkan device extensions | `EXTERNAL_MEMORY`, `EXTERNAL_MEMORY_FD` | Required for CUDA interop. |

---

## Examples

### Camera Plane Streaming (`examples/teleopviz/camera_planes/`)

Replaces the Holoscan camera_streamer for 2D planes. Camera capture (V4L2,
OAK-D, ZED) and GStreamer RTP code reused from existing camera_streamer,
extracted from Holoscan operators into standalone modules. TeleopViz renders
each feed as a QuadLayer. Supports local and remote sources, XR and windowed
display. YAML config for camera layout and plane placement.

### 3D Reconstruction Viz (`examples/teleopviz/reconstruction_viz/`) — future

nvblox_renderer integration via pull model. `MeshVisualizer` draws into
TeleopViz's ProjectionLayer render target. Optional QuadLayers for raw camera
feeds alongside the reconstruction.

### Combined Teleop Viz — future

Multi-camera QuadLayers + nvblox ProjectionLayer + telemetry OverlayLayers +
IsaacTeleop session for hand tracking and retargeting visualization.

---

## Build and Dependencies

Self-contained. Dependencies fetched via CMake FetchContent.

**Required:** Vulkan >= 1.2, CUDA >= 12.0, GLM, pybind11, GLFW.
**Optional:** OpenXR SDK (`BUILD_XR=ON`), CloudXR runtime (runtime only),
nvblox_renderer (examples only).

```cmake
option(BUILD_TELEOPVIZ "Build TeleopViz" ON)
if(BUILD_TELEOPVIZ)
    add_subdirectory(src/teleopviz)
endif()
```

---

## Migration Path from Holoscan Camera Streamer

| Current (Holoscan) | TeleopViz Replacement |
|---|---|
| HolovizOp (monitor tiling) | VizSession(kWindow) + QuadLayer per camera |
| XrPlaneRendererOp (XR planes) | VizSession(kXR) + QuadLayer per camera |
| XrBeginFrameOp / XrEndFrameOp | VizSession.beginFrame() / endFrame() |
| XrSession (HoloHub resource) | VizSession (standalone or external) |
| VideoStreamMonitorOp (timeout) | Built-in stale content detection per layer |
| FrameCombinerOp (async merge) | Built-in double buffering per layer |
| Holoscan EventBasedScheduler | Application main loop |
| GStreamer / NVENC/NVDEC ops | Reused as standalone C++/Python |

---

## Open Questions

1. **CloudXR dual-session validation**: Confirm two concurrent sessions (one
   headless for tracking, one graphics-bound for rendering) work without
   conflicts. If not, Option B (unified session) becomes mandatory.

2. **XR swapchain COLOR_ATTACHMENT usage**: If CloudXR supports it, the
   intermediate framebuffer copy could be eliminated (render directly to
   swapchain). Performance optimization, not blocking.

3. **VK_KHR_multiview**: Benchmark SBS vs multiview on target hardware. Add
   behind config flag if beneficial. Requires shader changes.

4. **OXR module changes for unified session**: VkDevice, VkQueue, view space
   exposure needed for future Option B/C. Not needed for Option A.
