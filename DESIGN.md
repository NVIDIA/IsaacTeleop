# Televiz — Teleop Visualization Renderer

**Author:** Farbod Motlagh
**Status:** Draft
**Created:** April 2026

---

## Overview

Televiz (`isaacteleop.viz`) is a lightweight C++ compositor module for Isaac
Teleop that renders 2D sensor feeds and 3D reconstruction content into XR or
windowed displays. It replaces the Holoscan-based camera streaming app with a
self-contained Vulkan compositor that integrates directly with Isaac Teleop's
device tracking and retargeting pipeline.

The current camera streaming solution pulls in the full Holoscan SDK, HoloHub
XR operators, GXF entity model, and HolovizOp. Televiz removes these
dependencies and provides a purpose-built module (~3,000–3,500 lines of C++)
covering 2D plane, RGBD projection, and combined rendering.

No third-party rendering library provides the combination of CUDA–Vulkan
interop, OpenXR swapchain management, and simple GPU-image submission APIs
that this module requires. Vulkan is the only viable graphics API (required
by OpenXR on NVIDIA, by CUDA interop, and by nvblox_renderer).

### Hello, Televiz

```python
import isaacteleop.viz as viz

session = viz.VizSession.create(viz.Config(mode=viz.DisplayMode.XR))
cam = session.add_layer(viz.QuadLayer.Config(
    name="front_cam",
    width_meters=1.0,
    height_meters=0.5625,
    placement=viz.PlacementMode.LAZY_LOCKED,
))

while running:
    cam.submit(camera_frame)   # CuPy array or VizBuffer
    session.render()           # wait + composite + present
```

## Goals

- C++ core with Python bindings (`isaacteleop.viz`) for compositing 2D
  images and RGBD content into XR and windowed displays.
- Self-contained Vulkan infrastructure — no shared code dependency on
  nvblox_renderer, Holoscan, or HoloHub.
- Zero-copy integration with external renderers via Vulkan render targets.
- Expose XR runtime info (resolution, FOV, frame timing, view poses) to
  content producers.
- Reference examples: multi-camera plane streaming and 3D reconstruction
  visualization.

## Non-Goals

- Camera capture and network streaming (GStreamer, StreamSDK, V4L2 remain
  separate — Televiz consumes frames, not produces them).
- Retargeting, device I/O, or teleop session management (remain in Isaac
  Teleop Core).
- General-purpose rendering engine (no lighting, shadows, PBR, scene
  graphs). Complex 3D content is rendered by external engines and
  submitted as a layer.

### Coordinate Conventions

Televiz uses **OpenXR stage space**: right-handed, Y-up, meters for
distance, radians for angles. Poses are `position (x,y,z)` +
`orientation (x,y,z,w)` quaternions. Robotics applications working in
ROS/TF frames should convert at the application layer (Televiz does not
bridge to TF).

---

## Architecture

Televiz sits between content producers (cameras, reconstruction engines,
any renderer) and display targets (OpenXR devices, desktop windows,
offscreen). It is a compositor — it assembles content from multiple
sources into a final frame.

The module lives under `src/viz/` in the IsaacTeleop tree as
`isaacteleop.viz`. It repackages the same OpenXR + Vulkan + CUDA interop
patterns used by HoloHub's XR operators into a standalone library with a
frame-loop API — no Holoscan operator graph, no GXF, no external
framework.

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
    │   │   │   ├── viz_types.hpp           # Fov, Pose3D, Resolution
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
    │   │   ├── viz_session.cpp
    │   │   ├── viz_compositor.cpp
    │   │   ├── quad_layer.cpp
    │   │   ├── vk_context.cpp
    │   │   ├── cuda_texture.cpp
    │   │   ├── render_target.cpp
    │   │   └── frame_sync.cpp
    │   ├── shaders/
    │   │   ├── textured_quad.vert
    │   │   └── textured_quad.frag
    │   └── python/
    │       ├── CMakeLists.txt              # pybind11 → _viz
    │       ├── viz_bindings.cpp
    │       └── viz_init.py
    └── viz_tests/                          # Sibling test dir (convention)
        ├── CMakeLists.txt
        ├── cpp/
        │   ├── CMakeLists.txt              # Catch2 v3, catch_discover_tests
        │   └── test_*.cpp
        └── python/
            ├── CMakeLists.txt              # add_test with uv run pytest
            ├── pyproject.toml
            └── test_*.py
