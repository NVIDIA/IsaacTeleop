// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/session/display_backend.hpp>
#include <viz/session/offscreen_backend.hpp>
#include <viz/session/viz_session.hpp>
#include <viz/session/window_backend.hpp>

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
        throw std::runtime_error("VizSession: kXr is not yet implemented");
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
    current_frame_info_.predicted_display_time = 0; // XR-only; 0 in offscreen
    current_frame_info_.should_render = (state_ == SessionState::kRunning);
    current_frame_info_.resolution = compositor_ ? compositor_->resolution() : Resolution{};
    // Public FrameInfo carries a single identity entry as a hint;
    // backends populate the actual per-view info inside render().
    current_frame_info_.views.assign(1, ViewInfo{});

    frame_in_progress_ = true;
    return current_frame_info_;
}

void VizSession::end_frame()
{
    if (!frame_in_progress_)
    {
        throw std::logic_error("VizSession: end_frame called without a matching begin_frame");
    }
    if (state_ != SessionState::kRunning)
    {
        frame_in_progress_ = false;
        return;
    }

    struct ClearGuard
    {
        bool* flag;
        ~ClearGuard()
        {
            *flag = false;
        }
    } guard{ &frame_in_progress_ };

    std::vector<LayerBase*> raw_layers;
    raw_layers.reserve(layers_.size());
    for (const auto& l : layers_)
    {
        raw_layers.push_back(l.get());
    }

    if (current_frame_info_.should_render)
    {
        compositor_->render(raw_layers);
    }

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
