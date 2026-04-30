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

### Code Style

Follows IsaacTeleop conventions throughout:

- **Namespace:** All Televiz symbols live in `namespace viz`.
  Internal helpers go in `viz::detail`.
- **Type names:** `PascalCase` (`VizSession`, `QuadLayer`, `VizBuffer`,
  `Pose3D`).
- **Method/function names:** `snake_case` (`begin_frame`, `add_layer`,
  `get_oxr_handles`, `set_pose`).
- **Variable / field names:** `snake_case` (`window_width`, `app_name`,
  `required_extensions`).
- **Private member names:** trailing underscore (`instance_`, `device_`,
  `layers_`).
- **Constants and enum values:** `kPascalCase` (`kRGBA8`, `kWorldLocked`,
  `kRunning`).
- **Format:** Allman braces, 120 columns, 4-space indent, left pointer
  alignment (`int* p`). Enforced by `clang-format` in CI.
- **License:** SPDX header on every new file:
  ```cpp
  // SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  // SPDX-License-Identifier: Apache-2.0
  ```
  (Use `#` for CMake / Python.)
- **Headers:** `#pragma once`. Includes use the nested-path convention
  reflecting the directory structure: `<viz/core/...>`,
  `<viz/layers/...>`, `<viz/session/...>`, `<viz/xr/...>`. The C++
  namespace `viz` is shared across all sub-modules. Library
  aliases drop the redundant `viz_` prefix: `viz::core`, `viz::layers`,
  `viz::session`, `viz::xr`.
- **Python:** snake_case throughout. The Python API mirrors C++ method
  names exactly (no naming gap between languages). Ruff enforces lint
  and format.
- **Testing:** Catch2 v3 with tags (`[unit]`, `[gpu]`, `[xr]`). pytest
  + uv for Python.

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

Televiz mirrors `src/core/`: it's a peer container of sub-modules, each
with its own static library and a sibling `<sub-module>_tests/` directory
where applicable. Each sub-module has a clear API boundary, can be built
optionally, and contributes to the same Python wheel via `viz/python/`.

**Sub-modules:**

| Sub-module | Library | Depends on | Purpose |
|------------|---------|------------|---------|
| `viz/core/` | `viz_core` | Vulkan, CUDA | Foundational types (`VizBuffer`, `Pose3D`, `Fov`, `Resolution`, `PixelFormat`) and Vulkan/CUDA infrastructure (`vk_context`, `cuda_texture`, `render_target`, `frame_sync`). |
| `viz/layers/` | `viz_layers` | `viz_core` | `LayerBase` and built-in layer types: `QuadLayer`, `ProjectionLayer`, `OverlayLayer`. |
| `viz/session/` | `viz_session` | `viz_core`, `viz_layers` | `VizSession`, `VizCompositor`, `FrameInfo`, display backends (offscreen, GLFW window). |
| `viz/xr/` | `viz_xr` | `viz_core`, OpenXR | OpenXR backend (instance/session, swapchain wrapping, frame loop, type conversion). Optional: `BUILD_VIZ_XR` (default ON when OpenXR available). |
| `viz/python/` | `_viz.so` | `viz_session` (+ `viz_xr` if enabled) | Pybind11 bindings, exposed as `isaacteleop.viz`. |
| `viz/shaders/` | — | glslangValidator | GLSL → SPIR-V at build time. |

**Tests:**

| Test dir | Tests for | Notes |
|----------|-----------|-------|
| `viz/core_tests/` | `viz_core` | `[unit]`: types, buffer; `[gpu]`: vk_context, cuda interop |
| `viz/layers_tests/` | `viz_layers` | `[unit]`: layer registry, placement math; `[gpu]`: render verification |
| `viz/session_tests/` | `viz_session` | `[unit]`: state machine; `[gpu]`: offscreen render + readback |
| `viz/xr_tests/` | `viz_xr` | `[xr]`: manual only (requires runtime + headset) |

**Include paths** mirror the on-disk nesting (sub-modules are children
of `viz/`, not peers):

- `<viz/core/vk_context.hpp>`, `<viz/core/viz_buffer.hpp>`
- `<viz/layers/quad_layer.hpp>`
- `<viz/session/viz_session.hpp>`
- `<viz/xr/xr_backend.hpp>`

C++ namespace stays `viz` across all sub-modules. CMake library
aliases follow the same nesting: `viz::core`, `viz::layers`,
`viz::session`, `viz::xr` (real target names use underscores —
`viz_core`, etc. — since `::` is reserved for aliases).

**File-name conventions** within a sub-module carry implicit grouping:

- `vk_*`, `cuda_*` — Vulkan / CUDA infrastructure
- `*_layer` — `LayerBase` subclasses
- `viz_*` — top-level public types
- `frame_*` — per-frame state types
- `xr_*` — OpenXR specifics

**Layout** (only `viz/core/` is implemented today; other sub-modules and
tests are added as they ship):

