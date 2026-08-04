// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/viz_types.hpp>
#include <vulkan/vulkan.h>

#include <atomic>
#include <optional>
#include <string>
#include <vector>

namespace viz
{

class RenderTarget;
class VizSession;
class VkContext;

// Maps ViewInfo::viewport → vkCmdSetViewport (origin top-left, depth
// [0,1], no y-flip). Layers call this once per view before drawing.
// Layer authors must NOT bind scissor — compositor pre-binds it.
inline void bind_view_viewport(VkCommandBuffer cmd, const ViewInfo& view)
{
    VkViewport vp{};
    vp.x = static_cast<float>(view.viewport.x);
    vp.y = static_cast<float>(view.viewport.y);
    vp.width = static_cast<float>(view.viewport.width);
    vp.height = static_cast<float>(view.viewport.height);
    vp.minDepth = 0.0f;
    vp.maxDepth = 1.0f;
    vkCmdSetViewport(cmd, 0, 1, &vp);
}

// Per-view source images for the direct-present path: a layer whose
// content is already a full-view (color, depth) image pair the backend
// can copy STRAIGHT into the presentation swapchains, bypassing the
// shared render target + render pass. This mirrors holohub xr_gsplat:
// the renderer's depth lands in the XR depth swapchain verbatim (no
// gl_FragDepth round-trip), so CloudXR reprojection gets exact depth.
// 1 entry for window/offscreen, 2 for kXr stereo.
struct DirectPresentView
{
    VkImage color = VK_NULL_HANDLE; // resting layout SHADER_READ_ONLY_OPTIMAL
    VkImage depth = VK_NULL_HANDLE; // VK_NULL_HANDLE when the layer has no depth
    Resolution extent{}; // must equal the swapchain per-view size
};

// Geometry a native OpenXR composition layer is sampled onto by the
// runtime. Each shape maps 1:1 to an XrCompositionLayer* struct; the
// backend gates non-quad shapes on the matching XR_KHR extension.
enum class NativeLayerShape
{
    kQuad, // XrCompositionLayerQuad (core)
    kCylinder, // XrCompositionLayerCylinderKHR (XR_KHR_composition_layer_cylinder)
    kEquirect2, // XrCompositionLayerEquirect2KHR (XR_KHR_composition_layer_equirect2)
};

// Per-frame descriptor for a layer that composites as a native OpenXR
// composition layer (quad / cylinder / equirect) instead of drawing into
// the shared render target. The XR backend owns a color swapchain per
// layer, copies ``color_left`` (and ``color_right`` for stereo) straight
// in, and submits one XrCompositionLayer* per eye — no shared RT, no
// projection draw. Only meaningful in kXr; non-XR backends never ask for
// one.
//
// A native layer carries no depth: the XrCompositionLayer* structs have
// no depth field, so the runtime composites them in submission order,
// not z-tested against projection-layer 3D content. This is inherent to
// OpenXR composition layers and is also what lets the runtime's layer
// fast path / client-reconstructed streaming treat them cheaply.
//
// ``shape`` selects which of the per-shape parameter groups below is
// meaningful; the others are ignored. A tagged flat struct (not a
// variant) to keep this header light and the backend's consumption
// simple.
struct NativeLayerView
{
    // Source images (resting layout SHADER_READ_ONLY_OPTIMAL). Backend
    // copies these into its own layer swapchain(s).
    VkImage color_left = VK_NULL_HANDLE;
    VkImage color_right = VK_NULL_HANDLE; // VK_NULL_HANDLE => mono (eyeVisibility BOTH)
    Resolution extent{}; // per-eye source size; the layer swapchain matches it

    // Placement origin in the session's reference space. Quad: center of
    // the rectangle. Cylinder: center point of the cylinder (arc bows
    // away from -z). Equirect: center of the sphere.
    Pose3D pose{};

    // Per-eye horizontal disparity along the placement's local +x axis
    // (millimeters); the left eye's layer pose shifts −half, the right
    // +half. Ignored mono. Any shape (a translated infinite-radius
    // equirect sphere is unchanged by construction, so it's a no-op there).
    float stereo_baseline_mm = 0.0f;

    // Composite this layer honoring its texture's alpha channel
    // (XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT). False =
    // opaque within the layer's bounds — the right setting for camera
    // feeds, and the one that keeps the layer eligible for the runtime's
    // client-reconstructed streaming (which excludes source-alpha layers).
    bool alpha_blend = false;