```

### Why an intermediate framebuffer?

XR swapchain images (from CloudXR / the OpenXR runtime) are typically
created with only `VK_IMAGE_USAGE_TRANSFER_DST_BIT` — they do **not**
support `VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT`, so a `VkRenderPass`
cannot target them directly. Same constraint HoloHub's XR operators work
under.

The render pipeline is therefore two steps:

1. **Render pass** into Televiz's own intermediate framebuffer (a
   `VkImage` created with `COLOR_ATTACHMENT_BIT | TRANSFER_SRC_BIT`). All
   layer `record()` calls happen here.
2. **Blit** from the intermediate framebuffer to the swapchain via
   `vkCmdBlitImage` — a Vulkan transfer command, no shader, no
   pipeline, no descriptor sets. Handles format conversion and scaling.

In window mode, the same pattern applies (GLFW surface swapchain). In
offscreen mode, step 2 is skipped — `readback()` reads the intermediate
framebuffer directly.

### Vulkan Infrastructure

Televiz owns its own Vulkan context and CUDA interop rather than sharing
with nvblox_renderer. Integration with external renderers happens at the
Vulkan API contract level (`VkCommandBuffer`, `VkRenderPass`), not
through shared code.

| Component | Purpose |
|-----------|---------|
| `vk_context` | Instance/device creation: standalone (enumerate GPU) or XR-negotiated (`xrCreateVulkanDeviceKHR`). `VK_KHR_external_memory_fd` extensions. |
| `cuda_texture` | Dual-mode CUDA-Vulkan interop buffer (see Content Submission). VkImage backed by external memory with CUDA-mapped view. Semaphore export/import for GPU sync. |
| `render_target` | Intermediate + swapchain VkImage pairs, VkRenderPass, VkFramebuffer. XR path wraps XrSwapchain; window wraps GLFW. |
| `frame_sync` | Per-frame fences, submit semaphores, front/back swap. |
| Fixed pipeline | Hardcoded `VkPipeline` for textured quad (Phase 1). Precompiled SPIR-V. |

---

## Core Types

Public types, defined in `viz_types.hpp`:

```cpp
struct Resolution {
    uint32_t width;
    uint32_t height;
};

struct Pose3D {
    struct { float x, y, z; } position;            // meters
    struct { float x, y, z, w; } orientation;      // quaternion
};

struct Fov {
    float angle_left;     // radians from forward axis, negative = left
    float angle_right;    // radians
    float angle_up;       // radians
    float angle_down;     // radians
};
```

OpenXR types (`XrPosef`, `XrFovf`) are converted to these at the Televiz
boundary. Consumers never see OpenXR headers.

### VizBuffer

A lightweight, non-owning reference to a 2D pixel buffer on GPU:

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
memory. For `acquire`/`release`, the layer owns the interop buffer;
`VizBuffer` is a view into it.

In Python, `VizBuffer` exposes `__cuda_array_interface__` so CuPy can
wrap it zero-copy: `cupy.asarray(buf)`.

For RGBD content (Phase 2):

```cpp
struct VizBufferPair {            // Phase 2, ProjectionLayer
    VizBuffer color;              // kRGBA8
    VizBuffer depth;              // kD32F
};
```

---

## VizSession API

The central object. Manages the Vulkan context, OpenXR session (XR mode),
display target, and layer registry. Session lifecycle follows the state
machine below.

```cpp
enum class DisplayMode {
    kXR,           // OpenXR graphics-bound session
    kWindow,       // GLFW windowed mono (tiling layout)
    kOffscreen,    // No display; readback() only
};

class VizSession {
public:
    struct Config {
        DisplayMode mode;
        uint32_t window_width;      // Window and offscreen modes
        uint32_t window_height;
        std::string app_name = "televiz";   // Used by OpenXR
    };

    // Creates session with its own Vulkan context + display target.
    static std::unique_ptr<VizSession> create(const Config& config);
    void destroy();

    // Layer management (insertion-order rendering — first added renders first).
    //
    // Single templated API: constructs a layer of type L in-place with
    // forwarded args and registers it. Works for built-in types (QuadLayer,
    // ProjectionLayer, OverlayLayer) and any user-defined LayerBase subclass.
    //
    //   auto* cam  = session.addLayer<QuadLayer>(QuadLayer::Config{...});
    //   auto* mesh = session.addLayer<MyMeshLayer>(my_renderer, ...);
    template<typename L, typename... Args>
    L* addLayer(Args&&... args);

    void removeLayer(LayerBase* layer);

    // Frame loop — two API levels:
    //
    // 1. Convenience (recommended for most users):
    //    Wait + composite + present in one call. Returns FrameInfo for the
    //    frame just rendered (for logging/diagnostics). If should_render is
    //    false, the GPU render pass is skipped internally; producers'
    //    submit/acquire work continues normally.
    FrameInfo render();
    //
    // 2. Explicit control (advanced — when the app needs FrameInfo before
    //    submitting, or wants to inject work between wait and present):
    //    beginFrame: XR: xrWaitFrame (blocking), xrBeginFrame, xrLocateViews.
    //                Window: vsync wait. Offscreen: immediate return.
    //    endFrame:   composite + present.
    //    Python bindings release the GIL during blocking portions.
    FrameInfo beginFrame();
    void endFrame();