```
IsaacTeleop/src/viz/
├── CMakeLists.txt                  # orchestrator
├── core/
│   ├── CMakeLists.txt
│   └── cpp/
│       ├── CMakeLists.txt          # static lib viz_core (alias viz::core)
│       ├── inc/viz/core/
│       │   ├── vk_context.hpp
│       │   ├── cuda_texture.hpp    (later)
│       │   ├── render_target.hpp   (later)
│       │   ├── frame_sync.hpp      (later)
│       │   ├── viz_buffer.hpp
│       │   └── viz_types.hpp
│       ├── vk_context.cpp
│       ├── cuda_texture.cpp        (later)
│       ├── render_target.cpp       (later)
│       └── frame_sync.cpp          (later)
├── layers/                         # added with first layer
│   ├── CMakeLists.txt
│   └── cpp/
│       ├── CMakeLists.txt          # static lib viz_layers (alias viz::layers)
│       ├── inc/viz/layers/
│       │   ├── layer_base.hpp
│       │   ├── quad_layer.hpp
│       │   ├── projection_layer.hpp
│       │   └── overlay_layer.hpp
│       └── *.cpp
├── session/                        # added with VizSession
│   ├── CMakeLists.txt
│   └── cpp/
│       ├── CMakeLists.txt          # static lib viz_session (alias viz::session)
│       ├── inc/viz/session/
│       │   ├── viz_session.hpp
│       │   ├── viz_compositor.hpp
│       │   └── frame_info.hpp
│       └── *.cpp
├── xr/                             # optional, BUILD_VIZ_XR
│   ├── CMakeLists.txt
│   └── cpp/
│       ├── CMakeLists.txt          # static lib viz_xr (alias viz::xr)
│       ├── inc/viz/xr/
│       │   ├── xr_backend.hpp
│       │   ├── xr_swapchain.hpp
│       │   ├── xr_frame.hpp
│       │   └── xr_types.hpp
│       └── *.cpp
├── shaders/                        # added with first shader
│   ├── CMakeLists.txt
│   ├── textured_quad.vert
│   └── textured_quad.frag
├── python/
│   ├── CMakeLists.txt              # pybind11 → _viz (filled later)
│   ├── viz_bindings.cpp
│   └── viz_init.py
├── core_tests/
│   ├── CMakeLists.txt
│   └── cpp/
│       ├── CMakeLists.txt          # Catch2, catch_discover_tests
│       ├── test_helpers.hpp
│       ├── test_viz_buffer.cpp
│       ├── test_viz_types.cpp
│       └── test_vk_context.cpp
├── layers_tests/                   # added with viz/layers/
├── session_tests/                  # added with viz/session/
└── xr_tests/                       # added with viz/xr/ (manual)
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
namespace viz
{

struct Resolution
{
    uint32_t width;
    uint32_t height;
};

struct Pose3D
{
    glm::vec3 position{0.0f};                      // meters
    glm::quat orientation{1.0f, 0.0f, 0.0f, 0.0f}; // unit quat (w, x, y, z)
};

struct Fov
{
    float angle_left;     // radians from forward axis, negative = left
    float angle_right;    // radians
    float angle_up;       // radians
    float angle_down;     // radians
};

} // namespace viz
```

OpenXR types (`XrPosef`, `XrFovf`) are converted to these at the Televiz
boundary in `viz::detail`. Consumers never see OpenXR headers.

### VizBuffer / HostImage / DeviceImage

The image-data surface in Televiz separates **shape** (one type) from
**ownership + memory space** (two types):

| Type | Role | Owns? | Memory space |
|---|---|---|---|
| `VizBuffer` | image-shape view (data ptr + dims + format + pitch) | No | `kDevice` *(default)* or `kHost` |
| `HostImage` | owning host bytes, exposes a `VizBuffer view()` | Yes | `kHost` |
| `DeviceImage` | owning device memory + CUDA-Vulkan interop primitives, exposes a `VizBuffer view()` | Yes | `kDevice` |

```cpp
namespace viz
{

enum class PixelFormat
{
    kRGBA8,     // 4-channel uint8 color (Phase 1)
    kD32F,      // single-channel float32 depth (Phase 2)
};

enum class MemorySpace
{
    kDevice,    // CUDA device memory (default; production layer interop)
    kHost,      // CPU memory (test-grade readback, debug helpers)
};

struct VizBuffer
{
    void* data;
    uint32_t width;
    uint32_t height;
    PixelFormat format;
    size_t pitch;            // Row pitch in bytes (0 = tightly packed)
    MemorySpace space;       // Where data lives; default kDevice
};

} // namespace viz
```

`VizBuffer` carries no ownership: the producer (layer / external
renderer / `HostImage` / `DeviceImage`) owns the underlying memory;
`VizBuffer` is a typed view over it. The `space` field is documentary
— callers must match it to the API they're calling (CUDA expects
`kDevice`, CPU helpers expect `kHost`); there is no runtime check.

`HostImage` and `DeviceImage` are the owning counterparts. Use them
when Televiz needs to allocate (offscreen readback → `HostImage`;
mode-B `acquire`/`release` interop → `DeviceImage`). Both expose
`view()` returning a `VizBuffer` of the matching `space`, so the same
helpers (`save_to_png`, image-diff, Python interop) take a single
`VizBuffer` and work for both. Callers that are handed memory by
someone else (mode-A `submit(VizBuffer)`, external renderer hand-off)
work with bare `VizBuffer` views directly.

