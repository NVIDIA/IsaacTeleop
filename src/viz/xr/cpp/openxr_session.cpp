// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/vk_context.hpp>
#include <viz/xr/openxr_instance.hpp>
#include <viz/xr/openxr_session.hpp>

#define XR_USE_GRAPHICS_API_VULKAN
#include <openxr/openxr_platform.h>

#include <stdexcept>
#include <string>

namespace viz
{

namespace
{

void check_xr(XrResult r, const char* what)
{
    if (XR_FAILED(r))
    {
        throw std::runtime_error(std::string("OpenXrSession: ") + what + " failed: XrResult=" + std::to_string(r));
    }
}

} // namespace

OpenXrSession::OpenXrSession(const OpenXrInstance& instance, const VkContext& vk)
    : OpenXrSession(instance, vk, Config{})
{
}

OpenXrSession::OpenXrSession(const OpenXrInstance& instance, const VkContext& vk, const Config& config)
    : config_(config), instance_(instance.instance()), system_id_(instance.system_id())
{
    if (instance_ == XR_NULL_HANDLE)
    {
        throw std::invalid_argument("OpenXrSession: instance is XR_NULL_HANDLE");
    }
    if (system_id_ == XR_NULL_SYSTEM_ID)
    {
        throw std::invalid_argument("OpenXrSession: system_id is XR_NULL_SYSTEM_ID");
    }
    if (!vk.is_initialized())
    {
        throw std::invalid_argument("OpenXrSession: VkContext is not initialized");
    }
    try
    {
        enumerate_view_configuration();
        create_session(vk);
        create_reference_space(config_.reference_space_type);
    }
    catch (...)
    {
        // Roll back any partial state so the destructor only sees what
        // it expects. Order is reverse of construction.
        if (reference_space_ != XR_NULL_HANDLE)
        {
            xrDestroySpace(reference_space_);
            reference_space_ = XR_NULL_HANDLE;
        }
        if (session_ != XR_NULL_HANDLE)
        {
            xrDestroySession(session_);
            session_ = XR_NULL_HANDLE;
        }
        throw;
    }
}

OpenXrSession::~OpenXrSession()
{
    if (reference_space_ != XR_NULL_HANDLE)
    {
        xrDestroySpace(reference_space_);
        reference_space_ = XR_NULL_HANDLE;
    }
    if (session_ != XR_NULL_HANDLE)
    {
        // Best-effort graceful shutdown if we never observed STOPPING
        // (e.g. process is exiting before the runtime got to ask us).
        // Quiet failures — destructor can't throw.
        if (session_running_)
        {
            (void)xrEndSession(session_);
            session_running_ = false;
        }
        xrDestroySession(session_);
        session_ = XR_NULL_HANDLE;
    }
}

void OpenXrSession::enumerate_view_configuration()
{
    uint32_t count = 0;
    check_xr(xrEnumerateViewConfigurationViews(instance_, system_id_, view_configuration_type_, 0, &count, nullptr),
             "xrEnumerateViewConfigurationViews(count)");
    if (count == 0)
    {
        throw std::runtime_error("OpenXrSession: runtime reports zero views for PRIMARY_STEREO");
    }
    view_configuration_views_.assign(count, XrViewConfigurationView{ XR_TYPE_VIEW_CONFIGURATION_VIEW });
    check_xr(xrEnumerateViewConfigurationViews(
                 instance_, system_id_, view_configuration_type_, count, &count, view_configuration_views_.data()),
             "xrEnumerateViewConfigurationViews(data)");
}

void OpenXrSession::create_session(const VkContext& vk)
{
    XrGraphicsBindingVulkan2KHR binding{ XR_TYPE_GRAPHICS_BINDING_VULKAN2_KHR };
    binding.instance = vk.instance();
    binding.physicalDevice = vk.physical_device();
    binding.device = vk.device();
    binding.queueFamilyIndex = vk.queue_family_index();
    binding.queueIndex = 0;

    XrSessionCreateInfo info{ XR_TYPE_SESSION_CREATE_INFO };
    info.next = &binding;
    info.systemId = system_id_;
    check_xr(xrCreateSession(instance_, &info, &session_), "xrCreateSession");
}

void OpenXrSession::create_reference_space(XrReferenceSpaceType type)
{
    XrReferenceSpaceCreateInfo info{ XR_TYPE_REFERENCE_SPACE_CREATE_INFO };
    info.referenceSpaceType = type;
    info.poseInReferenceSpace.orientation = XrQuaternionf{ 0.0f, 0.0f, 0.0f, 1.0f };
    info.poseInReferenceSpace.position = XrVector3f{ 0.0f, 0.0f, 0.0f };
    check_xr(xrCreateReferenceSpace(session_, &info, &reference_space_), "xrCreateReferenceSpace");
}

void OpenXrSession::poll_events()
{
    while (true)
    {
        XrEventDataBuffer event{ XR_TYPE_EVENT_DATA_BUFFER };
        const XrResult r = xrPollEvent(instance_, &event);
        if (r == XR_EVENT_UNAVAILABLE)
        {
            return;
        }
        if (XR_FAILED(r))
        {
            throw std::runtime_error("OpenXrSession: xrPollEvent failed: XrResult=" + std::to_string(r));
        }
        switch (event.type)
        {
        case XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED:
        {
            const auto* state_change = reinterpret_cast<const XrEventDataSessionStateChanged*>(&event);
            if (state_change->session == session_)
            {
                handle_session_state_change(state_change->state);
            }
            break;
        }
        case XR_TYPE_EVENT_DATA_INSTANCE_LOSS_PENDING:
            // Runtime is going away — quit cleanly.
            exit_requested_ = true;
            break;
        case XR_TYPE_EVENT_DATA_REFERENCE_SPACE_CHANGE_PENDING:
            // Pose origin shifted (recenter, guardian rebound). For
            // seated/local the next locate_views absorbs the change;
            // app can re-anchor world-locked content if it cares.
            break;
        default:
            // Ignore unknown / extension event types we didn't ask for.
            break;
        }
    }
}

void OpenXrSession::handle_session_state_change(XrSessionState new_state)
{
    state_ = new_state;
    switch (new_state)
    {
    case XR_SESSION_STATE_READY:
    {
        XrSessionBeginInfo info{ XR_TYPE_SESSION_BEGIN_INFO };
        info.primaryViewConfigurationType = view_configuration_type_;
        const XrResult r = xrBeginSession(session_, &info);
        if (XR_SUCCEEDED(r))
        {
            session_running_ = true;
        }
        // Hard failure to begin is unusual; surface on next wait_frame
        // attempt rather than throwing from event poll.
        break;
    }
    case XR_SESSION_STATE_SYNCHRONIZED:
    case XR_SESSION_STATE_VISIBLE:
    case XR_SESSION_STATE_FOCUSED:
        // Already running from READY; this is just a focus/visibility shift.
        session_running_ = true;
        break;
    case XR_SESSION_STATE_STOPPING:
        if (session_running_)
        {
            (void)xrEndSession(session_);
            session_running_ = false;
        }
        break;
    case XR_SESSION_STATE_EXITING:
    case XR_SESSION_STATE_LOSS_PENDING:
        exit_requested_ = true;
        session_running_ = false;
        break;
    default:
        break;
    }
}

bool OpenXrSession::wait_frame(XrFrameState* out_state)
{
    if (!session_running_)
    {
        return false;
    }
    XrFrameWaitInfo wait_info{ XR_TYPE_FRAME_WAIT_INFO };
    *out_state = XrFrameState{ XR_TYPE_FRAME_STATE };
    const XrResult r = xrWaitFrame(session_, &wait_info, out_state);
    if (XR_FAILED(r))
    {
        throw std::runtime_error("OpenXrSession: xrWaitFrame failed: XrResult=" + std::to_string(r));
    }
    return true;
}

void OpenXrSession::begin_frame()
{
    XrFrameBeginInfo info{ XR_TYPE_FRAME_BEGIN_INFO };
    const XrResult r = xrBeginFrame(session_, &info);
    // XR_FRAME_DISCARDED is non-fatal — runtime is asking us to skip
    // submission for this frame. Caller still pairs with end_frame
    // (with empty layers) to keep the protocol balanced.
    if (r != XR_SUCCESS && r != XR_FRAME_DISCARDED)
    {
        throw std::runtime_error("OpenXrSession: xrBeginFrame failed: XrResult=" + std::to_string(r));
    }
}

bool OpenXrSession::locate_views(XrTime predicted_display_time, XrViewState* out_view_state, std::vector<XrView>* out_views)
{
    if (!session_running_)
    {
        return false;
    }
    XrViewLocateInfo locate_info{ XR_TYPE_VIEW_LOCATE_INFO };
    locate_info.viewConfigurationType = view_configuration_type_;
    locate_info.displayTime = predicted_display_time;
    locate_info.space = reference_space_;

    *out_view_state = XrViewState{ XR_TYPE_VIEW_STATE };
    out_views->assign(view_count(), XrView{ XR_TYPE_VIEW });

    uint32_t got = 0;
    const XrResult r = xrLocateViews(session_, &locate_info, out_view_state, view_count(), &got, out_views->data());
    if (XR_FAILED(r))
    {
        return false;
    }
    // Pose validity flags must be set; otherwise the returned poses are
    // zero/identity and rendering with them would put content at origin.
    constexpr XrViewStateFlags kRequired = XR_VIEW_STATE_POSITION_VALID_BIT | XR_VIEW_STATE_ORIENTATION_VALID_BIT;
    return (out_view_state->viewStateFlags & kRequired) == kRequired;
}

void OpenXrSession::end_frame(XrTime predicted_display_time,
                              const std::vector<const XrCompositionLayerBaseHeader*>& layers)
{
    XrFrameEndInfo info{ XR_TYPE_FRAME_END_INFO };
    info.displayTime = predicted_display_time;
    info.environmentBlendMode = config_.environment_blend_mode;
    info.layerCount = static_cast<uint32_t>(layers.size());
    info.layers = layers.empty() ? nullptr : layers.data();
    const XrResult r = xrEndFrame(session_, &info);
    if (XR_FAILED(r))
    {
        throw std::runtime_error("OpenXrSession: xrEndFrame failed: XrResult=" + std::to_string(r));
    }
}

} // namespace viz
