// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>
#include <viz/session/display_backend.hpp>
#include <viz/xr/openxr_session.hpp>

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace viz
{

class OpenXrInstance;

// OpenXR display backend. Owns the OpenXrInstance + OpenXrSession +
// per-view XrSwapchain handles, plus a single intermediate RenderTarget
// the compositor writes into.
//
// Phase 1 = monoscopic-into-stereo: the compositor renders ONE image
// at one eye's recommended resolution into the intermediate; we blit
// it into BOTH eyes' XR swapchain images and submit one composition
// layer with two ProjectionViews (one per eye, each with its own
// pose / FOV from xrLocateViews, both subImages pointing at their
// own swapchain). True per-eye rendering (parallax, ProjectionLayer
// with depth) lands with Phase 2 — at that point the intermediate
// becomes per-view and record_post_render_pass blits view-by-view.
//
// Two-phase init: XrBackend's constructor creates the OpenXrInstance
// (so VkContext can use it for xrCreateVulkanInstanceKHR/DeviceKHR),
// and init() creates the session + swapchains + RT after VkContext
// is ready. VizSession orchestrates the order.
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

    // For VkContext::Config — VkContext's XR-bound init path needs
    // the raw XR handles. Available after construction (XrInstance is
    // created by the ctor); session-level handles are nullptr until init().
    XrInstance xr_instance_handle() const noexcept;
    XrSystemId xr_system_id() const noexcept;

    void init(const VkContext& ctx, Resolution preferred_size) override;
    void destroy();

    std::optional<Frame> begin_frame(int64_t /*ignored*/) override;
    const RenderTarget& render_target() const override;
    void record_post_render_pass(VkCommandBuffer cmd, const Frame& frame) override;
    void end_frame(const Frame& frame) override;
    void abort_frame(const Frame& frame) override;

    void poll_events() override;
    bool should_close() const override;
    Resolution current_extent() const override;

    // OpenXR session handles for app-side TeleopSession sharing. The
    // returned xrGetInstanceProcAddr is the loader-level entry, valid
    // for the lifetime of this backend.
    struct OxrHandles
    {
        XrInstance instance = XR_NULL_HANDLE;
        XrSession session = XR_NULL_HANDLE;
        XrSpace reference_space = XR_NULL_HANDLE;
        // VIEW reference space — locate against reference_space at any
        // XrTime to get the head pose. Apps doing head-locked / lazy-lock
        // placement use this instead of computing pose from per-eye views.
        XrSpace view_space = XR_NULL_HANDLE;
        PFN_xrGetInstanceProcAddr xrGetInstanceProcAddr = nullptr;
    };
    OxrHandles oxr_handles() const noexcept;

    // Underlying OpenXrInstance — exposed for time-conversion forwarding
    // and (eventually) richer extension queries. May be null between
    // ctor and session creation; never null in steady state.
    const OpenXrInstance* xr_instance() const noexcept
    {
        return xr_instance_.get();
    }

private:
    // Per-view OpenXR swapchain. Bundle, not a class — see decision
    // notes in the M5 design discussion: this state is tightly coupled
    // to XrBackend's frame loop and has no independent lifetime.
    struct ViewSwapchain
    {
        XrSwapchain handle = XR_NULL_HANDLE;
        std::vector<VkImage> images; // owned by the XR runtime
        uint32_t current_image_index = 0;
        uint32_t width = 0;
        uint32_t height = 0;
    };

    int64_t pick_swapchain_format() const;
    int64_t pick_depth_swapchain_format() const;
    void create_swapchains();
    void create_depth_swapchains();
    void destroy_swapchains();
    void create_intermediate();

    Config config_;
    const VkContext* ctx_ = nullptr;

    std::unique_ptr<OpenXrInstance> xr_instance_;
    std::unique_ptr<OpenXrSession> session_;
    std::unique_ptr<RenderTarget> render_target_;

    int64_t swapchain_format_ = 0; // VkFormat as int64 (XR's typing)
    int64_t depth_swapchain_format_ = 0; // 0 = depth submission disabled
    std::vector<ViewSwapchain> view_swapchains_;
    // Per-eye depth swapchains, present iff XR_KHR_composition_layer_depth
    // is available on the runtime. Same dimensions as the color swapchains;
    // per frame we copy the intermediate's depth attachment into them and
    // chain XrCompositionLayerDepthInfoKHR into each ProjectionView.next
    // for CloudXR-style server-side reprojection.
    std::vector<ViewSwapchain> depth_swapchains_;
    bool depth_layer_enabled_ = false;

    // Per-frame state captured in begin_frame, consumed in
    // end_frame / abort_frame. Only valid when frame_began_ == true.
    XrFrameState last_frame_state_{ XR_TYPE_FRAME_STATE };
    XrViewState last_view_state_{ XR_TYPE_VIEW_STATE };
    std::vector<XrView> last_views_;
    bool frame_began_ = false;
    bool frame_renderable_ = false; // false iff shouldRender=0 or locate failed
};

} // namespace viz