    // Session state.
    SessionState getState() const;

    // Runtime queries.
    Resolution getRecommendedResolution() const;
    FrameTimingStats getFrameTimingStats() const;

    // Readback (kOffscreen only). Returns the last composited frame as
    // a VizBuffer (CUDA device pointer). Valid until next endFrame().
    VizBuffer readback(cudaStream_t stream = 0);

    // Handle access for external renderer integration and session sharing.
    VkDevice getVkDevice() const;
    VkPhysicalDevice getVkPhysicalDevice() const;
    uint32_t getVkQueueFamilyIndex() const;
    VkRenderPass getRenderPass() const;          // For custom layer pipelines
    OpenXRSessionHandles getOxrHandles() const;  // XR mode only
};
```

### FrameInfo

Returned by `beginFrame()`. Per-frame state for content producers:

```cpp
struct ViewInfo {
    float view_matrix[16];          // Column-major 4x4
    float projection_matrix[16];
    Fov fov;
    Pose3D pose;
};

struct FrameInfo {
    uint64_t frame_index;
    int64_t predicted_display_time; // XR time (ns). 0 in window/offscreen.
    float delta_time;               // Seconds since last frame
    bool should_render;
    std::vector<ViewInfo> views;    // 2 in XR (stereo); 1 otherwise
    Resolution resolution;
};

struct FrameTimingStats {
    float render_fps;
    float target_fps;
    uint64_t missed_frames;
    float avg_frame_time_ms;
    float gpu_time_ms;
    uint32_t stale_layers;          // Layers that missed stale_timeout
};
```

**Time spaces:** `predicted_display_time` is OpenXR monotonic time in ns.
`delta_time` is CPU wall-clock seconds between frames — usable without
any XR knowledge. Most consumers should use `delta_time`.

In window and offscreen modes, `FrameInfo` has one `ViewInfo` with
identity matrices. `views[0].fov` is undefined in these modes.

---

## Layer System

### LayerBase

All layers inherit from `LayerBase`, which defines the interface the
compositor calls during the render pass. Developers can subclass
`LayerBase` to implement custom rendering logic — they are not limited to
the built-in layer types.

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
    bool isVisible() const;
    void setVisible(bool visible);
};
```

**Custom layers:** Create a `VkPipeline` compatible with Televiz's render
pass (via `VizSession::getRenderPass()`), subclass `LayerBase`, implement
`record()`, register via `VizSession::addLayer()`. The compositor
iterates layers **in insertion order** and calls `record()` for each
visible layer. This is the pull model, generalized — any Vulkan drawing
code works as long as it's render-pass-compatible.

### QuadLayer

A 2D image placed in 3D space. The most common layer type for camera
feeds. Built-in textured-quad rendering + CUDA interop.

```cpp
enum class PlacementMode {
    kWorldLocked,   // Fixed pose in stage space
    kHeadLocked,    // Follows headset exactly (HUD-style)
    kLazyLocked,    // Follows headset with damping
    kCustom,        // Application-provided callback
};

struct LazyLockConfig {
    float look_away_angle = 45.0f;      // Degrees; reposition when user looks away
    float reposition_distance = 0.5f;   // Meters; reposition when user walks away
    float reposition_delay = 0.5f;      // Seconds before repositioning starts
    float transition_duration = 0.3f;   // Seconds for smooth reposition
};

using PlacementCallback = std::function<Pose3D(
    const Pose3D& head_pose, float delta_time)>;

class QuadLayer : public LayerBase {
public:
    struct Config {
        std::string name;
        float width_meters;
        float height_meters;
        PlacementMode placement = PlacementMode::kWorldLocked;
        LazyLockConfig lazy_lock;            // Used when placement == kLazyLocked
        PlacementCallback placement_callback; // REQUIRED when placement == kCustom
        float stale_timeout = 2.0f;          // Seconds before showing placeholder
    };

    // Mode A: fire-and-forget. Copies from the VizBuffer into the layer's
    // interop back buffer. Non-blocking (enqueues on stream). Reallocates
    // internal buffer if dimensions change.
    void submit(const VizBuffer& image, cudaStream_t stream = 0);

    // Mode B: zero-copy write. Returns a VizBuffer pointing to the layer's
    // interop back buffer. Allocates on first call; reuses when dimensions
    // match; reallocates when they change. Producer writes into buf.data,
    // then calls release().
    VizBuffer acquire(uint32_t width, uint32_t height,
                      PixelFormat format = PixelFormat::kRGBA8);
    void release(cudaStream_t stream = 0);

    void setPose(const Pose3D& pose);
    void setSize(float width_meters, float height_meters);

    // LayerBase override (internal).
    void record(VkCommandBuffer cmd, const std::vector<ViewInfo>& views,
                const RenderTarget& target) override;
};
```

