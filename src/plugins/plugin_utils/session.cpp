// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// OpenXR initialization and session management

#include <plugin_utils/session.hpp>

#include <cstring>
#include <iostream>
#include <stdexcept>

namespace plugin_utils
{

namespace
{
void CheckXrResult(XrResult result, const char* message)
{
    if (XR_FAILED(result))
    {
        throw std::runtime_error(std::string(message) + " failed with XrResult: " + std::to_string(result));
    }
}
}

Session::Session(const SessionConfig& config) : config_(config)
{
    try
    {
        initialize(config);
    }
    catch (...)
    {
        cleanup();
        throw;
    }
}

Session::~Session()
{
    // Ensure we attempt to end session if active?
    // Usually end() is called explicitly, but cleanup handles destruction.
    cleanup();
}

void Session::initialize(const SessionConfig& config)
{
    create_instance(config);
    get_system();
    create_session();
    create_reference_space(config.reference_space_type);
}

void Session::create_instance(const SessionConfig& config)
{
    XrInstanceCreateInfo create_info{ XR_TYPE_INSTANCE_CREATE_INFO };
    create_info.enabledExtensionCount = static_cast<uint32_t>(config.extensions.size());
    create_info.enabledExtensionNames = config.extensions.data();

    strncpy(create_info.applicationInfo.applicationName, config.app_name.c_str(), XR_MAX_APPLICATION_NAME_SIZE - 1);
    create_info.applicationInfo.applicationVersion = 1;
    strcpy(create_info.applicationInfo.engineName, "SyntheticHands");
    create_info.applicationInfo.engineVersion = 1;
    create_info.applicationInfo.apiVersion = XR_CURRENT_API_VERSION;

    CheckXrResult(xrCreateInstance(&create_info, &handles_.instance), "xrCreateInstance");
}

void Session::get_system()
{
    XrSystemGetInfo system_info{ XR_TYPE_SYSTEM_GET_INFO };
    system_info.formFactor = config_.form_factor;

    CheckXrResult(xrGetSystem(handles_.instance, &system_info, &handles_.system_id), "xrGetSystem");
}

void Session::create_session()
{
    XrSessionCreateInfo create_info{ XR_TYPE_SESSION_CREATE_INFO };

    XrSessionCreateInfoOverlayEXTX overlay_info{};
    if (config_.use_overlay_mode)
    {
        overlay_info.type = XR_TYPE_SESSION_CREATE_INFO_OVERLAY_EXTX;
        overlay_info.next = nullptr;
        overlay_info.createFlags = 0;
        overlay_info.sessionLayersPlacement = 0;
        create_info.next = &overlay_info;
    }
    else
    {
        create_info.next = nullptr;
    }

    create_info.systemId = handles_.system_id;

    CheckXrResult(xrCreateSession(handles_.instance, &create_info, &handles_.session), "xrCreateSession");
}

void Session::create_reference_space(XrReferenceSpaceType type)
{
    XrReferenceSpaceCreateInfo create_info{ XR_TYPE_REFERENCE_SPACE_CREATE_INFO };
    create_info.referenceSpaceType = type;
    create_info.poseInReferenceSpace.orientation = { 0.0f, 0.0f, 0.0f, 1.0f };
    create_info.poseInReferenceSpace.position = { 0.0f, 0.0f, 0.0f };

    CheckXrResult(
        xrCreateReferenceSpace(handles_.session, &create_info, &handles_.reference_space), "xrCreateReferenceSpace");
}

void Session::begin()
{
    XrSessionBeginInfo begin_info{ XR_TYPE_SESSION_BEGIN_INFO };
    begin_info.primaryViewConfigurationType = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;

    CheckXrResult(xrBeginSession(handles_.session, &begin_info), "xrBeginSession");
}

void Session::end()
{
    if (handles_.session != XR_NULL_HANDLE)
    {
        // Don't call xrEndSession - it requires the session to be in STOPPING state
        // For a headless session or when we're just shutting down, we can skip this
        // and go directly to xrDestroySession in cleanup()
        // If we strictly wanted to follow state machine we would need to request exit and wait for STOPPING.
    }
}

void Session::cleanup()
{
    if (handles_.instance == XR_NULL_HANDLE)
    {
        return;
    }

    if (handles_.reference_space != XR_NULL_HANDLE)
    {
        xrDestroySpace(handles_.reference_space);
        handles_.reference_space = XR_NULL_HANDLE;
    }

    if (handles_.session != XR_NULL_HANDLE)
    {
        xrDestroySession(handles_.session);
        handles_.session = XR_NULL_HANDLE;
    }

    if (handles_.instance != XR_NULL_HANDLE)
    {
        xrDestroyInstance(handles_.instance);
        handles_.instance = XR_NULL_HANDLE;
    }
}

} // namespace plugin_utils
