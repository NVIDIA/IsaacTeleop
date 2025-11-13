// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/oxr/oxr_session.hpp"

#include <cstring>
#include <iostream>

namespace oxr
{

OpenXRSession::OpenXRSession()
    : instance_(XR_NULL_HANDLE), system_id_(XR_NULL_SYSTEM_ID), session_(XR_NULL_HANDLE), space_(XR_NULL_HANDLE)
{
}

OpenXRSession::~OpenXRSession()
{
    // RAII cleanup
    if (space_ != XR_NULL_HANDLE)
    {
        xrDestroySpace(space_);
        space_ = XR_NULL_HANDLE;
    }

    if (session_ != XR_NULL_HANDLE)
    {
        xrDestroySession(session_);
        session_ = XR_NULL_HANDLE;
    }

    if (instance_ != XR_NULL_HANDLE)
    {
        xrDestroyInstance(instance_);
        instance_ = XR_NULL_HANDLE;
    }
}

std::shared_ptr<OpenXRSession> OpenXRSession::Create(const std::string& app_name,
                                                     const std::vector<std::string>& extensions)
{

    auto session = std::shared_ptr<OpenXRSession>(new OpenXRSession());

    if (!session->create_instance(app_name, extensions))
    {
        return nullptr;
    }

    if (!session->create_system())
    {
        return nullptr;
    }

    if (!session->create_session())
    {
        return nullptr;
    }

    if (!session->create_reference_space())
    {
        return nullptr;
    }

    return session;
}

OpenXRSessionHandles OpenXRSession::get_handles() const
{
    // Pass the global xrGetInstanceProcAddr - oxr_session links against OpenXR loader
    return OpenXRSessionHandles(instance_, session_, space_, ::xrGetInstanceProcAddr);
}

bool OpenXRSession::create_instance(const std::string& app_name, const std::vector<std::string>& extensions)
{
    XrInstanceCreateInfo create_info{ XR_TYPE_INSTANCE_CREATE_INFO };
    create_info.applicationInfo.apiVersion = XR_CURRENT_API_VERSION;
    strncpy(create_info.applicationInfo.applicationName, app_name.c_str(), XR_MAX_APPLICATION_NAME_SIZE - 1);
    strncpy(create_info.applicationInfo.engineName, "OXR_Tracking", XR_MAX_ENGINE_NAME_SIZE - 1);

    // Create a combined list with required extensions for headless/overlay mode
    std::vector<std::string> all_extensions = extensions;

    // Add headless and overlay extensions automatically
    all_extensions.push_back("XR_MND_headless");
    all_extensions.push_back("XR_EXTX_overlay");

    // Convert vector<string> to array of const char* for OpenXR API
    std::vector<const char*> extension_ptrs;
    for (const auto& ext : all_extensions)
    {
        extension_ptrs.push_back(ext.c_str());
    }

    create_info.enabledExtensionCount = static_cast<uint32_t>(extension_ptrs.size());
    create_info.enabledExtensionNames = extension_ptrs.empty() ? nullptr : extension_ptrs.data();

    XrResult result = xrCreateInstance(&create_info, &instance_);
    if (XR_FAILED(result))
    {
        std::cerr << "Failed to create OpenXR instance: " << result << std::endl;
        return false;
    }

    std::cout << "Created OpenXR instance" << std::endl;
    return true;
}

bool OpenXRSession::create_system()
{
    XrSystemGetInfo system_info{ XR_TYPE_SYSTEM_GET_INFO };
    system_info.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;

    XrResult result = xrGetSystem(instance_, &system_info, &system_id_);
    if (XR_FAILED(result))
    {
        std::cerr << "Failed to get OpenXR system: " << result << std::endl;
        return false;
    }

    std::cout << "Created OpenXR system" << std::endl;
    return true;
}

bool OpenXRSession::create_session()
{
    // XrSessionCreateInfoOverlayEXTX structure for overlay/headless mode
    struct XrSessionCreateInfoOverlayEXTX
    {
        XrStructureType type;
        const void* next;
        uint32_t createFlags;
        uint32_t sessionLayersPlacement;
    };

    XrSessionCreateInfoOverlayEXTX overlay_info{};
    overlay_info.type = (XrStructureType)1000033000; // XR_TYPE_SESSION_CREATE_INFO_OVERLAY_EXTX
    overlay_info.next = nullptr;
    overlay_info.createFlags = 0;
    overlay_info.sessionLayersPlacement = 0;

    XrSessionCreateInfo create_info{ XR_TYPE_SESSION_CREATE_INFO };
    create_info.next = &overlay_info;
    create_info.systemId = system_id_;

    XrResult result = xrCreateSession(instance_, &create_info, &session_);
    if (XR_FAILED(result))
    {
        std::cerr << "Failed to create OpenXR session: " << result << std::endl;
        return false;
    }

    std::cout << "Created OpenXR session (headless mode)" << std::endl;
    std::cout << "  Session handle: " << session_ << std::endl;
    return true;
}

bool OpenXRSession::create_reference_space()
{
    XrReferenceSpaceCreateInfo create_info{ XR_TYPE_REFERENCE_SPACE_CREATE_INFO };
    create_info.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_STAGE;
    create_info.poseInReferenceSpace.orientation.w = 1.0f;

    XrResult result = xrCreateReferenceSpace(session_, &create_info, &space_);
    if (XR_FAILED(result))
    {
        std::cerr << "Failed to create reference space: " << result << std::endl;
        return false;
    }

    std::cout << "Created reference space" << std::endl;
    std::cout << "  Space handle: " << space_ << std::endl;
    return true;
}

} // namespace oxr