**Placement modes:**

- `kWorldLocked` — fixed pose in stage space (set via `setPose`).
- `kHeadLocked` — pose tracks headset every frame.
- `kLazyLocked` — follows headset with configurable damping
  (`LazyLockConfig`). Parameters match the existing camera_streamer UX.
- `kCustom` — application provides `Config::placement_callback`.
  Required at `addLayer` time; invalid config throws.

In **window and offscreen** modes, placement is ignored. Layers tile in
insertion order as a row-major grid sized to fit the display resolution,
preserving each layer's aspect ratio (from `width_meters / height_meters`).

**Stale content:** If no new image arrives within `stale_timeout`, a
solid-color placeholder is displayed and `FrameTimingStats::stale_layers`
increments.

**Pixel format:** `kRGBA8` only in Phase 1. One format, no branching in
shaders. Producers convert upstream (trivial CUDA swizzle). The existing
decode pipeline already produces RGB; pad to RGBA before submitting.

Use cases: camera feeds, depth-colorized images, sensor visualizations.

### ProjectionLayer (Phase 2)

A full stereo RGBD view. Supports push (color + depth VizBuffers) and
pull (custom `record()` subclass).

```cpp
class ProjectionLayer : public LayerBase {
public:
    struct Config {
        std::string name;
    };

    // Push: submit pre-rendered color + depth.
    void submit(const VizBuffer& color, const VizBuffer& depth,
                cudaStream_t stream = 0);

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
    };

    void submit(const VizBuffer& image, cudaStream_t stream = 0);
    void setRect(float x, float y, float width, float height);

    void record(VkCommandBuffer cmd, const std::vector<ViewInfo>& views,
                const RenderTarget& target) override;
};
```

Use cases: telemetry HUD, connection status, battery indicators.

---

## Content Submission

### Two Submission Modes

| | Mode A (`submit`) | Mode B (`acquire` / `release`) |
|---|---|---|
| **Copy** | One `cudaMemcpyAsync` per frame | Zero copy |
| **Ownership** | Producer owns source buffer | Televiz owns buffer, producer borrows |
| **Simplicity** | Simplest — any CUDA pointer / CuPy array | Requires producer to write into provided buffer |
| **Use case** | External sources, CuPy, remote decode | Tight integration, NVDEC direct output |

Both modes are valid in states `kReady` and `kRunning` (submitting before
the first `beginFrame` is fine — content appears in the first rendered
frame).

### Double Buffering and Synchronization

Each layer has two interop buffers (front + back). Producers write to the
back buffer at their own rate. The compositor reads the front buffer.

Sync flow for Mode A:

1. `submit` enqueues `cudaMemcpyAsync` on the producer's stream.
2. The stream signals an exported semaphore when the copy completes.
3. At `endFrame`, the compositor checks if the semaphore has fired.
4. If yes: atomically swap front/back. The Vulkan submit waits on the
   imported semaphore before sampling the texture.
5. If no (producer hasn't finished): render the old front buffer
   (last frame).

Mode B is identical except step 1 is the producer's own writes.

**Behavior:**

- Producer faster than display → only the latest frame is rendered
  (back buffer overwritten).
- Producer slower than display → last completed frame re-displayed.
- Neither side blocks.

**Dimension changes:** Both `submit` and `acquire` reallocate the
underlying interop buffer if `width`/`height`/`format` differ from the
current buffer. Allocation is not free — avoid changing dimensions every
frame.

**Timing with `beginFrame`/`endFrame`:** `acquire`/`release` and
`beginFrame`/`endFrame` are independent lifecycles. The compositor picks
up whatever is latest at `endFrame`. Multi-threaded producers can write
on a separate thread at their own rate.

### Pull Model = Custom Layers

The pull model is expressed through `LayerBase::record()`. Any layer
(built-in or custom) records Vulkan draw commands during the render
pass. Custom layers subclass `LayerBase` — that IS the pull model. No
separate callback API is needed or provided.

External renderers (e.g. nvblox_renderer) create pipelines compatible
with Televiz's render pass (`RenderTarget::render_pass`: RGBA8_SRGB +
D32_SFLOAT, 1 sample, 1 subpass), then record draw commands into the
provided `VkCommandBuffer`. No buffer copies, no shared Vulkan context.

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

---

## Session State Machine