In Python:
- `VizBuffer.space == kDevice` exposes `__cuda_array_interface__` →
  `cupy.asarray(buf)`
- `VizBuffer.space == kHost` exposes `__array_interface__` →
  `numpy.asarray(buf)`

For RGBD content (Phase 2):

```cpp
struct VizBufferPair {            // Phase 2, ProjectionLayer
    VizBuffer color;              // kRGBA8
    VizBuffer depth;              // kD32F
};
```

#### Implementation status

- `VizBuffer` (with `MemorySpace`): shipped.
- `HostImage`: shipped — used by `VizSession::readback_to_host()` and
  `VizCompositor::readback_to_host()` for test/debug pixel inspection.
- `DeviceImage`: forward-declared today. Full implementation
  (CUDA-Vulkan interop with `VK_KHR_external_memory_fd`,
  `cudaExternalMemory_t`, paired acquire/release semaphores) ships
  alongside CUDA-Vulkan interop.

---

## VizSession API

The central object. Manages the Vulkan context, OpenXR session (XR mode),
display target, and layer registry. Session lifecycle follows the state
machine below.

```cpp
namespace viz
{

enum class DisplayMode
{
    kXR,           // OpenXR graphics-bound session
    kWindow,       // GLFW windowed mono (tiling layout)
    kOffscreen,    // No display; readback() only
};

class VizSession
{
public:
    struct Config
    {
        DisplayMode mode;
        uint32_t window_width;                  // Window and offscreen modes
        uint32_t window_height;
        std::string app_name = "televiz";       // Used by OpenXR

        // Additional OpenXR instance extensions to enable. Used when Televiz
        // hosts the XR session and other components (e.g. TeleopSession
        // trackers) need their own extensions. Televiz already enables its
        // own required extensions (VULKAN_ENABLE2, COMPOSITION_LAYER_DEPTH,
        // CONVERT_TIMESPEC_TIME). Pass tracker extensions here.
        // Example: {"XR_EXT_hand_tracking", "XR_EXT_eye_gaze_interaction"}
        std::vector<std::string> required_extensions;
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
    //   auto* cam  = session->add_layer<QuadLayer>(QuadLayer::Config{...});
    //   auto* mesh = session->add_layer<MyMeshLayer>(my_renderer, ...);
    template <typename L, typename... Args>
    L* add_layer(Args&&... args);

    void remove_layer(LayerBase* layer);

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
    //    begin_frame: XR: xrWaitFrame (blocking), xrBeginFrame, xrLocateViews.
    //                 Window: vsync wait. Offscreen: immediate return.
    //    end_frame:   composite + present.
    //    Python bindings release the GIL during blocking portions.
    FrameInfo begin_frame();
    void end_frame();

    // Session state.
    SessionState get_state() const;

    // Runtime queries.
    Resolution get_recommended_resolution() const;
    FrameTimingStats get_frame_timing_stats() const;

    // Readback (kOffscreen only). Returns the last composited frame as
    // a VizBuffer (CUDA device pointer). Valid until next render() / end_frame().
    VizBuffer readback(cudaStream_t stream = 0);

    // Handle access for external renderer integration and session sharing.
    VkDevice get_vk_device() const;
    VkPhysicalDevice get_vk_physical_device() const;
    uint32_t get_vk_queue_family_index() const;
    VkRenderPass get_render_pass() const;             // For custom layer pipelines
    OpenXRSessionHandles get_oxr_handles() const;     // XR mode only
};

} // namespace viz
```

### FrameInfo

Returned by `render()` and `begin_frame()`. Per-frame state for content producers:

```cpp
namespace viz
{

struct ViewInfo
{
    glm::mat4 view_matrix;          // GLSL-compatible column-major
    glm::mat4 projection_matrix;
    Fov fov;
    Pose3D pose;
};

struct FrameInfo
{
    uint64_t frame_index;
    int64_t predicted_display_time; // XR time (ns). 0 in window/offscreen.
    float delta_time;               // Seconds since last frame
    bool should_render;
    std::vector<ViewInfo> views;    // 2 in XR (stereo); 1 otherwise
    Resolution resolution;
};

struct FrameTimingStats
{
    float render_fps;
    float target_fps;
    uint64_t missed_frames;
    float avg_frame_time_ms;
    float gpu_time_ms;
    uint32_t stale_layers;          // Layers that missed stale_timeout
};

} // namespace viz
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
namespace viz
{

class LayerBase
{
public:
    virtual ~LayerBase() = default;

    // Called by the compositor during the render pass. Subclasses record
    // Vulkan draw commands into the provided command buffer.
    // The render pass is already active (RGBA8_SRGB + D32_SFLOAT, 1 sample).
    virtual void record(VkCommandBuffer cmd,
                        const std::vector<ViewInfo>& views,
                        const RenderTarget& target) = 0;

    // Common properties.
    const std::string& get_name() const;
    bool is_visible() const;
    void set_visible(bool visible);
};

} // namespace viz
```

