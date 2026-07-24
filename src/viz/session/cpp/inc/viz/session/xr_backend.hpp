// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "display_backend.hpp"

#include <openxr/openxr.h>
#include <viz/xr/openxr_session.hpp>

#include <cstdint>
#include <map>
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

    // Direct-present: copy a ProjectionLayer's per-eye color/depth straight
    // into the per-eye color + depth swapchains (vkCmdCopyImage, verbatim),
    // skipping the shared RT — so the renderer's depth reaches CloudXR
    // exactly. Per-eye recommended size keeps the copy 1:1.
    bool supports_direct() const noexcept override
    {
        return true;
    }
    void record_direct(VkCommandBuffer cmd, const Frame& frame, const std::vector<DirectPresentView>& views) override;
    Resolution recommended_view_resolution() const override;

    // Native OpenXR quad layers (XrCompositionLayerQuad). Copies each
    // NativeQuadView's source image(s) into a per-quad color swapchain and
    // records the submission for end_frame; quad-only frames drop the shared
    // projection layer (see projection_active_).
    bool supports_native_quad() const noexcept override
    {
        return true;
    }
    void record_native_quads(VkCommandBuffer cmd, const Frame& frame, const std::vector<NativeQuadView>& views) override;

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

    // Native-quad color swapchain(s) for one QuadLayer: 1 (mono) or 2
    // (stereo, [left, right]). Created lazily on first submission, keyed by
    // the layer's stable source_id, reused each frame.
    struct NativeQuadSwapchain
    {
        std::vector<ViewSwapchain> eyes; // 1 mono, 2 stereo
    };
    // Ensure (lazily create) the quad swapchain(s) for ``key`` sized to
    // ``extent`` with ``eye_count`` eyes; returns the cached entry.
    NativeQuadSwapchain& ensure_native_quad_swapchain(const void* key, Resolution extent, uint32_t eye_count);
    void destroy_native_quad_swapchains();

    // Per-eye staging buffers that bridge a direct ProjectionLayer's depth
    // (stored as R32_SFLOAT — CUDA can't interop a depth-format image) into
    // the D32_SFLOAT depth swapchain via image->buffer->image. The float bits
    // copy verbatim. Allocated only when depth submission is enabled.
    void create_depth_staging();
    void destroy_depth_staging() noexcept;

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

    // Persistent per-QuadLayer native-quad swapchains, keyed by the layer's
    // source_id. Created lazily in record_native_quads, destroyed with the
    // backend. (Removing a native quad layer mid-session leaves its
    // swapchain allocated until destroy — layer removal is rare.)
    std::map<const void*, NativeQuadSwapchain> native_quad_swapchains_;

    // One XrCompositionLayerQuad to submit this frame. Storage for the
    // built XrCompositionLayerQuad lives in end_frame; this holds the
    // inputs record_native_quads gathered. eye_visibility selects the eye
    // (BOTH for mono).
    struct NativeQuadSubmit
    {
        XrSwapchain swapchain = XR_NULL_HANDLE;
        uint32_t width = 0;
        uint32_t height = 0;
        XrPosef pose{};
        XrExtent2Df size{};
        XrEyeVisibility eye_visibility = XR_EYE_VISIBILITY_BOTH;
    };
    std::vector<NativeQuadSubmit> active_native_quads_;

    // Per-eye R32_SFLOAT->D32_SFLOAT bridge buffers (see create_depth_staging).
    struct DepthStaging
    {
        VkBuffer buffer = VK_NULL_HANDLE;
        VkDeviceMemory memory = VK_NULL_HANDLE;
        VkDeviceSize size = 0;
    };
    std::vector<DepthStaging> depth_staging_;

    // Per-frame state — valid only while frame_began_ == true.
    XrFrameState last_frame_state_{ XR_TYPE_FRAME_STATE };
    XrViewState last_view_state_{ XR_TYPE_VIEW_STATE };
    std::vector<XrView> last_views_;
    bool frame_began_ = false;
    bool frame_renderable_ = false; // false on shouldRender=0 / locate failure
    // Set when the shared render pass (record_post_render_pass) or the
    // direct path (record_direct) produced content for the projection
    // layer this frame. When false at end_frame (every visible layer was a
    // native quad), the projection layer is dropped so the runtime sees a
    // quad-only frame and can engage its client-reconstructed path.
    bool projection_active_ = false;
    // Monotonic counter that drives Frame::backend_token; the contract
    // (display_backend.hpp) requires 0..image_count()-1, which the
    // compositor then mods by its slot count. Image_count is 1 today
    // (single-frame-in-flight on XR) but this keeps the invariant
    // explicit for future multi-slot work.
    uint64_t frame_index_ = 0;
};

} // namespace viz
