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
dependencies and provides a purpose-built module (~3000-3500 lines of C++)
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
any renderer) and display targets (OpenXR devices, desktop windows).
It is a compositor — it assembles content from multiple sources into a final
frame.

The module lives under `src/viz/` in the IsaacTeleop tree as
`isaacteleop.viz`. It repackages the same OpenXR + Vulkan + CUDA interop
patterns used by HoloHub's XR operators into a standalone library with a
frame-loop API — no Holoscan operator graph, no GXF, no external framework.

### Module Layout

```
IsaacTeleop/
└── src/
    ├── viz/                                # Module source
    │   ├── CMakeLists.txt                  # adds cpp/, python/
    │   ├── cpp/
    │   │   ├── CMakeLists.txt              # static lib viz_core
    │   │   ├── inc/viz/                    # public headers
    │   │   │   ├── viz_session.hpp
    │   │   │   ├── viz_compositor.hpp
    │   │   │   ├── viz_buffer.hpp
    │   │   │   ├── layers/
    │   │   │   │   ├── layer_base.hpp
    │   │   │   │   ├── quad_layer.hpp
    │   │   │   │   ├── projection_layer.hpp   (Phase 2)
    │   │   │   │   └── overlay_layer.hpp      (Phase 2)
    │   │   │   └── core/
    │   │   │       ├── vk_context.hpp
    │   │   │       ├── cuda_texture.hpp
    │   │   │       ├── render_target.hpp
    │   │   │       ├── frame_sync.hpp
    │   │   │       └── frame_info.hpp
    │   │   ├── viz_session.cpp             # source files alongside inc/
    │   │   ├── viz_compositor.cpp
    │   │   ├── quad_layer.cpp
    │   │   ├── vk_context.cpp
    │   │   ├── cuda_texture.cpp
    │   │   ├── render_target.cpp
    │   │   └── frame_sync.cpp
    │   ├── shaders/
    │   │   ├── textured_quad.vert
    │   │   ├── textured_quad.frag
    │   │   ├── overlay.vert               (Phase 2)
    │   │   └── overlay.frag               (Phase 2)
    │   └── python/
    │       ├── CMakeLists.txt              # pybind11, output _viz
    │       ├── viz_bindings.cpp
    │       └── viz_init.py
    └── viz_tests/                          # Sibling test directory (convention)
        ├── CMakeLists.txt
        ├── cpp/
        │   ├── CMakeLists.txt              # Catch2, catch_discover_tests
        │   └── test_*.cpp
        └── python/
            ├── CMakeLists.txt              # uv run pytest
            ├── pyproject.toml
            └── test_*.py
```

**Why an intermediate framebuffer?** XR swapchain images (from CloudXR /
the OpenXR runtime) are typically created with only
`VK_IMAGE_USAGE_TRANSFER_DST_BIT` — they do **not** support
`VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT`, which means you cannot target them
directly with a `VkRenderPass`. This is the same constraint HoloHub's XR
operators work under.

The render pipeline is therefore two steps:
1. **Render pass** into TeleopViz's own intermediate framebuffer (a VkImage
   created with `COLOR_ATTACHMENT_BIT | TRANSFER_SRC_BIT`). All layer
   `record()` calls happen here.
2. **Blit** from the intermediate framebuffer to the swapchain image via
   `vkCmdBlitImage` (a Vulkan transfer command — no shader, no pipeline,
   no descriptor set needed). Handles format conversion and scaling if
   the intermediate and swapchain formats/dimensions differ.

In window mode, the same pattern applies: render to intermediate
framebuffer, then blit to the GLFW surface swapchain image. In headless
mode, step 2 is skipped — `readback()` reads the intermediate framebuffer
directly.

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
| `cuda_texture` | Dual-mode CUDA-Vulkan interop buffer (see Content Submission). VkImage backed by external memory with CUDA-mapped view. Semaphore export/import for GPU sync. |
| `render_target` | Color + depth VkImage pairs, VkRenderPass, VkFramebuffer. XR path wraps XrSwapchain images; window path wraps GLFW swapchain. |
| `frame_sync` | Per-frame fences, submit semaphores, double-buffer swap. |
| Fixed pipelines | Hardcoded VkPipeline for textured quad (Phase 1). Overlay pipeline added in Phase 2. Precompiled SPIR-V shaders. |