**Custom layers:** Create a `VkPipeline` compatible with Televiz's render
pass (via `VizSession::get_render_pass()`), subclass `LayerBase`,
implement `record()`, register via `VizSession::add_layer()`. The
compositor iterates layers **in insertion order** and calls `record()`
for each visible layer. This is the pull model, generalized — any Vulkan
drawing code works as long as it's render-pass-compatible.

### QuadLayer

A 2D image placed in 3D space. The most common layer type for camera
feeds. Built-in textured-quad rendering + CUDA interop.

```cpp
namespace viz
{

enum class PlacementMode
{
    kWorldLocked,   // Fixed pose in stage space
    kHeadLocked,    // Follows headset exactly (HUD-style)
    kLazyLocked,    // Follows headset with damping
    kCustom,        // Application-provided callback
};

struct LazyLockConfig
{
    float look_away_angle = 45.0f;      // Degrees; reposition when user looks away
    float reposition_distance = 0.5f;   // Meters; reposition when user walks away
    float reposition_delay = 0.5f;      // Seconds before repositioning starts
    float transition_duration = 0.3f;   // Seconds for smooth reposition
};

using PlacementCallback = std::function<Pose3D(const Pose3D& head_pose, float delta_time)>;

class QuadLayer : public LayerBase
{
public:
    struct Config
    {
        std::string name;
        float width_meters;
        float height_meters;
        PlacementMode placement = PlacementMode::kWorldLocked;
        LazyLockConfig lazy_lock;             // Used when placement == kLazyLocked
        PlacementCallback placement_callback; // REQUIRED when placement == kCustom
        float stale_timeout = 2.0f;           // Seconds before showing placeholder
    };

    // Mode A: fire-and-forget. Copies from the VizBuffer into the layer's
    // interop back buffer. Non-blocking (enqueues on stream). Reallocates
    // internal buffer if dimensions change.
    void submit(const VizBuffer& image, cudaStream_t stream = 0);

    // Mode B: zero-copy write. Returns a VizBuffer pointing to the layer's
    // interop back buffer. Allocates on first call; reuses when dimensions
    // match; reallocates when they change. Producer writes into buf.data,
    // then calls release().
    VizBuffer acquire(uint32_t width, uint32_t height, PixelFormat format = PixelFormat::kRGBA8);
    void release(cudaStream_t stream = 0);

    void set_pose(const Pose3D& pose);
    void set_size(float width_meters, float height_meters);

    // LayerBase override (internal).
    void record(VkCommandBuffer cmd,
                const std::vector<ViewInfo>& views,
                const RenderTarget& target) override;
};

} // namespace viz
```

**Placement modes:**

- `kWorldLocked` — fixed pose in stage space (set via `set_pose`).
- `kHeadLocked` — pose tracks headset every frame.
- `kLazyLocked` — follows headset with configurable damping
  (`LazyLockConfig`). Parameters match the existing camera_streamer UX.
- `kCustom` — application provides `Config::placement_callback`.
  Required at `add_layer` time; invalid config throws.

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
namespace viz
{

class ProjectionLayer : public LayerBase
{
public:
    struct Config
    {
        std::string name;
    };

    // Push: submit pre-rendered color + depth.
    void submit(const VizBuffer& color, const VizBuffer& depth, cudaStream_t stream = 0);

    void record(VkCommandBuffer cmd,
                const std::vector<ViewInfo>& views,
                const RenderTarget& target) override;
};

} // namespace viz
```

Use cases: nvblox 3D reconstruction, depth-enhanced camera rendering.

### OverlayLayer (Phase 2)

A 2D image composited in screen space after all world-space content. No
depth testing.

```cpp
namespace viz
{

class OverlayLayer : public LayerBase
{
public:
    struct Config
    {
        std::string name;
        float x, y;                 // Normalized screen position [0,1]
        float width, height;        // Normalized screen size [0,1]
    };

    void submit(const VizBuffer& image, cudaStream_t stream = 0);
    void set_rect(float x, float y, float width, float height);

    void record(VkCommandBuffer cmd,
                const std::vector<ViewInfo>& views,
                const RenderTarget& target) override;
};

} // namespace viz
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
the first `begin_frame` is fine — content appears in the first rendered
frame).

### Double Buffering and Synchronization

Each layer has two interop buffers (front + back). Producers write to the
back buffer at their own rate. The compositor reads the front buffer.

Sync flow for Mode A:

1. `submit` enqueues `cudaMemcpyAsync` on the producer's stream.
2. The stream signals an exported semaphore when the copy completes.
3. At `end_frame`, the compositor checks if the semaphore has fired.
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

