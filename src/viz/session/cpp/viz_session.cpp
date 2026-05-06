// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/session/display_backend.hpp>
#include <viz/session/offscreen_backend.hpp>
#include <viz/session/viz_session.hpp>
#include <viz/session/window_backend.hpp>
#include <viz/session/xr_backend.hpp>

#include <algorithm>
#include <stdexcept>

namespace viz
{

namespace
{

// Factory: instantiate the backend matching the requested mode.
std::unique_ptr<DisplayBackend> make_backend(const VizSession::Config& cfg)
{
    switch (cfg.mode)
    {
    case DisplayMode::kOffscreen:
        return std::make_unique<OffscreenBackend>();
    case DisplayMode::kWindow:
    {
        WindowBackend::Config wc{};
        wc.width = cfg.window_width;
        wc.height = cfg.window_height;
        wc.title = cfg.app_name;
        return std::make_unique<WindowBackend>(wc);
    }
    case DisplayMode::kXr:
    {
        XrBackend::Config xc{};
        xc.app_name = cfg.app_name;
        xc.extra_xr_extensions = cfg.required_extensions;
        xc.system_wait_seconds = cfg.xr_system_wait_seconds;
        return std::make_unique<XrBackend>(std::move(xc));
    }
    }
    throw std::runtime_error("VizSession: unknown DisplayMode");
}

} // namespace

std::unique_ptr<VizSession> VizSession::create(const Config& config)
{
    if (config.window_width == 0 || config.window_height == 0)
    {
        throw std::invalid_argument("VizSession: window dimensions must be non-zero");
    }
    std::unique_ptr<VizSession> s(new VizSession(config));
    s->init();
    return s;
}

VizSession::VizSession(const Config& config) : config_(config)
{
}

VizSession::~VizSession()
{
    destroy();
}

void VizSession::init()
{
    // Backend first — it dictates the required Vulkan extensions and
    // rejects unsupported modes before any Vulkan work.
    backend_ = make_backend(config_);

    try
    {
        VkContext::Config vk_cfg{};
        vk_cfg.instance_extensions = backend_->required_instance_extensions();
        vk_cfg.device_extensions = backend_->required_device_extensions();

        // kXr two-phase init: XrBackend's ctor already created the
        // OpenXrInstance, so we can hand the raw XR handles to VkContext
        // before it builds its instance/device. VkContext takes the
        // xrCreateVulkanInstanceKHR / xrCreateVulkanDeviceKHR path,
        // which lets the OpenXR runtime interpose on Vulkan creation.
        if (config_.mode == DisplayMode::kXr)
        {
            auto* xr = static_cast<XrBackend*>(backend_.get());
            vk_cfg.xr_instance = xr->xr_instance_handle();
            vk_cfg.xr_system_id = xr->xr_system_id();
        }

        if (config_.external_context != nullptr)
        {
            if (!config_.external_context->is_initialized())
            {
                throw std::invalid_argument("VizSession: external_context is not initialized");
            }
            ctx_ptr_ = config_.external_context;
        }
        else
        {
            owned_ctx_ = std::make_unique<VkContext>();
            owned_ctx_->init(vk_cfg);
            ctx_ptr_ = owned_ctx_.get();
        }

        backend_->init(*ctx_ptr_, Resolution{ config_.window_width, config_.window_height });

        VizCompositor::Config c_cfg{};
        c_cfg.clear_color = { { config_.clear_color[0], config_.clear_color[1], config_.clear_color[2],
                                config_.clear_color[3] } };
        compositor_ = VizCompositor::create(*ctx_ptr_, *backend_, c_cfg);

        state_ = SessionState::kReady;
    }
    catch (...)
    {
        destroy();
        throw;
    }
}

void VizSession::destroy()
{
    // If teardown happens with a frame still in progress (app threw
    // between begin_frame and end_frame, or simply destroys the
    // session mid-frame), abort it so the backend's protocol stays
    // balanced (XR's xrBeginFrame/xrEndFrame pairing in particular).
    if (frame_in_progress_ && cached_frame_ && backend_)
    {
        try
        {
            backend_->abort_frame(*cached_frame_);
        }
        catch (...)
        {
            // Quiet — destroy must not throw.
        }
    }
    cached_frame_.reset();
    frame_in_progress_ = false;

    layers_.clear();
    // Order: compositor (holds backend ref) -> backend -> context.
    compositor_.reset();
    backend_.reset();
    if (owned_ctx_)
    {
        owned_ctx_.reset();
    }
    ctx_ptr_ = nullptr;
    state_ = SessionState::kDestroyed;
}

void VizSession::remove_layer(LayerBase* layer)
{
    if (layer == nullptr)
    {
        return;
    }
    auto it = std::remove_if(
        layers_.begin(), layers_.end(), [layer](const std::unique_ptr<LayerBase>& p) { return p.get() == layer; });
    layers_.erase(it, layers_.end());
}

void VizSession::pump_events()
{
    if (!backend_)
    {
        return;
    }
    backend_->poll_events();
    if (backend_->consume_resized())
    {
        // Hint ignored — backend reads its own framebuffer size.
        backend_->resize(Resolution{});
    }
}

FrameInfo VizSession::begin_frame()
{
    if (state_ == SessionState::kDestroyed || state_ == SessionState::kLost)
    {
        throw std::runtime_error("VizSession: begin_frame called on destroyed/lost session");
    }
    if (frame_in_progress_)
    {
        throw std::logic_error(
            "VizSession: begin_frame called while a frame is already in "
            "progress (missing end_frame for previous begin_frame)");
    }
    pump_events();
    if (state_ == SessionState::kReady)
    {
        state_ = SessionState::kRunning;
    }

    const auto now = std::chrono::steady_clock::now();
    if (first_frame_)
    {
        current_frame_info_.delta_time = 0.0f;
        first_frame_ = false;
    }
    else
    {
        current_frame_info_.delta_time = std::chrono::duration<float>(now - last_frame_time_).count();
    }
    last_frame_time_ = now;

    current_frame_info_.frame_index = frame_index_;
    current_frame_info_.resolution = compositor_ ? compositor_->resolution() : Resolution{};

    // Acquire next frame from the backend. For kXr this BLOCKS in
    // xrWaitFrame — pacing happens here, at the API's stated start
    // of frame, so the app can read predicted_display_time and time
    // its work between begin_frame and end_frame to display.
    cached_frame_.reset();
    if (backend_ && state_ == SessionState::kRunning)
    {
        cached_frame_ = backend_->begin_frame(/*predicted_display_time hint*/ 0);
    }

    if (cached_frame_)
    {
        current_frame_info_.predicted_display_time = cached_frame_->predicted_display_time;
        current_frame_info_.should_render = true;
        // Surface real per-view info (XR: 2 entries with eye viewports;
        // window/offscreen: 1 entry filling the intermediate).
        current_frame_info_.views = cached_frame_->views;
        if (current_frame_info_.views.empty())
        {
            current_frame_info_.views.assign(1, ViewInfo{});
        }
    }
    else
    {
        // Backend skipped this frame (XR session not yet running,
        // window minimized, etc.). end_frame becomes a no-op for
        // this frame.
        current_frame_info_.predicted_display_time = 0;
        current_frame_info_.should_render = false;
        current_frame_info_.views.assign(1, ViewInfo{});
    }

    frame_in_progress_ = true;
    return current_frame_info_;
}

void VizSession::end_frame()
{
    if (!frame_in_progress_)
    {
        throw std::logic_error("VizSession: end_frame called without a matching begin_frame");
    }

    // Always clear frame_in_progress_ + cached_frame_ on exit, even
    // if compositor.render throws (its own FrameGuard already calls
    // backend.abort_frame inside that case — we just need to release
    // the slot here).
    struct EndFrameGuard
    {
        bool* in_progress;
        std::optional<DisplayBackend::Frame>* cached;
        ~EndFrameGuard()
        {
            *in_progress = false;
            cached->reset();
        }
    } guard{ &frame_in_progress_, &cached_frame_ };

    if (state_ != SessionState::kRunning)
    {
        return;
    }

    if (cached_frame_)
    {
        std::vector<LayerBase*> raw_layers;
        raw_layers.reserve(layers_.size());
        for (const auto& l : layers_)
        {
            raw_layers.push_back(l.get());
        }
        compositor_->render(*cached_frame_, raw_layers);
    }
    // No cached frame = backend skipped (XR no-render / window minimized).
    // Compositor.render is not called; nothing to submit.

    update_timing_stats(current_frame_info_.delta_time);
    ++frame_index_;
}

FrameInfo VizSession::render()
{
    // begin_frame() now pumps events itself; no need to do it twice.
    auto info = begin_frame();
    end_frame();
    return info;
}

void VizSession::update_timing_stats(float frame_time_seconds)
{
    if (frame_time_seconds <= 0.0f)
    {
        return;
    }
    constexpr float kSmoothing = 0.1f;
    const float frame_ms = frame_time_seconds * 1000.0f;
    timing_stats_.avg_frame_time_ms = kSmoothing * frame_ms + (1.0f - kSmoothing) * timing_stats_.avg_frame_time_ms;
    timing_stats_.render_fps =
        (timing_stats_.avg_frame_time_ms > 0.0f) ? 1000.0f / timing_stats_.avg_frame_time_ms : 0.0f;
}

Resolution VizSession::get_recommended_resolution() const noexcept
{
    if (compositor_)
    {
        return compositor_->resolution();
    }
    return Resolution{ config_.window_width, config_.window_height };
}

HostImage VizSession::readback_to_host()
{
    if (!backend_)
    {
        throw std::runtime_error("VizSession: readback_to_host called before init");
    }
    return backend_->readback_to_host();
}

bool VizSession::should_close() const noexcept
{
    return backend_ ? backend_->should_close() : false;
}

std::optional<core::OpenXRSessionHandles> VizSession::get_oxr_handles() const noexcept
{
    if (config_.mode != DisplayMode::kXr || !backend_)
    {
        return std::nullopt;
    }
    auto* xr = static_cast<XrBackend*>(backend_.get());
    const auto h = xr->oxr_handles();
    if (h.instance == XR_NULL_HANDLE || h.session == XR_NULL_HANDLE)
    {
        // Backend created but session not yet established (init failed
        // or hasn't run); nothing useful to share.
        return std::nullopt;
    }
    core::OpenXRSessionHandles out{};
    out.instance = h.instance;
    out.session = h.session;
    out.space = h.reference_space;
    out.xrGetInstanceProcAddr = h.xrGetInstanceProcAddr;
    return out;
}

const VkContext& VizSession::ctx() const noexcept
{
    return *ctx_ptr_;
}

VkDevice VizSession::get_vk_device() const noexcept
{
    return ctx_ptr_ ? ctx_ptr_->device() : VK_NULL_HANDLE;
}

VkPhysicalDevice VizSession::get_vk_physical_device() const noexcept
{
    return ctx_ptr_ ? ctx_ptr_->physical_device() : VK_NULL_HANDLE;
}

uint32_t VizSession::get_vk_queue_family_index() const noexcept
{
    return ctx_ptr_ ? ctx_ptr_->queue_family_index() : UINT32_MAX;
}

VkRenderPass VizSession::get_render_pass() const noexcept
{
    return compositor_ ? compositor_->render_pass() : VK_NULL_HANDLE;
}

const VkContext* VizSession::get_vk_context() const noexcept
{
    return ctx_ptr_;
}

} // namespace viz