    NativeLayerShape shape = NativeLayerShape::kQuad;

    // ── kQuad ────────────────────────────────────────────────────────
    glm::vec2 size_meters{ 0.0f, 0.0f }; // physical width × height

    // ── kCylinder ────────────────────────────────────────────────────
    float radius = 0.0f; // meters (kEquirect2 shares it: 0 / +inf = infinite sphere)
    float central_angle = 0.0f; // visible arc, radians
    float aspect_ratio = 0.0f; // arc-width / height of the visible portion

    // ── kEquirect2 ───────────────────────────────────────────────────
    float central_horizontal_angle = 0.0f; // radians, 2π = full 360°
    float upper_vertical_angle = 0.0f; // radians from horizon, +π/2 = zenith
    float lower_vertical_angle = 0.0f; // radians from horizon, −π/2 = nadir

    // Stable identity the backend keys its persistent swapchain(s) on
    // across frames (the layer's ``this``). Never dereferenced by the backend.
    const void* source_id = nullptr;
};

// Abstract layer drawn into the compositor's render pass (RGBA8_SRGB
// color + D32_SFLOAT depth, single-sample). record() issues draw calls;
// it must NOT end the render pass or submit. Resource lifetime is the
// subclass's concern — compositor only ever calls record().
class LayerBase
{
public:
    explicit LayerBase(std::string name);
    virtual ~LayerBase() = default;

    LayerBase(const LayerBase&) = delete;
    LayerBase& operator=(const LayerBase&) = delete;

    // Optional transfer/compute work that can't run inside a render
    // pass (layout transitions, blits, mip generation). Called once per
    // visible layer BEFORE vkCmdBeginRenderPass on the same command
    // buffer. ``in_flight_slot`` matches the value the compositor will
    // pass to record() — implementations that mutate per-slot state
    // (QuadLayer mailbox) MUST agree on the slot across both calls.
    // Default = no-op.
    virtual void record_pre_render_pass(VkCommandBuffer /*cmd*/, uint32_t /*in_flight_slot*/)
    {
    }

    // Called from ``VizSession::begin_frame`` for EVERY registered layer
    // (visible or not) before the new frame's FrameInfo is returned.
    // Lets layers clear per-frame state (e.g. ProjectionLayer's
    // submitted-this-frame flag). Default = no-op. Must NOT touch GPU
    // state — the backend's begin_frame has already run, and the
    // compositor's per-slot fence wait hasn't happened yet.
    virtual void on_frame_begin()
    {
    }

    // Issue draws inside the active render pass.
    //   views:    1 entry in window/offscreen, 2 in kXr stereo. Each
    //             entry's viewport is this layer's rect for that view —
    //             bind it via viz::bind_view_viewport.
    //   in_flight_slot: index of the in-flight slot this render() is
    //             targeting. Layers with multi-frame-in-flight mailboxes
    //             (e.g. QuadLayer) use this to track which sample slot
    //             belongs to which in-flight frame, so submit() can pick
    //             a slot not currently being read by any GPU work. 0 in
    //             single-frame-in-flight setups.
    //   DO NOT bind scissor; compositor pre-binds it.
    virtual void record(VkCommandBuffer cmd,
                        const std::vector<ViewInfo>& views,
                        const RenderTarget& target,
                        uint32_t in_flight_slot) = 0;

    // Timeline waits to thread into vkQueueSubmit (e.g. CUDA-Vulkan
    // producer fences). Compositor concatenates across visible layers.
    struct WaitSemaphore
    {
        VkSemaphore semaphore = VK_NULL_HANDLE;
        uint64_t value = 0;
        VkPipelineStageFlags wait_stage = 0;
    };

    virtual std::vector<WaitSemaphore> get_wait_semaphores() const
    {
        return {};
    }

    // True only for ProjectionLayer. VizSession uses it to enforce the
    // single-projection XOR multi-quad invariant, and the compositor uses
    // it to pick the direct-present path.
    virtual bool is_projection_layer() const noexcept
    {
        return false;
    }

    // The VkContext this layer's GPU resources came from (nullptr if none).
    // add_layer rejects a layer whose context isn't the session's — its
    // images/semaphores would be used on the wrong device/queue.
    virtual const VkContext* vk_context() const noexcept
    {
        return nullptr;
    }

