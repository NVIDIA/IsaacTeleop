// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// OpenXR initialization and session management

#include "session.hpp"

#include <cstring>
#include <iostream>

Session* Session::Create(const SessionConfig& config)
{
    Session* session = new Session();
    if (!session->initialize(config))
    {
        delete session;
        return nullptr;
    }
    return session;
}

Session::~Session()
{
    end();
    cleanup();
}

bool Session::initialize(const SessionConfig& config)
{
    config_ = config;

    if (!create_instance(config) || !get_system() || !create_session() ||
        !create_reference_space(config.reference_space_type))
    {
        cleanup();
        return false;
    }

    return true;
}

bool Session::create_instance(const SessionConfig& config)
{
    XrInstanceCreateInfo create_info{ XR_TYPE_INSTANCE_CREATE_INFO };
    create_info.enabledExtensionCount = static_cast<uint32_t>(config.extensions.size());
    create_info.enabledExtensionNames = config.extensions.data();

    strncpy(create_info.applicationInfo.applicationName, config.app_name.c_str(), XR_MAX_APPLICATION_NAME_SIZE - 1);
    create_info.applicationInfo.applicationVersion = 1;
    strcpy(create_info.applicationInfo.engineName, "SyntheticHands");
    create_info.applicationInfo.engineVersion = 1;
    create_info.applicationInfo.apiVersion = XR_CURRENT_API_VERSION;

    XrResult result = xrCreateInstance(&create_info, &handles_.instance);
    if (XR_FAILED(result))
    {
        std::cerr << "Failed to create OpenXR instance: " << result << std::endl;
        return false;
    }

    return true;
}

bool Session::get_system()
{
    XrSystemGetInfo system_info{ XR_TYPE_SYSTEM_GET_INFO };
    system_info.formFactor = config_.form_factor;

    XrResult result = xrGetSystem(handles_.instance, &system_info, &handles_.system_id);
    if (XR_FAILED(result))
    {
        std::cerr << "Failed to get OpenXR system: " << result << std::endl;
        return false;
    }

    return true;
}

bool Session::create_session()
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

    XrResult result = xrCreateSession(handles_.instance, &create_info, &handles_.session);
    if (XR_FAILED(result))
    {
        std::cerr << "Failed to create OpenXR session: " << result << std::endl;
        return false;
    }

    return true;
}

bool Session::create_reference_space(XrReferenceSpaceType type)
{
    XrReferenceSpaceCreateInfo create_info{ XR_TYPE_REFERENCE_SPACE_CREATE_INFO };
    create_info.referenceSpaceType = type;
    create_info.poseInReferenceSpace.orientation = { 0.0f, 0.0f, 0.0f, 1.0f };
    create_info.poseInReferenceSpace.position = { 0.0f, 0.0f, 0.0f };

    XrResult result = xrCreateReferenceSpace(handles_.session, &create_info, &handles_.reference_space);
    if (XR_FAILED(result))
    {
        std::cerr << "Failed to create reference space: " << result << std::endl;
        return false;
    }

    return true;
}

bool Session::begin()
{
    XrSessionBeginInfo begin_info{ XR_TYPE_SESSION_BEGIN_INFO };
    begin_info.primaryViewConfigurationType = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;

    XrResult result = xrBeginSession(handles_.session, &begin_info);
    if (XR_FAILED(result))
    {
        std::cerr << "Failed to begin session: " << result << std::endl;
        return false;
    }

    return true;
}

void Session::end()
{
    if (handles_.session != XR_NULL_HANDLE)
    {
        xrEndSession(handles_.session);
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
