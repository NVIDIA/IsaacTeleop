// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/viz_types.hpp>
#include <viz/core/vk_context.hpp>
#include <viz/layers/layer_base.hpp>
#include <viz/session/frame_info.hpp>
#include <viz/session/viz_compositor.hpp>

#include <chrono>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace viz
{

// Display backend selection at session creation time.
//
// kOffscreen is the only mode implemented today; readback_to_host() is
// the primary output. kWindow (GLFW) and kXr (OpenXR + CloudXR) ship
// with the window-mode and XR-mode milestones respectively.
enum class DisplayMode
{
    kOffscreen,
    kWindow,
    kXr,
};

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

// VizSession: the central object. Owns the Vulkan context, the
// compositor, and the layer registry. One VizSession per display
// surface (one window, one XR session, or one offscreen target).
//
// Frame loop, two API levels:
//   - render() — convenience for "wait + composite + present" in one
//     call. Returns the FrameInfo for the just-rendered frame.
//   - begin_frame() / end_frame() — explicit pair for callers that need
//     FrameInfo before submitting (e.g. to make per-frame decisions
//     about what to render).
//
// State machine: kUninitialized -> kReady (after create) -> kRunning
// (after first render/begin_frame) -> kDestroyed (after destroy).
// XR-only states (kStopping, kLost) ship with the XR backend.
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
        // Layers render on top of this. Defaults to opaque black.
        float clear_color[4] = { 0.0f, 0.0f, 0.0f, 1.0f };

        // Optional pre-built Vulkan context. If null, the session creates
        // its own VkContext. Pass an externally-owned ctx (heap or static)
        // when sharing the device with another component.
        VkContext* external_context = nullptr;

        // OpenXR instance extensions to enable beyond Televiz's required
        // set. Used in kXr mode by the XR backend (no effect in
        // kOffscreen / kWindow today).
        std::vector<std::string> required_extensions;
    };

    static std::unique_ptr<VizSession> create(const Config& config);

    ~VizSession();
    void destroy();

    VizSession(const VizSession&) = delete;
    VizSession& operator=(const VizSession&) = delete;
    VizSession(VizSession&&) = delete;
    VizSession& operator=(VizSession&&) = delete;

    // Layer management. Insertion order is render order. Returns a raw
    // pointer to the layer for content updates / set_visible(). The
    // session owns the layer's lifetime.
    template <typename L, typename... Args>
    L* add_layer(Args&&... args)
    {
        auto layer = std::make_unique<L>(std::forward<Args>(args)...);
        L* raw = layer.get();
        layers_.push_back(std::move(layer));
        return raw;
    }

    // Removes a layer by pointer. No-op if `layer` is not registered.
    void remove_layer(LayerBase* layer);

    // Convenience frame loop: wait + composite + (in window/XR) present.
    // Returns the FrameInfo for the just-rendered frame.
    FrameInfo render();

    // Explicit frame-loop pair. begin_frame returns FrameInfo for the
    // upcoming frame; end_frame composites + presents. Application code
    // can inspect FrameInfo (e.g. `should_render`, `views`) between
    // begin_frame and end_frame to decide what to draw.
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

    // Read the most recent composited frame as host-side RGBA8 bytes
    // (width * height * 4). Defined in kOffscreen; throws in kWindow /
    // kXr (use the swapchain present path there). Test / debug grade —
    // the production CUDA-pointer readback returning a VizBuffer ships
    // with CUDA-Vulkan interop.
    std::vector<uint8_t> readback_to_host();

    // Vulkan handle accessors for external renderers and custom layers
    // that need to build pipelines against the compositor's render pass.
    VkDevice get_vk_device() const noexcept;
    VkPhysicalDevice get_vk_physical_device() const noexcept;
    uint32_t get_vk_queue_family_index() const noexcept;
    VkRenderPass get_render_pass() const noexcept;

private:
    explicit VizSession(const Config& config);
    void init();

    const VkContext& ctx() const noexcept;
    void update_timing_stats(float frame_time_seconds);

    Config config_{};

    // Either we own a VkContext or we hold a borrowed pointer.
    std::unique_ptr<VkContext> owned_ctx_;
    VkContext* ctx_ptr_ = nullptr;

    std::unique_ptr<VizCompositor> compositor_;
    std::vector<std::unique_ptr<LayerBase>> layers_;

    SessionState state_ = SessionState::kUninitialized;
    uint64_t frame_index_ = 0;
    std::chrono::steady_clock::time_point last_frame_time_{};
    bool first_frame_ = true;
    FrameInfo current_frame_info_{};
    FrameTimingStats timing_stats_{};
};

} // namespace viz