```cpp
enum class SessionState {
    kUninitialized,  // Before create()
    kReady,          // Vulkan + display initialized. Layers and content can be added.
    kRunning,        // Frame loop active.
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
| VISIBLE | kRunning | true | Rendering, but app is not focused |
| FOCUSED | kRunning | true | Full rendering + input |
| STOPPING | kStopping | false | xrEndSession called, empty frames |
| LOSS_PENDING | kLost | false | Session lost, must recreate |
| EXITING | kDestroyed | — | Runtime shutting down |

### Window and Offscreen Mode States

Simplified subset: `kUninitialized → kReady → kRunning → kDestroyed`.
Window close event triggers `kRunning → kDestroyed`. Offscreen runs until
explicit `destroy()`.

### API Behavior by State

| State | `render()` / `beginFrame()` | `endFrame()` | `addLayer()` | `submit()` |
|---|---|---|---|---|
| kReady | Transitions to kRunning, returns first frame | — | Valid | Valid |
| kRunning | Returns FrameInfo normally | Composites + presents | Valid | Valid |
| kStopping | Returns `should_render=false` | Submits empty frame | No | No |
| kLost / kDestroyed | Throws `VizSessionLostError` / `RuntimeError` | No-op | No | No |

### XR Event Handling

OpenXR events are polled inside `beginFrame()`. Session state transitions
are driven by the runtime; VizSession updates its own state accordingly.
The application observes state via `getState()` and
`FrameInfo::should_render`.

For `kLost`: the application destroys and recreates the VizSession.
Televiz supports clean recreation in-process — no `os.execv` restart
needed.

---

## IsaacTeleop Integration

### Package Name

`isaacteleop.viz` — follows the pattern of `isaacteleop.oxr`,
`isaacteleop.mcap`, `isaacteleop.schema`.

### Session Ownership (Option A now, Option B future)

IsaacTeleop's existing `OpenXRSession` creates a **headless** OpenXR
session for device tracking (hand tracking, headset pose) — no Vulkan
binding, cannot render. Televiz needs a **graphics-bound** XR session.

| Option | Description | Status |
|--------|-------------|--------|
| **A: Separate sessions** | Televiz creates its own graphics session. OXR keeps its headless session. | Phase 1 — confirmed working with CloudXR. |
| **B: Televiz owns, trackers attach** | Televiz creates session. Trackers attach via `oxr_handles`. | Future — single CloudXR connection. |
| **C: Extended OXR module** | OXR creates graphics-bound session, passes handles to Televiz. | Alternative future. |

Option B uses `TeleopSessionConfig`'s existing `oxr_handles` field.
Televiz exposes `VizSession::getOxrHandles()` for this purpose already —
no TeleopSession changes needed to migrate:

```python
# Option A (Phase 1): separate sessions
viz_session = isaacteleop.viz.VizSession.create(viz_config)
teleop_config = TeleopSessionConfig(pipeline=pipeline)

# Option B (future): unified session
viz_session = isaacteleop.viz.VizSession.create(viz_config)
teleop_config = TeleopSessionConfig(
    pipeline=pipeline,
    oxr_handles=viz_session.get_oxr_handles(),  # trackers share viz session
)
```

### Application-Level Integration

Televiz integrates alongside `TeleopSession`, not inside it. Both run in
the application loop:

```python
import isaacteleop.viz as viz
from isaacteleop import TeleopSession, TeleopSessionConfig

viz_session = viz.VizSession.create(viz.Config(mode=viz.DisplayMode.XR))
cam_layer = viz_session.add_layer(viz.QuadLayer.Config(
    name="front_cam", width_meters=1.0, height_meters=0.5625,
    placement=viz.PlacementMode.LAZY_LOCKED))

teleop_config = TeleopSessionConfig(app_name="teleop", pipeline=pipeline)
with TeleopSession(teleop_config) as teleop:
    while running:
        teleop.step()
        cam_layer.submit(camera_frame)   # CuPy array or VizBuffer
        viz_session.render()

viz_session.destroy()
```

The `render()` call internally checks `should_render` and skips the GPU
render pass if the runtime says the frame won't be visible. Producers'
`submit`/`acquire` writes continue regardless — they're just stored in
the back buffer until rendering resumes.

If the application needs to react to `should_render` itself (e.g., to skip
expensive video decode), use the explicit form:

```python
while running:
    frame = viz_session.begin_frame()
    if frame.should_render:
        teleop.step()
        cam_layer.submit(decode_camera())  # skip decode when not visible
    viz_session.end_frame()
```

### Independent State Machines

TeleopSession and VizSession are **not** coupled:

- **Different lifecycles:** VizSession tracks XR session + Vulkan device
  state. TeleopSession tracks device connections and retargeting.
- **Different failure modes:** VizSession can go `kLost` (XR session
  lost) while TeleopSession continues; a tracker can disconnect while
  VizSession keeps rendering.
- **Independent deployment:** Either can run without the other.

The application loop is the coordination point.

---

## Rendering Strategy

All layers composite into a single stereo framebuffer per frame,
submitted as one `XrCompositionLayerProjection` with depth. Per frame:

```
xrWaitFrame → xrBeginFrame → xrLocateViews → acquire swapchain →
  begin render pass →
    for each layer in insertion order:
      if layer.isVisible(): layer.record(cmd, views, target)
  end render pass →
  vkCmdBlitImage intermediate → swapchain image →