**Timing with `begin_frame`/`end_frame`:** `acquire`/`release` and
`begin_frame`/`end_frame` are independent lifecycles. The compositor
picks up whatever is latest at `end_frame`. Multi-threaded producers
can write
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
namespace viz
{

struct RenderTarget
{
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

} // namespace viz
```

---

## Session State Machine

```cpp
namespace viz
{

enum class SessionState
{
    kUninitialized,  // Before create()
    kReady,          // Vulkan + display initialized. Layers and content can be added.
    kRunning,        // Frame loop active.
    kStopping,       // XR: session stopping. end_frame submits empty frames.
    kLost,           // XR: session lost. Must destroy and recreate.
    kDestroyed,      // After destroy(). No operations valid.
};

} // namespace viz
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

| State | `render()` / `begin_frame()` | `end_frame()` | `add_layer()` | `submit()` |
|---|---|---|---|---|
| kReady | Transitions to kRunning, returns first frame | — | Valid | Valid |
| kRunning | Returns FrameInfo normally | Composites + presents | Valid | Valid |
| kStopping | Returns `should_render=false` | Submits empty frame | No | No |
| kLost / kDestroyed | Throws `VizSessionLostError` / `RuntimeError` | No-op | No | No |

### XR Event Handling

OpenXR events are polled inside `begin_frame()`. Session state
transitions are driven by the runtime; VizSession updates its own state
accordingly. The application observes state via `get_state()` and
`FrameInfo::should_render`.

For `kLost`: the application destroys and recreates the VizSession.
Televiz supports clean recreation in-process — no `os.execv` restart
needed.

---

## IsaacTeleop Integration

### Package Name

`isaacteleop.viz` — follows the pattern of `isaacteleop.oxr`,
`isaacteleop.mcap`, `isaacteleop.schema`.

### Session Ownership

IsaacTeleop's existing `OpenXRSession` creates a **headless** OpenXR
session for device tracking — no Vulkan binding, cannot render. Televiz
needs a **graphics-bound** XR session for rendering.

**Televiz always creates its own graphics-bound session.** When both
Televiz and TeleopSession are used together, the application has two
choices:

| Pattern | When to use | How |
|---------|-------------|-----|
| **Unified (recommended)** | Both Televiz and TeleopSession active. Single CloudXR connection, synchronized timing. | Pass `viz_session.get_oxr_handles()` to `TeleopSessionConfig.oxr_handles`. TeleopSession skips creating its own session and attaches its trackers to Televiz's. |
| **Separate** | Debugging, isolation, or running TeleopSession alone (no rendering). | Don't pass `oxr_handles`. TeleopSession creates its own headless session. |

The unified pattern requires that Televiz's OpenXR instance has the
extensions trackers need (e.g. `XR_EXT_hand_tracking`). The application
declares these in `VizSession::Config::required_extensions`. Televiz
already enables its own rendering extensions automatically.

```python
# Unified (recommended): single XR session shared between rendering and trackers.
viz_session = isaacteleop.viz.VizSession.create(viz.Config(
    mode=viz.DisplayMode.XR,
    required_extensions=[
        "XR_EXT_hand_tracking",   # for hand trackers
        # ... other tracker extensions as needed
    ],
))
teleop_config = TeleopSessionConfig(
    pipeline=pipeline,
    oxr_handles=viz_session.get_oxr_handles(),  # trackers share viz session
)

# Separate (fallback): two sessions, two CloudXR connections.
# Works the same — just don't pass oxr_handles to TeleopSession.
```

**Future alternative — Option C: Extended OXR module.** OXR could
optionally create the graphics-bound session itself and pass Vulkan
handles to Televiz. Considered but not pursued: requires OXR module
changes; current path is simpler.

### Application-Level Integration

Televiz integrates alongside `TeleopSession`, not inside it. Both run in
the application loop. The unified-session pattern (recommended) shares
Televiz's XR session with TeleopSession's trackers:

```python
import isaacteleop.viz as viz
from isaacteleop import TeleopSession, TeleopSessionConfig

# Televiz creates the graphics-bound session, with extensions trackers need.
viz_session = viz.VizSession.create(viz.Config(
    mode=viz.DisplayMode.XR,
    required_extensions=["XR_EXT_hand_tracking"],
))
cam_layer = viz_session.add_layer(viz.QuadLayer.Config(
    name="front_cam", width_meters=1.0, height_meters=0.5625,
    placement=viz.PlacementMode.LAZY_LOCKED))

# TeleopSession reuses Televiz's session — single CloudXR connection.
teleop_config = TeleopSessionConfig(
    app_name="teleop",
    pipeline=pipeline,
    oxr_handles=viz_session.get_oxr_handles(),
)
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

TeleopSession and VizSession are **independent components** with their
own state machines:

- **Different lifecycles:** VizSession tracks XR session + Vulkan device
  state. TeleopSession tracks device connections and retargeting.
- **Independent deployment:** Either can run without the other.
- **Independent failure modes:** Trackers can disconnect while
  VizSession keeps rendering. A retargeting pipeline error doesn't
  affect rendering.

In the **unified-session pattern**, the underlying OpenXR session is
shared. If the XR session is lost (`VizSession.kLost`), trackers also
lose their session — the application must destroy and recreate both. In
the **separate-session pattern**, XR session loss in one is independent
of the other.

The application loop is the coordination point in either pattern.

---

## Rendering Strategy

All layers composite into a single stereo framebuffer per frame,
submitted as one `XrCompositionLayerProjection` with depth. Per frame:

```
xrWaitFrame → xrBeginFrame → xrLocateViews → acquire swapchain →
  begin render pass →
    for each layer in insertion order:
      if layer.is_visible(): layer.record(cmd, views, target)
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
  count, display refresh rate via `get_recommended_resolution()`.
- **Per-frame (`FrameInfo`):** per-eye pose + FOV + view + projection
  matrices, `predicted_display_time`, `should_render`, `delta_time`.
- **Performance stats (polled):** `get_frame_timing_stats()` — render FPS,
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

- `render()` and `begin_frame()` release the GIL during blocking wait
  (xrWaitFrame / vsync). All other APIs hold the GIL — they are fast,
  non-blocking.
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
no GLFW, no OpenXR, no swapchain, no display server. `end_frame()`
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
    │   ├── test_helpers.hpp   # Fixtures, pixel comparison, GPU detection
    │   ├── test_viz_buffer.cpp     # [unit]
    │   ├── test_viz_types.cpp      # [unit]
    │   ├── test_state_machine.cpp  # [unit]
    │   ├── test_layer_mgmt.cpp     # [unit]
    │   ├── test_placement.cpp      # [unit]
    │   ├── test_vk_context.cpp     # [gpu]
    │   ├── test_cuda_interop.cpp   # [gpu]
    │   └── test_quad_render.cpp    # [gpu] kOffscreen + readback
    └── python/
        ├── CMakeLists.txt     # add_test with uv run pytest
        ├── pyproject.toml     # [tool.pytest.ini_options]
        ├── conftest.py        # GPU detection fixture
        ├── test_viz_session.py
        ├── test_quad_layer.py
        └── test_offscreen_render.py
```

**C++ tests (Catch2):** `TEST_CASE` / `SECTION` / `CHECK` pattern
matching existing `schema_tests` and `mcap_tests`. Linked against
`viz_core` + `Catch2::Catch2WithMain`. `catch_discover_tests` registers
each `TEST_CASE` as a CTest test.

**Python tests (pytest):** Import from `isaacteleop.viz` namespace.
`PYTHONPATH` set to build's `python_package/` tree by CMake.

### Test Tags

Catch2 tags categorize tests by infrastructure requirements. CTest can
filter via labels; CI configurations select what to run.

| Tag | Meaning | When to run |
|-----|---------|-------------|
| `[unit]` | Pure C++ logic. No GPU, no Vulkan, no I/O. | Always — fast, runs everywhere. |
| `[gpu]` | Requires Vulkan-capable GPU (and CUDA for interop tests). | GPU CI, dev machines. Skipped gracefully on no-GPU systems. |
| `[xr]` | Requires OpenXR runtime + headset. | Manual only in Phase 1. |
| `[slow]` | Long-running tests (>1s typical). | Optional in CI. |

Tags are listed in `TEST_CASE` declarations:
```cpp
TEST_CASE("VizBuffer construction", "[unit][viz_buffer]") { ... }
TEST_CASE("VkContext creates device", "[gpu][vk_context]") { ... }
```

Run subsets via Catch2 directly or CTest:
```sh
./viz_tests "[unit]"               # Unit tests only
./viz_tests "[gpu]"                # GPU tests only
./viz_tests "[unit] | [gpu]"       # Both
ctest -L unit                      # Via CTest labels (when wired)
```

### GPU Detection and Skipping

Tests tagged `[gpu]` use a shared fixture that probes for Vulkan
availability and skips gracefully when no GPU is present (CI on
CPU-only runners, machines without drivers, etc.).

```cpp
// test_helpers.hpp
namespace viz::testing
{

bool is_gpu_available();   // Tries minimal vkCreateInstance + device enum

struct GpuFixture
{
    viz::VkContext vk;

