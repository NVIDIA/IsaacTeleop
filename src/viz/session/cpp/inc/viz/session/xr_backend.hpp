// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "display_backend.hpp"

#include <openxr/openxr.h>
#include <viz/xr/openxr_session.hpp>

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace viz
{

// OpenXR display backend. Owns the OpenXrSession + per-view XrSwapchain
// handles, plus one wide intermediate RenderTarget the compositor writes
// into; record_post_render_pass blits per-eye regions into per-eye
// swapchain images.
//
// Two-phase init mirrors OpenXrSession's stages: ctor creates the
// XrInstance + system (so VkContext can use the XR-bound Vulkan
// creation path), init() attaches graphics + creates swapchains + RT
// once VkContext is ready. VizSession orchestrates.
class XrBackend final : public DisplayBackend
{
public:
    struct Config
    {
        std::string app_name = "Televiz";
        // Extra OpenXR instance extensions on top of XR_KHR_VULKAN_ENABLE2.
        std::vector<std::string> extra_xr_extensions;
        // Seconds to keep polling xrGetSystem when the runtime returns
        // XR_ERROR_FORM_FACTOR_UNAVAILABLE (no HMD yet). Useful for
        // CloudXR / streaming runtimes where the headset connects after
        // the app starts.
        //   0  → fail fast on first failure (default; tests / CI)
        //   >0 → bounded wait
        //   <0 → wait forever (Ctrl-C to break)
        int system_wait_seconds = 0;
        // Underlying session config (reference space type, blend mode).
        OpenXrSession::Config session_config{};
    };

    explicit XrBackend(Config config);
    ~XrBackend() override;

    // Raw XR handles for VkContext::Config's XR-bound init path. Both
    // available after ctor; session-level state isn't ready until init().
    XrInstance xr_instance_handle() const noexcept;
    XrSystemId xr_system_id() const noexcept;

    void init(const VkContext& ctx, Resolution preferred_size) override;
    void destroy();

    bool is_xr() const noexcept override
    {
        return true;
    }

    std::optional<Frame> begin_frame(int64_t /*ignored*/) override;
    const RenderTarget& render_target() const override;
    void record_post_render_pass(VkCommandBuffer cmd, const Frame& frame) override;
    void end_frame(const Frame& frame) override;
    void abort_frame(const Frame& frame) override;

    void poll_events() override;
    bool should_close() const override;
    Resolution current_extent() const override;
    uint32_t image_count() const override;

    // Backend-internal handle bundle. VizSession::get_oxr_handles()
    // converts this to core::OpenXRSessionHandles for cross-module
    // sharing (drops view_space, renames reference_space → space).
    // view_space is used internally by head_pose_now(): locate against
    // reference_space at any XrTime to get the head pose.
    struct OxrHandles
    {
        XrInstance instance = XR_NULL_HANDLE;
        XrSession session = XR_NULL_HANDLE;
        XrSpace reference_space = XR_NULL_HANDLE;
        XrSpace view_space = XR_NULL_HANDLE;
        PFN_xrGetInstanceProcAddr xrGetInstanceProcAddr = nullptr;
    };
    OxrHandles oxr_handles() const noexcept;

    // VizSession reaches in for time conversion and head-pose
    // forwarding. Null after destroy().
    const OpenXrSession* xr_session() const noexcept
    {
        return session_.get();
    }

private:
    // Per-view OpenXR swapchain. `acquired` is set immediately after
    // xrAcquireSwapchainImage success (before wait); cleared after
    // release. Lets abort/cleanup release ONLY images we actually got,
    // even on partial-acquire mid-loop.
    struct ViewSwapchain
    {
        XrSwapchain handle = XR_NULL_HANDLE;
        std::vector<VkImage> images; // owned by the XR runtime
        uint32_t current_image_index = 0;
        uint32_t width = 0;
        uint32_t height = 0;
        bool acquired = false;
    };

    int64_t pick_swapchain_format() const;
    int64_t pick_depth_swapchain_format() const;
    void create_swapchains();
    void create_depth_swapchains();
    void destroy_swapchains();
    void create_intermediate();

    // Release every swapchain currently flagged `acquired`.
    void release_acquired_swapchains() noexcept;
    // Submit an empty xrEndFrame to balance an outstanding xrBeginFrame.
    // Idempotent. Clears frame_began_ before the runtime call so a
    // stacked unwind can't re-enter; swallows runtime errors.
    void abort_in_flight_frame() noexcept;

    Config config_;
    const VkContext* ctx_ = nullptr;

    std::unique_ptr<OpenXrSession> session_;
    std::unique_ptr<RenderTarget> render_target_;

    int64_t swapchain_format_ = 0; // VkFormat as int64 (XR's typing)
    int64_t depth_swapchain_format_ = 0; // 0 = depth submission disabled
    std::vector<ViewSwapchain> view_swapchains_;
    // Per-eye depth swapchains, allocated only when the runtime supports
    // XR_KHR_composition_layer_depth. record_post_render_pass copies the
    // intermediate's depth into them and end_frame chains them via
    // XrCompositionLayerDepthInfoKHR for runtime reprojection.
    std::vector<ViewSwapchain> depth_swapchains_;
    bool depth_layer_enabled_ = false;

    // Per-frame state — valid only while frame_began_ == true.
    XrFrameState last_frame_state_{ XR_TYPE_FRAME_STATE };
    XrViewState last_view_state_{ XR_TYPE_VIEW_STATE };
    std::vector<XrView> last_views_;
    bool frame_began_ = false;
    bool frame_renderable_ = false; // false on shouldRender=0 / locate failure
    // Monotonic counter that drives Frame::backend_token; the contract
    // (display_backend.hpp) requires 0..image_count()-1, which the
    // compositor then mods by its slot count. Image_count is 1 today
    // (single-frame-in-flight on XR) but this keeps the invariant
    // explicit for future multi-slot work.
    uint64_t frame_index_ = 0;
};

} // namespace viz
