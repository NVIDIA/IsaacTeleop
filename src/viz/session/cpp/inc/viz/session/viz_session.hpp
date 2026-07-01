// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "display_mode.hpp"
#include "frame_info.hpp"
#include "layer_base.hpp"
#include "viz_compositor.hpp"

#include <oxr_utils/oxr_session_handles.hpp>
#include <viz/core/host_image.hpp>
#include <viz/core/viz_types.hpp>
#include <viz/core/vk_context.hpp>

#include <chrono>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace viz
{

class DisplayBackend;

// Lifecycle states for a VizSession. The full set covers XR; window /
// offscreen modes only transition through:
//   kUninitialized -> kReady -> kRunning -> kDestroyed
//
// XR adds kStopping (session stopping per OpenXR runtime) and kLost
// (session lost — must destroy and recreate). See the design doc for
// the full OpenXR-state-to-VizSession-state mapping.
enum class SessionState
{
    kUninitialized, // Before create()
    kReady, // Vulkan + display initialized; layers can be added
    kRunning, // Frame loop active
    kStopping, // XR only: session is stopping; end_frame submits empty
    kLost, // XR only: session lost; must destroy and recreate
    kDestroyed, // After destroy(); no operations valid
};

// VizSession: owns the Vulkan context, compositor, and layer registry.
// One per display surface (window / XR session / offscreen target).
//
// Frame loop:
//   render()                      — wait + composite + present in one call.
//   begin_frame() / end_frame()   — explicit pair when the caller needs
//                                   FrameInfo before submitting.
class VizSession
{
public:
    struct Config
    {
        DisplayMode mode = DisplayMode::kOffscreen;
        uint32_t window_width = 1024;
        uint32_t window_height = 1024;
        std::string app_name = "televiz";

        // Initial clear color for the framebuffer (RGBA, [0..1] each).
        // Layers render on top of this. Defaults to transparent — the
        // XR compositor and most window managers blend behind us, so
        // alpha=0 lets a non-opaque background show through.
        float clear_color[4] = { 0.0f, 0.0f, 0.0f, 0.0f };

        // Optional pre-built Vulkan context. If non-null, MUST already
        // have the backend's extensions enabled (VK_KHR_swapchain +
        // surface for kWindow, OpenXR-Vulkan for kXr) — backend init
        // doesn't retroactively enable them.
        VkContext* external_context = nullptr;

        // Extra OpenXR instance extensions (kXr only).
        std::vector<std::string> required_extensions;

        // kXr-only: poll xrGetSystem on FORM_FACTOR_UNAVAILABLE.
        //   0  → fail fast (default; CI / tests).
        //   >0 → bounded wait, then throw.
        //   <0 → wait forever (Ctrl-C to break).
        int xr_system_wait_seconds = 0;

        // kXr-only: reverse-Z near/far in meters. Drives per-eye
        // projection matrices AND XrCompositionLayerDepthInfoKHR; the
        // two MUST match for runtime reprojection.
        float xr_near_z = 0.05f;
        float xr_far_z = 100.0f;

        // Opt-in GPU timestamp queries (render-pass, post-pass, total).
        // Off by default — production builds shouldn't pay. Read via
        // get_gpu_timing().
        bool gpu_timing = false;
    };

    static std::unique_ptr<VizSession> create(const Config& config);

    ~VizSession();
    void destroy();

    VizSession(const VizSession&) = delete;
    VizSession& operator=(const VizSession&) = delete;
    VizSession(VizSession&&) = delete;
    VizSession& operator=(VizSession&&) = delete;

    // Insertion order = render order. Returns a non-owning pointer for
    // content updates / set_visible(). The session owns the layer's
    // lifetime. add_layer / remove_layer must run on the same thread
    // as the frame loop; only LayerBase::set_visible() is atomic.
    //
    // Layer-mode invariant (for now): a session holds EITHER one
    // ProjectionLayer OR any number of QuadLayers, never both. The
    // ProjectionLayer is direct-present (copied straight to the swapchain),
    // while QuadLayers composite into the shared render target — the two
    // paths don't coexist yet. Violations throw std::invalid_argument.
    template <typename L, typename... Args>
    L* add_layer(Args&&... args)
    {
        // Layers may only be added to a live session. After destroy() the
        // backend + context are gone (validate_layer_against_backend_ would
        // no-op), so without this guard a layer could attach to a dead session.
        if (state_ != SessionState::kReady && state_ != SessionState::kRunning)
        {
            throw std::logic_error("VizSession: add_layer requires an active session (kReady or kRunning)");
        }
        auto layer = std::make_unique<L>(std::forward<Args>(args)...);
        L* raw = layer.get();

        bool have_projection = false;
        for (const auto& l : layers_)
        {
            have_projection = have_projection || l->is_projection_layer();
        }
        if (raw->is_projection_layer() && !layers_.empty())
        {
            throw std::invalid_argument("VizSession: a ProjectionLayer must be the session's only layer");
        }
        if (!raw->is_projection_layer() && have_projection)
        {
            throw std::invalid_argument("VizSession: cannot add another layer alongside a ProjectionLayer");
        }

        // Let the layer reject a backend it can't run on (e.g. a direct-present
        // layer whose resolution/stereo/slot count doesn't match). Throws
        // before the layer is registered, so a rejected add leaves no state.
        validate_layer_against_backend_(raw);

        raw->attach_to_session_(this);
        layers_.push_back(std::move(layer));
        return raw;
    }

    // No-op if `layer` isn't registered. Same threading contract as
    // add_layer.
    void remove_layer(LayerBase* layer);

    // wait + composite + present in one call.
    FrameInfo render();

    // Explicit frame-loop pair: inspect FrameInfo between calls to
    // decide what to draw.
    FrameInfo begin_frame();
    void end_frame();

    SessionState get_state() const noexcept
    {
        return state_;
    }
    Resolution get_recommended_resolution() const noexcept;
    FrameTimingStats get_frame_timing_stats() const noexcept
    {
        return timing_stats_;
    }

    // Most-recent frame as host RGBA8. kOffscreen only; kWindow/kXr
    // throw — use the swapchain present path there.
    HostImage readback_to_host();

    // Vulkan handles for layers building their own pipelines.
    VkDevice get_vk_device() const noexcept;
    VkPhysicalDevice get_vk_physical_device() const noexcept;
    uint32_t get_vk_queue_family_index() const noexcept;
    VkRenderPass get_render_pass() const noexcept;
    const VkContext* get_vk_context() const noexcept;

    // True when the display target has been asked to close (window-X
    // clicked, etc.). Always false in kOffscreen / kXr.
    bool should_close() const noexcept;

    bool is_xr_mode() const noexcept
    {
        return config_.mode == DisplayMode::kXr;
    }

    // OpenXR handles for downstream consumers (e.g. TeleopSession)
    // that need to share this session. nullopt outside kXr.
    std::optional<core::OpenXRSessionHandles> get_oxr_handles() const noexcept;

    // XR_KHR_convert_timespec_time forwarding (kXr only). Throws on
    // non-kXr or when the extension isn't enabled — check has_*()
    // first if unsure.
    bool has_xr_time_conversion() const noexcept;
    std::chrono::steady_clock::time_point xr_time_to_steady_clock(int64_t xr_time) const;
    int64_t steady_clock_to_xr_time(std::chrono::steady_clock::time_point t) const;

    // Current head pose in the reference space (kXr only). Throws on
    // non-kXr. Returns nullopt without time-conversion or on tracking loss.
    std::optional<Pose3D> head_pose_now() const;

    // Most recent GPU timestamp deltas. Zeros unless gpu_timing was
    // enabled and at least one render() has completed.
    const VizCompositor::GpuFrameTiming& get_gpu_timing() const noexcept;

private:
    explicit VizSession(const Config& config);
    void init();

    const VkContext& ctx() const noexcept;
    // Ask a freshly-constructed layer to validate itself against the active
    // backend (resolution / stereo / in-flight count). No-op until the
    // backend is initialized. Throws std::invalid_argument on mismatch.
    void validate_layer_against_backend_(LayerBase* layer) const;
    void update_timing_stats(float frame_time_seconds);
    // Poll backend events + handle resize. Called by render() and
    // begin_frame() so explicit-loop users get the same behavior.
    void pump_events();

    Config config_{};

    // Either we own a VkContext or we hold a borrowed pointer.
    std::unique_ptr<VkContext> owned_ctx_;
    VkContext* ctx_ptr_ = nullptr;

    // Display backend (picked from config_.mode at init). Owns mode-
    // specific resources. Must outlive compositor_ (compositor holds
    // a non-owning ref) and is destroyed before the VkContext.
    std::unique_ptr<DisplayBackend> backend_;

    std::unique_ptr<VizCompositor> compositor_;
    std::vector<std::unique_ptr<LayerBase>> layers_;

    SessionState state_ = SessionState::kUninitialized;
    uint64_t frame_index_ = 0;
    std::chrono::steady_clock::time_point last_frame_time_{};
    bool first_frame_ = true;
    bool frame_in_progress_ = false;
    FrameInfo current_frame_info_{};
    // The backend-acquired frame for the in-progress begin/end pair.
    // Acquired by begin_frame, consumed by end_frame. nullopt outside
    // a begin/end window or when the backend skipped this frame
    // (e.g. XR runtime shouldRender=0).
    std::optional<DisplayBackend::Frame> current_backend_frame_;
    FrameTimingStats timing_stats_{};
};

} // namespace viz