---

## Core API

### VizSession

The central object. Manages the Vulkan context, OpenXR session (if XR),
display target, and layer registry. Session lifecycle follows the state
machine defined in the Session State Machine section below.

```cpp
class VizSession {
public:
    struct Config {
        DisplayMode mode;           // kXR, kWindow, kHeadless
        uint32_t window_width;      // Window and headless mode
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
    QuadLayer*  addQuadLayer(const QuadLayer::Config& config);
    LayerBase*  addLayer(std::unique_ptr<LayerBase> layer);  // custom layers
    void        removeLayer(LayerBase* layer);

    // Phase 2:
    // ProjectionLayer* addProjectionLayer(const ProjectionLayer::Config&);
    // OverlayLayer*    addOverlayLayer(const OverlayLayer::Config&);

    // Frame loop.
    // beginFrame: In XR mode, calls xrWaitFrame (blocking), xrBeginFrame,
    // xrLocateViews. In window mode, blocks on vsync if enabled.
    // Python bindings release the GIL during blocking portions.
    FrameInfo beginFrame();
    void endFrame();

    // Session state.
    SessionState getState() const;

    // Runtime queries.
    Resolution getRecommendedResolution() const;
    FrameTimingStats getFrameTimingStats() const;

    // Readback (kHeadless only). Returns the last composited frame.
    VizBuffer readback(cudaStream_t stream = 0);

    // Handle access (for external renderer integration and session sharing).
    VkDevice getVkDevice() const;
    VkPhysicalDevice getVkPhysicalDevice() const;
    uint32_t getVkQueueFamilyIndex() const;
    VkRenderPass getRenderPass() const;          // For custom layer pipeline creation
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

In windowed mode, `FrameInfo` has one view with identity matrices and
window resolution. QuadLayers are tiled as 2D rectangles — no 3D
perspective. This is a dev/debug view, not a spatial preview of the XR
layout.

---

## VizBuffer

A lightweight, non-owning reference to a 2D pixel buffer on GPU. Used
throughout the layer API for content submission and buffer acquisition.

```cpp
enum class PixelFormat {
    kRGBA8,     // 4-channel uint8 color (Phase 1)
    kD32F,      // single-channel float32 depth (Phase 2)
};

struct VizBuffer {
    void* data;              // CUDA device pointer
    uint32_t width;
    uint32_t height;
    PixelFormat format;
    size_t pitch;            // Row pitch in bytes (0 = tightly packed)
};
```

`VizBuffer` has no ownership semantics — it does not allocate or free
memory. For Mode B (`acquire`/`release`), the layer owns the underlying
interop memory; `VizBuffer` is just a view into it.

In Python, `VizBuffer` exposes `__cuda_array_interface__` so CuPy can
wrap it zero-copy: `cupy.asarray(buf)`.

For RGBD content (Phase 2), color and depth are two separate `VizBuffer`s:

```cpp
struct VizBufferPair {            // Phase 2, for ProjectionLayer
    VizBuffer color;              // kRGBA8
    VizBuffer depth;              // kD32F
};
```

---

## Layer System

### LayerBase

All layers inherit from `LayerBase`, which defines the interface the
compositor calls during the render pass. Developers can subclass `LayerBase`
to implement custom rendering logic — they are not limited to the built-in
layer types.

```cpp
class LayerBase {
public:
    virtual ~LayerBase() = default;