xrEndFrame
```

In Phase 2, ProjectionLayer (pull model subclass) typically renders first
(writes depth), followed by QuadLayers, then OverlayLayers in screen
space. Insertion order determines sequencing.

**Why single render pass rather than OpenXR quad layers?** Quad layers
limit layer count (~16), prevent depth compositing between layers, and
can't embed 2D planes in 3D space. Single render pass is the only approach
that combines 2D planes with 3D content at correct depth. Quad layers
remain a future optimization for head-locked overlays that benefit from
runtime reprojection.

---

## XR Runtime Information

Content producers need resolution, FOV, and timing. Televiz exposes:

- **Session-level (stable):** recommended per-eye resolution, view
  count, display refresh rate via `getRecommendedResolution()`.
- **Per-frame (`FrameInfo`):** per-eye pose + FOV + view + projection
  matrices, `predicted_display_time`, `should_render`, `delta_time`.
- **Performance stats (polled):** `getFrameTimingStats()` — render FPS,
  target FPS, missed frames, frame times, stale layer count.

---

## Python Bindings

Python bindings via pybind11, exposed as `isaacteleop.viz`.

### Python API Surface

Snake-case mirror of the C++ API. Equivalent signatures:

```python
# Session
session = viz.VizSession.create(config)
session.destroy()

# Layers — single method. pybind11 dispatches by argument type:
#   pass a Layer::Config  → constructs and registers the corresponding Layer
#   pass a Layer instance → registers a pre-constructed custom Layer
layer   = session.add_layer(viz.QuadLayer.Config(...))   # built-in
layer   = session.add_layer(my_custom_layer_instance)    # custom
session.remove_layer(layer)

# Frame loop — recommended (one call per frame)
frame   = session.render()          # wait + composite + present; releases GIL

# Or explicit (advanced — when you need FrameInfo before submitting)
frame   = session.begin_frame()     # releases GIL during blocking wait
session.end_frame()

# Queries
state   = session.get_state()
res     = session.get_recommended_resolution()
stats   = session.get_frame_timing_stats()
buf     = session.readback()        # kOffscreen only

# QuadLayer
layer.submit(cupy_array_or_viz_buffer, stream=0)
viz_buf = layer.acquire(1920, 1080, viz.PixelFormat.RGBA8)
# ... write into viz_buf ...
layer.release(stream=0)

layer.set_pose(pose3d)
layer.set_size(1.0, 0.5625)
layer.set_visible(True)
```

### Enum naming

C++ `kRGBA8` → Python `viz.PixelFormat.RGBA8` (no `k` prefix).
C++ `kXR` → Python `viz.DisplayMode.XR`.

### CUDA data types

**`submit` accepts:**

- A `VizBuffer` (explicit width/height/format/pointer).
- Any object with `__cuda_array_interface__` (CuPy arrays, PyTorch CUDA
  tensors). The binding extracts pointer, shape, and dtype; constructs
  a `VizBuffer` internally.

**`VizBuffer` in Python:** exposes `data_ptr` (int), `width`, `height`,
`format`, `pitch`, and `__cuda_array_interface__` (so CuPy can wrap it
zero-copy: `cupy.asarray(buf)`).

**`cudaStream_t`:** accepted as `int` (raw stream handle). Default
stream (`0`) is used if omitted.

### GIL and errors

- `begin_frame()` releases the GIL during blocking wait (xrWaitFrame /
  vsync). All other APIs hold the GIL — they are fast, non-blocking.
- `end_frame()` holds the GIL; GPU submission is non-blocking from the
  CPU side.
- Vulkan/OpenXR errors map to Python exceptions (`RuntimeError` with
  descriptive message). Session state `kLost` raises `VizSessionLostError`
  (subclass of `RuntimeError`).

---

## Testing

### Display Modes for Testing

| Mode | VkDevice | Swapchain | Frame timing | Present | Use |
|------|----------|-----------|-------------|---------|-----|
| kXR | XR-negotiated | XrSwapchain | xrWaitFrame | xrEndFrame | Manual XR testing |
| kWindow | Standalone | GLFW surface | vsync | glfwSwapBuffers | Development |
| kOffscreen | Standalone | None | Free-running | readback() only | CI, integration tests |

kOffscreen is the simplest mode: Vulkan device + offscreen framebuffer,
no GLFW, no OpenXR, no swapchain, no display server. `endFrame()`
composites into the intermediate framebuffer but does not present.
`readback()` returns the composited frame as a `VizBuffer` for
pixel-level verification.

### Test Structure

Follows IsaacTeleop conventions: tests in a sibling `*_tests/` directory
under `src/`, C++ with Catch2 v3, Python with pytest + uv, gated by
`BUILD_TESTING`.

```
src/
├── viz/                       # Module source
└── viz_tests/
    ├── CMakeLists.txt
    ├── cpp/
    │   ├── CMakeLists.txt     # Catch2, catch_discover_tests
    │   ├── test_state_machine.cpp
    │   ├── test_layer_mgmt.cpp
    │   ├── test_placement.cpp
    │   ├── test_viz_buffer.cpp
    │   ├── test_vk_context.cpp      # GPU required
    │   ├── test_cuda_interop.cpp    # GPU required
    │   └── test_quad_render.cpp     # GPU required (kOffscreen + readback)
    └── python/
        ├── CMakeLists.txt     # add_test with uv run pytest
        ├── pyproject.toml     # [tool.pytest.ini_options]
        ├── test_viz_session.py
        ├── test_quad_layer.py
        └── test_offscreen_render.py # GPU required
