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

    // Hard requirements a layer places on the backend it's attached to.
    // Called once by VizSession::add_layer with the backend's per-view
    // recommended resolution, view count (1 window/offscreen, 2 kXr
    // stereo), and in-flight image count. Direct-present layers override
    // this to fail fast (std::invalid_argument) when a 1:1 swapchain copy
    // would be impossible (size/stereo/slot mismatch). Default: no
    // requirements.
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