    // Called by the compositor during the render pass. Subclasses record
    // Vulkan draw commands into the provided command buffer.
    // The render pass is already active (RGBA8_SRGB + D32_SFLOAT, 1 sample).
    virtual void record(VkCommandBuffer cmd,
                        const std::vector<ViewInfo>& views,
                        const RenderTarget& target) = 0;

    // Common properties.
    const std::string& getName() const;
    int32_t getPriority() const;
    bool isVisible() const;
    void setVisible(bool visible);
    void setPriority(int32_t priority);
};
```

**Custom layers:** A developer creates a VkPipeline compatible with
TeleopViz's render pass (via `RenderTarget::render_pass`), subclasses
`LayerBase`, implements `record()`, and registers it via
`VizSession::addLayer()`. The compositor iterates all layers sorted by
priority and calls `record()` for each visible layer. This is the same
contract as the pull model, generalized — any Vulkan drawing code works
as long as it's render-pass-compatible.

```cpp
// VizSession layer management
QuadLayer*  addQuadLayer(const QuadLayer::Config& config);
LayerBase*  addLayer(std::unique_ptr<LayerBase> layer);  // custom layers
void        removeLayer(LayerBase* layer);

// Phase 2:
ProjectionLayer* addProjectionLayer(const ProjectionLayer::Config& config);
OverlayLayer*    addOverlayLayer(const OverlayLayer::Config& config);
```

### QuadLayer

A 2D image placed in 2D or 3D space. The most common layer type for
camera feeds. Built-in textured-quad rendering + CUDA interop.

```cpp
struct LazyLockConfig {
    float look_away_angle = 45.0f;      // Degrees; reposition when user looks away
    float reposition_distance = 0.5f;   // Meters; reposition when user walks away
    float reposition_delay = 0.5f;      // Seconds before repositioning starts
    float transition_duration = 0.3f;   // Seconds for smooth reposition
};

class QuadLayer : public LayerBase {
public:
    struct Config {
        std::string name;
        float width_meters;
        float height_meters;
        PlacementMode placement;    // kWorldLocked, kHeadLocked, kLazyLocked, kCustom
        LazyLockConfig lazy_lock;   // Used when placement == kLazyLocked
        int32_t priority;
        float stale_timeout = 2.0f; // Seconds before showing placeholder
    };

    // Mode A: fire-and-forget. Copies from the VizBuffer into the
    // layer's interop back buffer. Non-blocking (enqueues on stream).
    void submit(const VizBuffer& image, cudaStream_t stream = 0);

    // Mode B: zero-copy write. Returns a VizBuffer pointing to the
    // layer's interop back buffer. Allocates on first call; reuses on
    // subsequent calls with matching dimensions (reallocates on change).
    // Producer writes into buf.data, then calls release().
    VizBuffer acquire(uint32_t width, uint32_t height,
                      PixelFormat format = PixelFormat::kRGBA8);
    void release(cudaStream_t stream = 0);

    void setPose(const Pose3D& pose);
    void setSize(float width_meters, float height_meters);
    void setVisible(bool visible);
    void setOpacity(float opacity);

    // Custom placement: register a callback invoked per frame with current
    // head pose. Returns the desired quad pose. Overrides placement mode.
    using PlacementCallback = std::function<Pose3D(
        const Pose3D& head_pose, float delta_time)>;
    void setPlacementCallback(PlacementCallback callback);