```

**C++ tests (Catch2):** `TEST_CASE` / `SECTION` / `CHECK` pattern
matching existing `schema_tests` and `mcap_tests`. Linked against
`viz_core` + `Catch2::Catch2WithMain`.

**Python tests (pytest):** Import from `isaacteleop.viz` namespace.
`PYTHONPATH` set to build's `python_package/` tree by CMake.

**GPU tests:** require a GPU but no display. Marked in docstrings.
Pattern:

```python
def test_quad_render():
    """Integration test — requires GPU."""
    session = viz.VizSession.create(viz.Config(
        mode=viz.DisplayMode.OFFSCREEN, window_width=256, window_height=256))
    layer = session.add_layer(viz.QuadLayer.Config(
        name="test", width_meters=1.0, height_meters=1.0))
    layer.submit(test_image)
    session.render()
    result = session.readback()
    assert pixels_match(result, expected)
```

**XR tests:** Manual testing with CloudXR + headset. Not automated in
Phase 1.

---

## Build and Dependencies

Self-contained. Dependencies fetched via CMake FetchContent.

**Required:** Vulkan >= 1.2, CUDA >= 12.0, GLM, pybind11, GLFW.
**Optional:** OpenXR SDK (`BUILD_XR=ON`), CloudXR runtime (runtime
only), nvblox_renderer (examples only).

```cmake
option(BUILD_VIZ "Build Televiz" ON)
if(BUILD_VIZ)
    add_subdirectory(src/viz)
    if(BUILD_TESTING)
        add_subdirectory(src/viz_tests)
    endif()