    GpuFixture()
    {
        if (!is_gpu_available())
        {
            SKIP("No Vulkan-capable GPU available");
        }
        vk.init(viz::VkContext::Config{});
    }
};

} // namespace viz::testing
```

Usage:
```cpp
TEST_CASE_METHOD(viz::testing::GpuFixture,
                 "VkContext exposes valid device",
                 "[gpu][vk_context]")
{
    CHECK(vk.device() != VK_NULL_HANDLE);
    CHECK(vk.physical_device() != VK_NULL_HANDLE);
}
```

`SKIP()` is a Catch2 v3 macro that marks the test skipped (not failed).
CI sees "skipped" rather than "failed" on no-GPU environments.

For Python tests, `conftest.py` provides equivalent fixtures:
```python
import pytest

def gpu_available() -> bool: ...

@pytest.fixture
def viz_session_offscreen():
    if not gpu_available():
        pytest.skip("No Vulkan-capable GPU available")
    session = viz.VizSession.create(viz.Config(
        mode=viz.DisplayMode.OFFSCREEN, window_width=64, window_height=64))
    yield session
    session.destroy()
```

### Test Helpers

Shared utilities in `test_helpers.hpp`:

```cpp
namespace viz::testing
{

// True if a Vulkan-capable GPU + driver is present.
bool is_gpu_available();

// True if running on CI (CI=true env var). Used to skip flaky/slow tests.
bool is_on_ci();

// Fill a VizBuffer with a known test pattern (for round-trip tests).
void fill_test_pattern(VizBuffer buf, uint32_t seed = 0);

// Pixel-level comparison with tolerance (sRGB roundtrip introduces small
// errors). Returns true if all pixels are within `tolerance` per channel.
bool pixels_match(const VizBuffer& actual,
                  const VizBuffer& expected,
                  uint8_t tolerance = 2);

} // namespace viz::testing
```

`pixels_match` defaults tolerance to `2` because the
`R8G8B8A8_SRGB` → linear → render → `R8G8B8A8_SRGB` round-trip has a
~1 LSB rounding error that's not a real failure.

### Test Data Conventions

- **Sizes:** Use small framebuffers for unit tests (`64x64` to `256x256`).
  No need to test at 4K stereo when verifying compositor logic.
- **No external assets:** Generate test patterns programmatically
  (gradients, color blocks, checkerboards). Avoids file-loading
  dependencies.
- **Deterministic:** Seed any random patterns. The same test must
  produce the same output every run.

### Example Test Patterns

**Unit test (no GPU):**
```cpp
TEST_CASE("VizBuffer pitch defaults to packed", "[unit][viz_buffer]")
{
    viz::VizBuffer buf{nullptr, 1920, 1080, viz::PixelFormat::kRGBA8, 0};
    CHECK(viz::effective_pitch(buf) == 1920 * 4);
}
```

**GPU integration test (Catch2):**
```cpp
TEST_CASE_METHOD(viz::testing::GpuFixture,
                 "QuadLayer round-trip pattern",
                 "[gpu][quad_layer]")
{
    auto session = VizSession::create({.mode = DisplayMode::kOffscreen,
                                       .window_width = 64,
                                       .window_height = 64});
    auto* layer = session->add_layer<QuadLayer>(QuadLayer::Config{
        .name = "test", .width_meters = 1.0f, .height_meters = 1.0f});

    VizBuffer expected = layer->acquire(64, 64, PixelFormat::kRGBA8);
    viz::testing::fill_test_pattern(expected);
    layer->release();

    session->render();
    auto result = session->readback();
    CHECK(viz::testing::pixels_match(result, expected, /*tolerance=*/2));
}
```

**Python GPU test:**
```python
def test_quad_render(viz_session_offscreen):
    """Integration test — requires GPU."""
    session = viz_session_offscreen
    layer = session.add_layer(viz.QuadLayer.Config(
        name="test", width_meters=1.0, height_meters=1.0))
    layer.submit(test_pattern_cupy_array())
    session.render()
    result = session.readback()
    assert pixels_match(result, expected)
```

**XR tests:** Manual testing with CloudXR + headset. Not automated in
Phase 1.

### Failure-mode audit checklist

Lessons distilled from real bugs caught in code review (the M2.2
fence-reset, frame-pairing, and validate-then-allocate misses). For
every new public function, walk this list before submitting a PR:

1. **Validate inputs first, allocate second.** All preconditions
   (mode supported? config sane? dependencies initialized?) must be
   checked before any resource is acquired (`vkCreate*`, `cudaMalloc`,
   heap allocation). A failed validation should leave the system
   unchanged.

2. **Exception safety on every mutation.** For each
   "acquire/reset/begin → ... → release/submit/end" pattern, ask:
   *what happens if the middle code throws?* Move the reset adjacent
   to the matching release where possible, or use an RAII guard, or
   catch + revert. Never leave a fence unsignaled, a flag stuck, or
   a Vulkan handle dangling on a failure path.

3. **State-machine hygiene.** When introducing any state field
   (explicit enum or implicit boolean like `frame_in_progress`),
   enumerate every transition — including invalid ones — and decide
   whether to throw, no-op, or assert. Silent no-ops mask real bugs
   in caller code; prefer throw for invalid transitions in test /
   debug paths.

4. **Idempotent destroy.** `destroy()` and equivalent cleanup paths
   must be safe to call twice and after partial init failure. Test
   it.

5. **Threading contract documented.** Every public mutation method
   must document whether it's thread-safe. Default to "single-
   threaded; must be called from the frame thread" unless explicitly
   designed for cross-thread use (and then it needs an atomic /
   mutex / lock-free queue).

6. **Test the failure paths.** Beyond happy-path coverage, every
   feature ships with at least:
   - **invalid-input rejection** test (no GPU needed),
   - **state-machine invalid-transition** test (begin/begin,
     end/end, etc.),
   - **exception recovery** test (inject a throw mid-loop, verify
     next iteration works) — `viz::testing::ThrowingLayer` is the
     canonical pattern,
   - **idempotent destroy** test.

CI helps but does not replace this audit:
- **clang-format** + **CodeRabbit** catch some of #1, #2, #3.
- **AddressSanitizer / UBSAN** in CI catches lifetime / leak bugs
  (#1 / #4 partially) — see the `test-viz-sanitizers` workflow job.
- **Test patterns above** catch #2 / #3 / #6 — these are the
  developer's responsibility to write up-front.

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

### `examples/camera_viz/` — Phase 1

Drop-in replacement for the existing `examples/camera_streamer/` — same
camera sources, same RTP transport, same YAML config schema, but with
the entire Holoscan / HoloHub / GXF stack removed. Architecture:

- **Camera capture** (V4L2, OAK-D, ZED) and **GStreamer RTP** code
  extracted from the current `camera_streamer/operators/` into
  standalone Python/C++ modules (no Holoscan operator framework).
- **NVENC/NVDEC** wrappers extracted from `NvStreamEncoderOp` /
  `NvStreamDecoderOp` C++ ops into standalone CUDA modules.
- **Application loop** in Python: drive `VizSession.render()` in a
  while loop; producers feed CUDA buffers via `submit()`.
- **Stale-content** handling and **frame combining** are no longer
  needed — Televiz handles them per-layer (built-in stale detection +
  double buffering).
- **YAML config** schema preserved (camera sources + display section
  with XR plane placement / lock_mode / lazy params).
- **Display modes**: monitor (`kWindow`) and XR (`kXR`) — same
  user-facing CLI as `camera_streamer`.

This is the validation milestone for Phase 1.

### `examples/reconstruction_viz/` — Phase 2

nvblox_renderer integration. A custom `LayerBase` subclass wraps
`MeshVisualizer::render(cmd, view_proj, x, y, w, h)` — zero-copy, via
Televiz's render pass. Optional QuadLayers for raw camera feeds
alongside the reconstruction.

### `examples/teleop_viz/` — Phase 2

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

1. **Session ownership:** Televiz hosts the graphics-bound XR session.
   Application shares it with TeleopSession via `oxr_handles` (unified
   pattern, recommended) or runs them as separate sessions (fallback).
   Single CloudXR connection in unified mode.
2. **XR swapchain usage:** Intermediate framebuffer → `vkCmdBlitImage`
   to swapchain.
3. **Stereo layout:** SBS. `VK_KHR_multiview` deferred.
4. **Tracker extension declaration:** Application passes tracker
   extensions to `VizSession::Config::required_extensions`. No
   TeleopSession code changes needed.
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
- **`createWithXrSession` constructor:** Session injection path for the
  hypothetical Option C (extended OXR module). Televiz always creates
  its session; the unified-session pattern uses `get_oxr_handles()` which
  already exists.

### Architecture Improvements / Known Limitations

- **Multi-GPU Device Matching**: Currently `vk_context` prefers NVIDIA GPUs but may mismatch with the active CUDA device. Must query the Vulkan physical device's UUID (`VkPhysicalDeviceIDProperties`) and match it with the active CUDA device UUID (`cudaDeviceGetProp::uuid`) to avoid P2P overhead or failures.
- **Dynamic Resolution Reallocation**: Rapid dimension changes in `submit`/`acquire` trigger `VkImage` and `cudaExternalMemory_t` reallocation, causing stutter. A future improvement should over-allocate and update viewport/scissor/UVs, only reallocating if the new frame exceeds capacity.
- **Hardcoded Pixel Formats (NV12 vs. RGBA8)**: `VizBuffer` currently forces `kRGBA8`, making hardware decoders (NVDEC) convert from NV12/YUV upstream. Future phases should support Vulkan YCbCr samplers to allow zero-cost color-space conversion in the shader.
- **Error Granularity in Python**: Generic `RuntimeError` makes programmatic recovery hard. We should introduce a richer exception hierarchy in pybind11 (e.g., `VulkanError`, `CudaInteropError`, `InvalidStateError`).
- **Asynchronous Readback**: The `readback()` method maps the intermediate framebuffer synchronously. If production video recording is ever needed, it will require asynchronous PBO readback via a ring-buffer of `VkBuffer` objects.

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
  `begin_frame`/`end_frame` explicit), layer registry, display modes
  (kXR, kWindow, kOffscreen), state machine. `Config::required_extensions`
  for tracker integration. `get_oxr_handles()` returns handles for
  unified-session pattern with TeleopSession.
- `VizCompositor` — single render pass, SBS stereo,
  `vkCmdBlitImage` to swapchain (or readback in offscreen)

**Core types:**

- `Resolution`, `Pose3D`, `Fov` (OpenXR-free public API)
- `VizBuffer`, `PixelFormat` (`kRGBA8`)
- `FrameInfo`, `ViewInfo`, `FrameTimingStats`, `SessionState`

**Layer types:**

- `LayerBase` — extensible abstract base with virtual `record()`.
  Custom layers via `add_layer()`.
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

- CMakeLists under each `src/viz/<sub-module>/`, wired into root
- FetchContent for GLFW, GLM, pybind11
- Optional OpenXR SDK (`BUILD_XR=ON`)

**Testing:**

- Unit tests: state machine, layer management, placement math (no GPU)
- Integration tests: kOffscreen + `readback()` for pixel verification (GPU CI)
- Manual XR testing with CloudXR + headset

**Validation:**

- `examples/camera_viz/` — drop-in Holoscan-free replacement for
  `examples/camera_streamer/`

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
- Possible: extended OXR module (Option C) if symmetric ownership is
  ever needed.