    // LayerBase override (internal — renders the textured quad).
    void record(VkCommandBuffer cmd, const std::vector<ViewInfo>& views,
                const RenderTarget& target) override;
};
```

**Placement modes:**
- `kWorldLocked` — fixed pose in stage space.
- `kHeadLocked` — follows headset pose exactly (HUD-style).
- `kLazyLocked` — follows headset with configurable damping
  (`LazyLockConfig`). Parameters match the existing camera_streamer UX.
- `kCustom` — application provides a `PlacementCallback` for full control.

In windowed mode, placement is ignored; layers are tiled as 2D rectangles.

**Stale content:** If no new texture arrives within `stale_timeout`, a
solid-color placeholder is displayed and `FrameTimingStats::stale_layers`
is incremented.

**Pixel format:** RGBA8 only (`kRGBA8`). One format, no branching in
shaders or pipelines. Producers that have BGRA or other formats convert to
RGBA upstream (trivial CUDA swizzle or decode pipeline config). The decode
pipeline (NvStreamDecoderOp) already converts NV12 → RGB; pad to RGBA
before submitting. Depth uses `kD32F` (Phase 2).

Use cases: camera feeds, depth maps, sensor visualizations.

### ProjectionLayer (Phase 2)

A full stereo RGBD view. Supports push (CUDA buffers) and pull (custom
`record()` override or render callback) content submission.

```cpp
class ProjectionLayer : public LayerBase {
public:
    struct Config {
        std::string name;
        int32_t priority;
    };

    // Push: submit pre-rendered color + depth.
    void submit(const VizBuffer& color, const VizBuffer& depth,
                cudaStream_t stream = 0);

    void setVisible(bool visible);

    void record(VkCommandBuffer cmd, const std::vector<ViewInfo>& views,
                const RenderTarget& target) override;
};
```

Use cases: nvblox 3D reconstruction, depth-enhanced camera rendering.

### OverlayLayer (Phase 2)

A 2D image composited in screen space after all world-space content. No
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

    void submit(const VizBuffer& image, cudaStream_t stream = 0);
    void setRect(float x, float y, float width, float height);
    void setVisible(bool visible);
    void setOpacity(float opacity);

    void record(VkCommandBuffer cmd, const std::vector<ViewInfo>& views,
                const RenderTarget& target) override;
};
```

Use cases: telemetry HUD, connection status, battery indicators.

---

## Content Submission

### Push Model (Phase 1)

Two modes for getting CUDA content into layers:

**Mode A — fire-and-forget (`submit(VizBuffer)`):** Producer owns
arbitrary CUDA memory, wraps it in a `VizBuffer`, and calls `submit`.
TeleopViz copies from the producer's buffer into its own interop back
buffer via `cudaMemcpyAsync`. Non-blocking — producer can reuse its buffer
immediately. In Python, `submit` also accepts any object with
`__cuda_array_interface__` (CuPy arrays, PyTorch CUDA tensors).

**Mode B — zero-copy write (`acquire` / `release`):** Producer calls
`acquire` to get a `VizBuffer` pointing to TeleopViz's interop back
buffer. Producer writes directly into `buf.data` (kernel, memcpy, NVDEC
output target, etc.), then calls `release` to signal completion. No extra
copy. Same pattern as HoloHub's `XrSwapchainCuda`.

| | Mode A (`submit`) | Mode B (`acquire` / `release`) |
|---|---|---|
| **Copy** | One `cudaMemcpyDeviceToDevice` per frame | Zero copy |
| **Ownership** | Producer owns source buffer | TeleopViz owns buffer, producer borrows |
| **Simplicity** | Simplest — works with any CUDA pointer / CuPy array | Requires producer to write into provided buffer |
| **Use case** | External sources, CuPy arrays, remote decode | Tight integration, NVDEC direct output |

### Double Buffering and Synchronization

Each layer has two interop buffers (front + back). Producers write to the
back buffer at their own rate. The renderer reads the front buffer.

Sync flow for Mode A:
1. `submit` enqueues `cudaMemcpyAsync` on producer's stream
2. After enqueue, CUDA signals an exported semaphore on that stream
3. At render time (`endFrame`), compositor checks if the semaphore fired
4. If yes: atomically swap front/back pointers. Vulkan submit waits on the
   imported semaphore before sampling the texture.