endif()
```

---

## Examples

### `examples/viz/camera_planes/` — Phase 1

Replaces the Holoscan camera_streamer for 2D planes. Camera capture
(V4L2, OAK-D, ZED) and GStreamer RTP code reused from the existing
camera_streamer — extracted from Holoscan operators into standalone
modules. Televiz renders each feed as a QuadLayer. Supports local and
remote sources, XR and windowed display. YAML config for camera layout
and plane placement.

### `examples/viz/reconstruction_viz/` — Phase 2

nvblox_renderer integration. A custom `LayerBase` subclass wraps
`MeshVisualizer::render(cmd, view_proj, x, y, w, h)` — zero-copy, via
Televiz's render pass. Optional QuadLayers for raw camera feeds
alongside the reconstruction.

### Combined teleop visualization — Phase 2

Multi-camera QuadLayers + nvblox custom layer + telemetry OverlayLayers
+ IsaacTeleop session for hand tracking and retargeting visualization.

---

## Migration Path from Holoscan Camera Streamer

| Current (Holoscan) | Televiz Replacement |
|---|---|
| HolovizOp (monitor tiling) | VizSession(kWindow) + QuadLayer per camera |
| XrPlaneRendererOp (XR planes) | VizSession(kXR) + QuadLayer per camera |
| XrBeginFrameOp / XrEndFrameOp | VizSession.begin_frame() / end_frame() |
| XrSession (HoloHub resource) | VizSession |
| VideoStreamMonitorOp (timeout) | Built-in stale content detection per layer |
| FrameCombinerOp (async merge) | Built-in double buffering per layer |
| Holoscan EventBasedScheduler | Application main loop |
| GStreamer / NVENC/NVDEC ops | Reused as standalone C++/Python |

---

## Resolved Questions

1. **CloudXR dual-session:** Confirmed — one headless + one
   graphics-bound session works. Proceed with Option A.
2. **XR swapchain usage:** Intermediate framebuffer → `vkCmdBlitImage`
   to swapchain.
3. **Stereo layout:** SBS. `VK_KHR_multiview` deferred.
4. **OXR module changes for unified session:** Not needed for Phase 1.
5. **CUDA-Vulkan interop:** Dual-mode via `VizBuffer`
   (`submit` + `acquire`/`release`).
6. **Pixel format:** `kRGBA8` only (`kD32F` for depth in Phase 2).
7. **Windowed mode:** 2D tiling (insertion-order row-major grid).
8. **Offscreen mode:** Phase 1 for testing. `readback()` returns
   composited frame as VizBuffer.
9. **Layer ordering:** Insertion order (no explicit priority field).
10. **OpenXR types:** Hidden behind `Fov` / `Pose3D`; not in public API.
11. **XR types rename:** `kHeadless` → `kOffscreen` to avoid collision
    with IsaacTeleop's existing "headless OpenXR session" concept.

### Deferred (not in Phase 1)

- **Window SBS stereo (`window_stereo` config):** XR layout debug
  preview. Defer until someone actually needs it.
- **`setOpacity` on layers:** Producers can bake alpha into textures.
  Alpha compositing between layers is a niche feature.
- **Explicit layer priority:** Insertion order is sufficient for now.
- **`createWithXrSession` constructor:** Session injection path for
  hypothetical Option C. Televiz always creates its session; Option B
  migration uses `getOxrHandles()` which already exists.

---

## Implementation Phases

### Phase 1 — Televiz Infrastructure (current)

Build the core compositor module with C++ and Python APIs sufficient to
replace Holoscan in the camera streaming stack.

**Vulkan infrastructure:**

- `vk_context` — instance/device creation (standalone + XR-negotiated)
- `cuda_texture` — dual-mode CUDA-Vulkan interop, semaphore sync,
  double-buffered
- `render_target` — intermediate + swapchain framebuffer pairs
- `frame_sync` — per-frame fences, semaphores, front/back swap

**Session and compositor:**

- `VizSession` — lifecycle, frame loop (`render()` convenience +
  `beginFrame`/`endFrame` explicit), layer registry, display modes
  (kXR, kWindow, kOffscreen), state machine
- `VizCompositor` — single render pass, SBS stereo,
  `vkCmdBlitImage` to swapchain (or readback in offscreen)

**Core types:**

- `Resolution`, `Pose3D`, `Fov` (OpenXR-free public API)
- `VizBuffer`, `PixelFormat` (`kRGBA8`)
- `FrameInfo`, `ViewInfo`, `FrameTimingStats`, `SessionState`

**Layer types:**

- `LayerBase` — extensible abstract base with virtual `record()`.
  Custom layers via `addLayer()`.
- `QuadLayer` — 2D image in 3D space, `submit` / `acquire`+`release`,
  placement modes (world/head/lazy/custom), `LazyLockConfig`, stale
  detection. Callback required in Config when `placement == kCustom`.

**Shaders:**

- `textured_quad.vert/frag` — quad rendering with MVP

**Python bindings (`isaacteleop.viz`):**

- pybind11 wrappers for all public types, snake_case methods
- `submit` accepts VizBuffer or `__cuda_array_interface__` objects
- VizBuffer exposes `__cuda_array_interface__`
- GIL release during `begin_frame` blocking
- `VizSessionLostError` for `kLost` state

**Build:**

- CMakeLists under `src/viz/` and `src/viz_tests/`, wired into root
- FetchContent for GLFW, GLM, pybind11
- Optional OpenXR SDK (`BUILD_XR=ON`)

**Testing:**

- Unit tests: state machine, layer management, placement math (no GPU)
- Integration tests: kOffscreen + `readback()` for pixel verification (GPU CI)
- Manual XR testing with CloudXR + headset

**Validation:**

- Camera plane streaming example replacing the Holoscan camera_streamer

**Out of scope for Phase 1:**

- `ProjectionLayer`, `OverlayLayer`
- nvblox_renderer integration example
- Performance optimizations (multiview, direct swapchain render, XR quad
  layers)
- See also "Deferred" section above.

### Phase 2 — Remaining Layers + External Renderer Integration

- `ProjectionLayer` (push), `OverlayLayer`.
- nvblox_renderer integration via custom `LayerBase` subclass (zero-copy
  VkCommandBuffer).
- Combined 2D + 3D + HUD demo.

### Phase 3 — Optimization and Polish

- `VK_KHR_multiview` benchmark and config flag.
- Direct swapchain rendering if runtime allows `COLOR_ATTACHMENT`
  (eliminates intermediate framebuffer copy).
- XR quad layers for head-locked overlays (runtime reprojection).
- Adaptive quality.
- Option B unified-session migration (Televiz session shared with
  TeleopSession trackers via `oxr_handles`).
