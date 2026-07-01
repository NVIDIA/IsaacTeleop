// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/viz/session/viz_session.hpp"

#include "inc/viz/session/display_backend.hpp"
#include "inc/viz/session/offscreen_backend.hpp"
#include "inc/viz/session/window_backend.hpp"
#include "inc/viz/session/xr_backend.hpp"

#include <viz/xr/openxr_session.hpp>

#include <algorithm>
#include <stdexcept>

namespace viz
{

namespace
{

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
        // Env blend mode chosen at runtime from what the system advertises.
        xc.session_config.near_z = cfg.xr_near_z;
        xc.session_config.far_z = cfg.xr_far_z;
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
    // Backend first — it dictates Vulkan extensions and rejects
    // unsupported modes before any Vulkan work.
    backend_ = make_backend(config_);

    try
    {
        VkContext::Config vk_cfg{};
        vk_cfg.instance_extensions = backend_->required_instance_extensions();
        vk_cfg.device_extensions = backend_->required_device_extensions();
        vk_cfg.optional_device_extensions = backend_->optional_device_extensions();

        // kXr: hand XrInstance + systemId to VkContext so it takes the
        // xrCreateVulkan*KHR path — lets the runtime interpose on
        // instance/device creation.
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
        c_cfg.gpu_timing = config_.gpu_timing;
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
    // Drain GPU before tearing anything down. render() returns without
    // host-waiting on its fence (multi-frame-in-flight), so when we
    // reach destroy() the GPU may still be reading layer descriptor
    // sets / DeviceImages / command buffers. vkDeviceWaitIdle blocks
    // until the device is idle. Errors are swallowed — if the device
    // is already lost we still need to tear down cleanly.
    if (ctx_ptr_ != nullptr && ctx_ptr_->device() != VK_NULL_HANDLE)
    {
        (void)vkDeviceWaitIdle(ctx_ptr_->device());
    }
    layers_.clear();
    // compositor holds a backend ref; backend uses the context: tear down in this order.
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
    // Same hazard as destroy() — a layer's resources may still be in
    // an in-flight command buffer; drain before freeing them.
    if (ctx_ptr_ != nullptr && ctx_ptr_->device() != VK_NULL_HANDLE)
    {
        (void)vkDeviceWaitIdle(ctx_ptr_->device());
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

    // A direct-present (ProjectionLayer) layer copies its images 1:1 into the
    // swapchain, so its resolution / view count / in-flight slot count must
    // keep matching the backend. pump_events() may have resized or recreated
    // the swapchain (changing the per-view size or image count), so revalidate
    // here — a now-incompatible layer fails fast with a clear error instead of
    // silently presenting clamped or partial content. Cheap: at most one
    // projection layer, integer comparisons unless they mismatch.
    for (const auto& layer : layers_)
    {
        if (layer->is_projection_layer())
        {
            validate_layer_against_backend_(layer.get());
        }
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
    current_backend_frame_.reset();

    // Acquire the backend frame BEFORE returning so renderers calling
    // submit() against the returned FrameInfo's views are working with
    // the same per-eye poses xrEndFrame will submit later. Skip the
    // acquire when state isn't kRunning (kStopping/kLost paths submit
    // empty xrEndFrames internally) or when the backend itself returns
    // nullopt (XR shouldRender=0, swapchain skip).
    if (state_ == SessionState::kRunning && backend_)
    {
        current_backend_frame_ = backend_->begin_frame(/*ignored=*/0);
    }

    if (current_backend_frame_.has_value())
    {
        current_frame_info_.should_render = true;
        current_frame_info_.predicted_display_time = current_backend_frame_->predicted_display_time_ns;
        current_frame_info_.views = current_backend_frame_->views;
        if (current_frame_info_.views.empty())
        {
            current_frame_info_.views.assign(1, ViewInfo{});
        }
    }
    else
    {
        current_frame_info_.should_render = false;
        current_frame_info_.predicted_display_time = 0;
        current_frame_info_.views.assign(1, ViewInfo{});
    }

    // Notify layers a new frame has begun. Lets ProjectionLayer-style
    // layers clear per-frame freshness flags so a stale mailbox slot
    // doesn't get composited under a new pose.
    for (const auto& layer : layers_)
    {
        if (layer != nullptr)
        {
            layer->on_frame_begin();
        }
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

    struct ClearGuard
    {
        bool* flag;
        std::optional<DisplayBackend::Frame>* frame_slot;
        ~ClearGuard()
        {
            *flag = false;
            frame_slot->reset();
        }
    } guard{ &frame_in_progress_, &current_backend_frame_ };

    if (current_backend_frame_.has_value())
    {
        std::vector<LayerBase*> raw_layers;
        raw_layers.reserve(layers_.size());
        for (const auto& l : layers_)
        {
            raw_layers.push_back(l.get());
        }
        compositor_->render(*current_backend_frame_, raw_layers);
    }

    update_timing_stats(current_frame_info_.delta_time);
    ++frame_index_;
}

FrameInfo VizSession::render()
{
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

void VizSession::validate_layer_against_backend_(LayerBase* layer) const
{
    // No backend yet (layers may be built standalone in tests) → nothing to check.
    if (layer == nullptr || backend_ == nullptr)
    {
        return;
    }
    // Context affinity: a foreign context's images/semaphores would be used on
    // this session's queue — invalid cross-device usage.
    if (layer->vk_context() != nullptr && layer->vk_context() != &ctx())
    {
        throw std::invalid_argument(
            "VizSession: layer was created from a different VkContext than the session's; "
            "build layers with VizSession::get_vk_context().");
    }
    const uint32_t backend_view_count = backend_->is_xr() ? 2u : 1u;
    layer->validate_backend_compatibility(
        backend_->recommended_view_resolution(), backend_view_count, backend_->image_count());
}

Resolution VizSession::get_recommended_resolution() const noexcept
{
    // Per-view size a direct ProjectionLayer should render at (kXr: per-eye,
    // so its copy to the swapchain is 1:1). Window/offscreen report the
    // single-view target extent.
    if (backend_)
    {
        return backend_->recommended_view_resolution();
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
        // Backend exists but XR session not yet established.
        return std::nullopt;
    }
    core::OpenXRSessionHandles out{};
    out.instance = h.instance;
    out.session = h.session;
    out.space = h.reference_space;
    out.xrGetInstanceProcAddr = h.xrGetInstanceProcAddr;
    return out;
}

bool VizSession::has_xr_time_conversion() const noexcept
{
    if (config_.mode != DisplayMode::kXr || !backend_)
    {
        return false;
    }
    const auto* xr = static_cast<const XrBackend*>(backend_.get());
    const auto* sess = xr->xr_session();
    return sess != nullptr && sess->has_time_conversion();
}

std::chrono::steady_clock::time_point VizSession::xr_time_to_steady_clock(int64_t xr_time) const
{
    if (config_.mode != DisplayMode::kXr || !backend_)
    {
        throw std::logic_error("VizSession::xr_time_to_steady_clock: only valid in kXr mode");
    }
    const auto* xr = static_cast<const XrBackend*>(backend_.get());
    const auto* sess = xr->xr_session();
    if (sess == nullptr)
    {
        throw std::logic_error("VizSession::xr_time_to_steady_clock: XR session not initialized");
    }
    return sess->xr_time_to_steady_clock(static_cast<XrTime>(xr_time));
}

int64_t VizSession::steady_clock_to_xr_time(std::chrono::steady_clock::time_point t) const
{
    if (config_.mode != DisplayMode::kXr || !backend_)
    {
        throw std::logic_error("VizSession::steady_clock_to_xr_time: only valid in kXr mode");
    }
    const auto* xr = static_cast<const XrBackend*>(backend_.get());
    const auto* sess = xr->xr_session();
    if (sess == nullptr)
    {
        throw std::logic_error("VizSession::steady_clock_to_xr_time: XR session not initialized");
    }
    return static_cast<int64_t>(sess->steady_clock_to_xr_time(t));
}

const VizCompositor::GpuFrameTiming& VizSession::get_gpu_timing() const noexcept
{
    static constexpr VizCompositor::GpuFrameTiming kZero{};
    return compositor_ ? compositor_->last_gpu_timing() : kZero;
}

std::optional<Pose3D> VizSession::head_pose_now() const
{
    if (config_.mode != DisplayMode::kXr || !backend_)
    {
        throw std::logic_error("VizSession::head_pose_now: only valid in kXr mode");
    }
    const auto* xr = static_cast<const XrBackend*>(backend_.get());
    const auto* sess = xr->xr_session();
    if (sess == nullptr || !sess->has_time_conversion())
    {
        return std::nullopt;
    }
    const XrTime now = sess->steady_clock_to_xr_time(std::chrono::steady_clock::now());
    XrSpaceLocation loc{ XR_TYPE_SPACE_LOCATION };
    if (!sess->locate_view_space(now, &loc))
    {
        return std::nullopt;
    }
    return Pose3D{
        glm::vec3(loc.pose.position.x, loc.pose.position.y, loc.pose.position.z),
        glm::quat(loc.pose.orientation.w, loc.pose.orientation.x, loc.pose.orientation.y, loc.pose.orientation.z),
    };
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