5. If no (producer hasn't finished): render the old front buffer (last frame)

Mode B is identical except step 1 is replaced by the producer's own writes.

**Behavior:** If the producer submits faster than the display rate, only the
latest frame is rendered (the previous back buffer content is overwritten).
If the producer is slower, the last completed frame is re-displayed. No
blocking on either side.

**Timing with beginFrame/endFrame:** `acquire`/`release` and
`beginFrame`/`endFrame` are independent lifecycles. The producer can
acquire, write, and release at any time — the compositor picks up the
latest completed content at `endFrame`. In a single-threaded loop the
pattern is sequential (acquire → write → release → endFrame), but
multi-threaded producers can write at their own rate on a separate thread.
If the producer calls `acquire` again before `endFrame` swaps, it gets the
same back buffer and overwrites the pending content (last writer wins).

### Pull Model / Custom Layers

The pull model is generalized through `LayerBase::record()`. Any layer
(built-in or custom) records Vulkan draw commands during the render pass.
This replaces the need for a separate callback API — a custom LayerBase
subclass IS the pull model. See the Layer System section above.

For ProjectionLayer (Phase 2), the built-in implementation handles CUDA
push internally. Custom layers handle their own rendering.

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

## Session State Machine

VizSession has a state machine that maps to OpenXR session lifecycle in XR
mode and simplifies to a minimal set in window mode.

```cpp
enum class SessionState {
    kUninitialized,  // Before create()
    kReady,          // Vulkan + display initialized. Layers can be added.
    kRunning,        // Frame loop active. beginFrame/endFrame work normally.
    kPaused,         // XR: session visible but not focused (no input).
                     // Still rendering, should_render may be true.
    kStopping,       // XR: session stopping. endFrame submits empty frames.
    kLost,           // XR: session lost. Must destroy and recreate.
    kDestroyed,      // After destroy(). No operations valid.
};
```

### OpenXR Session State Mapping

| OpenXR State | VizSession State | `should_render` | Notes |
|---|---|---|---|
| IDLE | kReady | — | After xrCreateSession |
| READY | kReady | — | xrBeginSession called automatically |
| SYNCHRONIZED | kRunning | false | Runtime synced but not visible yet |
| VISIBLE | kRunning | true | Rendering, but no input (another app has focus) |
| FOCUSED | kRunning | true | Full rendering + input |
| STOPPING | kStopping | false | xrEndSession called, empty frames submitted |
| LOSS_PENDING | kLost | false | Session lost, must recreate |
| EXITING | kDestroyed | — | Runtime shutting down |

### Window and Headless Mode States

Window and headless modes use only:
`kUninitialized → kReady → kRunning → kDestroyed`.
Window close event triggers `kRunning → kDestroyed`. Headless runs until
explicitly destroyed.

### API Behavior by State

| State | `beginFrame()` | `endFrame()` | `addLayer()` | `submit()` |
|---|---|---|---|---|
| kReady | Transitions to kRunning, returns first frame | — | Valid | No (no frame active) |
| kRunning | Returns FrameInfo normally | Composites + presents | Valid | Valid |
| kPaused | Returns FrameInfo with `should_render` per XR | Submits (may be empty) | Valid | Valid |
| kStopping | Returns FrameInfo with `should_render=false` | Submits empty frame | No | No |
| kLost / kDestroyed | Returns error / throws | No-op | No | No |

### XR Event Handling

OpenXR events are polled inside `beginFrame()`. Session state transitions
are driven by the runtime; VizSession updates its own state accordingly.
The application observes state via `getState()` and `FrameInfo::should_render`.

For `kLost`: the application is responsible for destroying and recreating
the VizSession. The existing camera_streamer uses `os.execv` for this;
TeleopViz should support clean recreation without process restart.

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

teleop_config = TeleopSessionConfig(app_name="teleop", pipeline=pipeline)
with TeleopSession(teleop_config) as teleop:
    while running:
        frame = viz_session.begin_frame()
        if frame.should_render:
            teleop.step()
            cam_layer.submit(camera_frame)  # CuPy array or VizBuffer
        viz_session.end_frame()

viz_session.destroy()
```

### Independent State Machines

TeleopSession and TeleopViz have **independent** state machines. They are
not coupled:

- **Different lifecycles:** VizSession tracks XR session state and Vulkan
  device state. TeleopSession tracks device connections, tracking availability,
  and retargeting pipeline state.
- **Different failure modes:** VizSession can go `kLost` (XR session lost)
  while TeleopSession continues fine (headless session is separate). A
  tracker can disconnect while VizSession keeps rendering stale frames.
- **Independent deployment:** VizSession can run without TeleopSession
  (camera viewing only). TeleopSession can run without VizSession (headless
  tracking).

The application loop is the coordination point. The application observes
both states and decides how to proceed.

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
| Input pixel format | RGBA8 only (kD32F for depth in Phase 2) | One format, no branching. Producers convert upstream. |
| Shaders | Precompiled SPIR-V at CMake time | 1-2 trivial shader pairs. No runtime compilation needed. |
| CUDA-Vulkan interop | Dual-mode: fire-and-forget copy or zero-copy write into TeleopViz-owned buffer | Covers both simple and performance-critical producers. |
| Rendering pipeline | Intermediate framebuffer → `vkCmdBlitImage` to XR swapchain | Swapchains use TRANSFER_DST only. Intermediate FB allows VkRenderPass. |
| Thread model | Single render thread, multi-threaded producers | Double-buffered per layer, CUDA-Vulkan semaphore sync, non-blocking. |
| Windowed mode | 2D tiling (no 3D perspective), mono only | Simple dev/debug view. SBS stereo as config option for XR debugging. |
| Display modes | kXR, kWindow, kHeadless | kHeadless enables GPU integration testing in CI without display. |
| OpenXR extensions | `COMPOSITION_LAYER_DEPTH`, `VULKAN_ENABLE2`, `CONVERT_TIMESPEC_TIME` | Matches HoloHub. |
| Vulkan device extensions | `EXTERNAL_MEMORY`, `EXTERNAL_MEMORY_FD` | Required for CUDA interop. |
| Session state machine | State machine with XR session state mapping (see Session State Machine section above) | Robust handling of XR session transitions, errors, focus changes. |

### Size Estimate

Based on analysis of reference implementations:

| Reference | Lines |
|-----------|-------|
| HoloHub XR operators (session, swapchain, composition, frame ops) | ~1,600 |
| XrPlaneRendererOp + CameraPlane (IsaacTeleop camera_streamer) | ~1,150 |
| CloudXR examples common (VK + OXR bootstrap, no rendering) | ~2,100 |

TeleopViz Phase 1 adds windowed mode, CUDA dual-mode interop, layer
abstraction, state machine, and Python bindings. Estimated **~3,000-3,500
lines** of C++ plus ~100 lines GLSL and ~150 lines CMake.

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

## Python Bindings

Python bindings via pybind11, exposed as `isaacteleop.viz`.

**`submit` accepts:**
- A `VizBuffer` (explicit width/height/format/pointer)
- Any object with `__cuda_array_interface__` (CuPy arrays, PyTorch CUDA
  tensors) — the binding extracts pointer, shape, and dtype, constructs
  a `VizBuffer` internally.

**`VizBuffer` in Python:** exposes `data_ptr` (int), `width`, `height`,
`format`, `pitch`, and `__cuda_array_interface__` (so CuPy can wrap it
zero-copy: `cupy.asarray(buf)`).

**GIL handling:** `beginFrame()` releases the GIL during blocking portions
(`xrWaitFrame` in XR mode, vsync wait in window mode). All other APIs hold
the GIL (they are fast, non-blocking operations). `endFrame()` holds the
GIL — GPU submission is non-blocking from the CPU's perspective.

**Error mapping:** Vulkan/OpenXR errors map to Python exceptions
(`RuntimeError` with descriptive message). Session state `kLost` raises
`VizSessionLostError` (subclass of `RuntimeError`) so applications can
catch and recreate.

**cudaStream_t passing:** Accepted as `int` (raw stream handle). Default
stream (`0`) is used if not provided.

---

## Testing

### Display Modes for Testing

| Mode | VkDevice | Swapchain | Frame timing | Present | Use |
|------|----------|-----------|-------------|---------|-----|
| kXR | XR-negotiated | XrSwapchain | xrWaitFrame | xrEndFrame | Manual XR testing |
| kWindow | Standalone | GLFW surface | vsync | glfwSwapBuffers | Development |
| kHeadless | Standalone | None | Free-running | readback() only | CI, integration tests |

kHeadless is the simplest mode: Vulkan device + offscreen framebuffer, no
GLFW, no OpenXR, no swapchain, no display server. `endFrame()` composites
into the intermediate framebuffer but does not present. `readback()` returns
the composited frame as a `VizBuffer` (CUDA device pointer) for pixel-level
verification.

### Test Structure

Follows IsaacTeleop conventions: tests in a sibling `*_tests/` directory
under `src/core/`, C++ with Catch2 v3, Python with pytest + uv, gated by
`BUILD_TESTING`.

```
src/core/
├── viz/                       # Module source (not tests)
└── viz_tests/
    ├── CMakeLists.txt         # add_subdirectory(cpp), add_subdirectory(python)
    ├── cpp/
    │   ├── CMakeLists.txt     # viz_tests executable, catch_discover_tests
    │   ├── test_state_machine.cpp
    │   ├── test_layer_mgmt.cpp
    │   ├── test_placement.cpp
    │   ├── test_viz_buffer.cpp
    │   ├── test_vk_context.cpp      # GPU required
    │   ├── test_cuda_interop.cpp    # GPU required
    │   └── test_quad_render.cpp     # GPU required (kHeadless + readback)
    └── python/
        ├── CMakeLists.txt     # add_test with uv run pytest
        ├── pyproject.toml     # [tool.pytest.ini_options]
        ├── test_viz_session.py
        ├── test_quad_layer.py
        └── test_headless_render.py  # GPU required
```

**C++ tests (Catch2):** `TEST_CASE` / `SECTION` / `CHECK` pattern matching
existing `schema_tests` and `mcap_tests`. Linked against `viz_core` +
`Catch2::Catch2WithMain`.

**Python tests (pytest):** Import from `isaacteleop.viz` namespace.
`PYTHONPATH` set to build's `python_package/` tree by CMake.

**GPU tests:** Tests requiring a GPU (Vulkan context, CUDA interop,
headless rendering) are marked in docstrings. kHeadless + `readback()`
pattern for pixel verification:

```python
def test_quad_render():
    """Integration test — requires GPU."""
    session = viz.VizSession.create(viz.Config(
        mode=viz.DisplayMode.HEADLESS, window_width=256, window_height=256))
    layer = session.add_quad_layer(name="test", ...)
    frame = session.begin_frame()
    layer.submit(test_image)
    session.end_frame()
    result = session.readback()
    assert pixels_match(result, expected)
```

**XR tests:** Manual testing with CloudXR + headset. Not automated in
Phase 1.

---

## Build and Dependencies

Self-contained. Dependencies fetched via CMake FetchContent.

**Required:** Vulkan >= 1.2, CUDA >= 12.0, GLM, pybind11, GLFW.
**Optional:** OpenXR SDK (`BUILD_XR=ON`), CloudXR runtime (runtime only),
nvblox_renderer (examples only).

```cmake
option(BUILD_VIZ "Build TeleopViz" ON)
if(BUILD_VIZ)
    add_subdirectory(src/viz)
    if(BUILD_TESTING)
        add_subdirectory(src/viz_tests)
    endif()
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

## Resolved Questions

1. **CloudXR dual-session**: Confirmed — one headless + one graphics-bound
   session works. Proceed with Option A. Pivot to Option B if issues arise.

2. **XR swapchain usage**: Use intermediate framebuffer → copy to swapchain
   (same as HoloHub XR pattern). Simpler, proven. Optimize later if needed.

3. **Stereo layout**: SBS (side-by-side) for now. VK_KHR_multiview deferred
   as a future optimization behind a config flag.

4. **OXR module changes for unified session**: Not needed for Phase 1
   (Option A). Revisit when migrating to Option B.

---

## Implementation Phases

### Phase 1 — TeleopViz Infrastructure (current)

Build the core compositor module with C++ and Python APIs sufficient to
replace Holoscan in the camera streaming stack. Deliverables:

**Vulkan infrastructure (`core/`):**
- `vk_context` — instance/device creation (standalone + XR-negotiated),
  external memory extensions
- `cuda_texture` — dual-mode CUDA-Vulkan interop (fire-and-forget +
  zero-copy write), semaphore sync, double-buffered
- `render_target` — color + depth framebuffer (XR swapchain or GLFW window)
- `frame_sync` — per-frame fences, semaphores, front/back buffer swap

**Session and compositor:**
- `VizSession` — lifecycle, frame loop (`beginFrame`/`endFrame`), layer
  registry, display modes (kXR, kWindow, kHeadless), session state machine
- `VizCompositor` — single render pass compositing all layers into stereo
  SBS framebuffer, `vkCmdBlitImage` to XR swapchain or present to window

**Core types:**
- `VizBuffer` — non-owning GPU image reference (data, width, height,
  format, pitch). Used by all layer submission APIs.
- `PixelFormat` — `kRGBA8` (Phase 1), `kD32F` (Phase 2)

**Layer types (push model, both submission modes):**
- `QuadLayer` — 2D image in 3D space, `submit(VizBuffer)` +
  `acquire`/`release`, placement modes (world/head/lazy/custom-locked),
  `LazyLockConfig`, stale content detection
- `LayerBase` — extensible abstract base with virtual `record()`. Custom
  layers via `addLayer()`. Built-in types in Phase 2: ProjectionLayer,
  OverlayLayer.

**Shaders:**
- `textured_quad.vert/frag` — quad rendering with model-view-projection

**Python bindings (`isaacteleop.viz`):**
- pybind11 wrappers for VizSession, VizBuffer, QuadLayer, FrameInfo,
  Config, DisplayMode, PixelFormat, SessionState
- `submit` accepts VizBuffer or `__cuda_array_interface__` objects (CuPy)
- VizBuffer exposes `__cuda_array_interface__` for zero-copy CuPy wrapping
- GIL release during `beginFrame` blocking

**Build integration:**
- CMakeLists.txt under `src/viz/`, wired into root build
- FetchContent for GLFW, GLM, pybind11
- Optional OpenXR SDK (`BUILD_XR=ON`)

**Testing:**
- Unit tests: state machine, layer management, placement math (no GPU)
- Integration tests: kHeadless + readback for pixel-level verification (GPU CI)
- Manual XR testing with CloudXR + headset

**Validation:**
- Camera plane streaming example replacing the Holoscan camera_streamer

**Out of scope for Phase 1:**
- ProjectionLayer (push and pull models)
- OverlayLayer (screen-space HUD)
- Pull-model render callback API
- nvblox_renderer integration
- Performance optimizations (multiview, direct swapchain render, XR quad
  layers)

### Phase 2 — Remaining Layers + External Renderer Integration (future)

Add ProjectionLayer (push + pull models) and OverlayLayer. Integrate
nvblox_renderer via pull-model zero-copy VkCommandBuffer callback.
Demonstrate combined 2D camera planes + 3D reconstruction + HUD in XR.
Add kHeadless display mode if needed for testing/CI.

### Phase 3 — Optimization and Polish (future)

Profile and optimize. Candidates: VK_KHR_multiview, direct swapchain
rendering (eliminate intermediate copy), XR quad layers for head-locked
overlays (runtime reprojection), adaptive quality, Option B unified
session migration.