    // Direct-present support (see DirectPresentView). When true, the
    // compositor — for a session whose only layer is this one — skips the
    // render pass and asks the backend to copy these images straight to
    // the swapchains. Default: not supported (composited via the RT).
    virtual bool supports_direct_present() const noexcept
    {
        return false;
    }

    // Promote this frame's content into ``in_flight_slot`` (same slot the
    // compositor passes to record()/get_wait_semaphores) and return the
    // per-view source images to copy. Empty vector = nothing fresh to
    // present this frame (backend clears the swapchains). Called instead
    // of record_pre_render_pass()/record() on the direct path.
    virtual std::vector<DirectPresentView> acquire_direct_views(uint32_t /*in_flight_slot*/)
    {
        return {};
    }

    // Native OpenXR composition-layer support (see NativeLayerView). When
    // true, the compositor — on a backend that supports_native_layers() —
    // routes this layer through acquire_native_layer()/record_native_layers()
    // instead of record(), and DROPS the shared projection layer for frames
    // where every visible layer is native (unlocking the runtime's layer fast
    // path). A layer WITH a composite fallback (QuadLayer) must return false
    // unless it is in a kXr session, so the window/offscreen fallback still
    // uses record(); native-only layers return true unconditionally and are
    // rejected at add_layer on unsupported backends (required_native_shape).
    // Default: not native.
    virtual bool is_native_layer() const noexcept
    {
        return false;
    }

    // Promote this frame's content into ``in_flight_slot`` (same slot the
    // compositor passes to get_wait_semaphores()) and return the native
    // layer descriptor. nullopt = nothing fresh to composite this frame (no
    // publish yet) — the backend submits no layer for this frame. Called
    // instead of record_pre_render_pass()/record() on the native path.
    virtual std::optional<NativeLayerView> acquire_native_layer(uint32_t /*in_flight_slot*/)
    {
        return std::nullopt;
    }

    // Shape this layer REQUIRES the backend to composite natively, or
    // nullopt when the layer has a composite fallback (QuadLayer) / isn't
    // native at all. add_layer rejects the layer up front when the backend
    // can't composite the shape (non-XR session, or the runtime lacks the
    // XR_KHR_composition_layer_* extension) — better than failing on the
    // first frame.
    virtual std::optional<NativeLayerShape> required_native_shape() const noexcept
    {
        return std::nullopt;
    }

    // Let a layer reject a backend it can't run on. Called once by add_layer
    // with the backend's per-view recommended resolution, view count (1
    // window/offscreen, 2 kXr stereo), and in-flight image count; throws
    // std::invalid_argument on mismatch. Default: no requirements.
    virtual void validate_backend_compatibility(Resolution /*recommended_view_resolution*/,
                                                uint32_t /*backend_view_count*/,
                                                uint32_t /*backend_image_count*/) const
    {
    }

    // Window-mode aspect-fit hint. nullopt = fill the tile; kXr ignores.
    virtual std::optional<float> aspect_ratio() const noexcept
    {
        return std::nullopt;
    }

    const std::string& name() const noexcept;

    // Non-owning back-pointer set by VizSession::add_layer. Null before
    // attach (layers may be constructed standalone for tests). Layers
    // reach through this for display mode, XR handles, time conversion.
    const VizSession* session() const noexcept
    {
        return session_;
    }

    // Atomic so toggles from any thread don't race the per-frame
    // is_visible() check. Relaxed: a toggle that races a frame may be
    // observed on the next frame instead — desired semantics.
    bool is_visible() const noexcept;
    void set_visible(bool visible) noexcept;

private:
    friend class VizSession;
    void attach_to_session_(VizSession* session) noexcept
    {
        session_ = session;
    }

    std::string name_;
    std::atomic<bool> visible_{ true };
    VizSession* session_ = nullptr;
};

inline LayerBase::LayerBase(std::string name) : name_(std::move(name))
{
}

inline const std::string& LayerBase::name() const noexcept
{
    return name_;
}

inline bool LayerBase::is_visible() const noexcept
{
    return visible_.load(std::memory_order_relaxed);
}

inline void LayerBase::set_visible(bool visible) noexcept
{
    visible_.store(visible, std::memory_order_relaxed);
}

} // namespace viz
