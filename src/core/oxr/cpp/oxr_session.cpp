// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/oxr/oxr_session.hpp"

#include <cstdlib>
#include <cstring>
#include <iostream>
#include <stdexcept>

namespace core
{

namespace
{

// Helper to get user home directory (cross-platform: HOME on Unix, USERPROFILE on Windows)
std::string get_home_dir()
{
#ifdef _WIN32
    const char* home = std::getenv("USERPROFILE");
#else
    const char* home = std::getenv("HOME");
#endif
    if (home == nullptr)
    {
        throw std::runtime_error("Failed to get user home directory");
    }
    return std::string(home);
}

// Ensure an environment variable is set. If not set, warn and set to default_value.
// Returns the final value (either existing or newly set).
void ensure_env_set(const char* env_name, const std::string& default_value)
{
    const char* current_value = std::getenv(env_name);

    if (current_value != nullptr && current_value[0] != '\0')
    {
        return;
    }

    // Not set - warn and set default
    std::cerr << "Warning: " << env_name << " environment variable is not set." << std::endl;
    std::cerr << "  Please set it before running, e.g.:" << std::endl;
    std::cerr << "    export " << env_name << "=" << default_value << std::endl;
    std::cerr << "  or set ISAAC_TELEOP_DISABLE_CXR_ENV_CHECKS to disable this check" << std::endl;

    throw std::runtime_error("Environment variable " + std::string(env_name) + " is not set");
}

// Ensure required environment variables are set before xrCreateInstance.
void ensure_cloudxr_runtime_configured()
{
    if (std::getenv("ISAAC_TELEOP_DISABLE_CXR_ENV_CHECKS") != nullptr)
    {
        return;
    }

    const std::string home = get_home_dir();

    // NV_CXR_RUNTIME_DIR - required by some OpenXR runtimes for IPC
    ensure_env_set("NV_CXR_RUNTIME_DIR", home + "/.cloudxr/run");

    // XR_RUNTIME_JSON - tells OpenXR loader which runtime to use
    ensure_env_set("XR_RUNTIME_JSON", home + "/.cloudxr/share/openxr/1/openxr_cloudxr.json");
}

} // anonymous namespace

OpenXRSession::OpenXRSession(const std::string& app_name, const std::vector<std::string>& extensions)
    : instance_(XR_NULL_HANDLE, &xrDestroyInstance),
      system_id_(XR_NULL_SYSTEM_ID),
      session_(XR_NULL_HANDLE, &xrDestroySession),
      space_(XR_NULL_HANDLE, &xrDestroySpace)
{
    create_instance(app_name, extensions);
    create_system();
    create_session();
    create_reference_space();
    begin();
}

OpenXRSessionHandles OpenXRSession::get_handles() const
{
    // Pass the global xrGetInstanceProcAddr - oxr_session links against OpenXR loader
    return OpenXRSessionHandles(instance_.get(), session_.get(), space_.get(), ::xrGetInstanceProcAddr);
}


void OpenXRSession::create_instance(const std::string& app_name, const std::vector<std::string>& extensions)
{
    // Ensure XR_RUNTIME_JSON is configured before calling xrCreateInstance
    ensure_cloudxr_runtime_configured();

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

    XrInstance instance = XR_NULL_HANDLE;
    XrResult result = xrCreateInstance(&create_info, &instance);
    if (XR_FAILED(result))
    {
        throw std::runtime_error("Failed to create OpenXR instance: " + std::to_string(result));
    }

    instance_.reset(instance);

    std::cout << "Created OpenXR instance" << std::endl;
}

void OpenXRSession::create_system()
{
    XrSystemGetInfo system_info{ XR_TYPE_SYSTEM_GET_INFO };
    system_info.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;

    XrResult result = xrGetSystem(instance_.get(), &system_info, &system_id_);
    if (XR_FAILED(result))
    {
        throw std::runtime_error("Failed to get OpenXR system: " + std::to_string(result));
    }

    std::cout << "Created OpenXR system" << std::endl;
}

void OpenXRSession::create_session()
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

    XrSession session = XR_NULL_HANDLE;
    XrResult result = xrCreateSession(instance_.get(), &create_info, &session);
    if (XR_FAILED(result))
    {
        throw std::runtime_error("Failed to create OpenXR session: " + std::to_string(result));
    }

    session_.reset(session);

    std::cout << "Created OpenXR session (headless mode)" << std::endl;
    std::cout << "  Session handle: " << session_.get() << std::endl;
}

void OpenXRSession::create_reference_space()
{
    XrReferenceSpaceCreateInfo create_info{ XR_TYPE_REFERENCE_SPACE_CREATE_INFO };
    create_info.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_STAGE;
    create_info.poseInReferenceSpace.orientation.w = 1.0f;

    XrSpace space = XR_NULL_HANDLE;
    XrResult result = xrCreateReferenceSpace(session_.get(), &create_info, &space);
    if (XR_FAILED(result))
    {
        throw std::runtime_error("Failed to create reference space: " + std::to_string(result));
    }

    space_.reset(space);

    std::cout << "Created reference space" << std::endl;
    std::cout << "  Space handle: " << space_.get() << std::endl;
}

void OpenXRSession::begin()
{
    // Enumerate view configurations to find a valid one
    uint32_t view_config_count = 0;
    XrResult result = xrEnumerateViewConfigurations(instance_.get(), system_id_, 0, &view_config_count, nullptr);
    if (XR_FAILED(result) || view_config_count == 0)
    {
        throw std::runtime_error("Failed to enumerate view configurations: " + std::to_string(result));
    }

    std::vector<XrViewConfigurationType> view_configs(view_config_count);
    result = xrEnumerateViewConfigurations(
        instance_.get(), system_id_, view_config_count, &view_config_count, view_configs.data());
    if (XR_FAILED(result))
    {
        throw std::runtime_error("Failed to get view configurations: " + std::to_string(result));
    }

    // Find the primary stereo view configuration (preferred), or use the first available
    XrViewConfigurationType selected_view_config = view_configs[0];
    for (const auto& config : view_configs)
    {
        if (config == XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO)
        {
            selected_view_config = config;
            break;
        }
    }

    XrSessionBeginInfo begin_info{ XR_TYPE_SESSION_BEGIN_INFO };
    begin_info.primaryViewConfigurationType = selected_view_config;

    result = xrBeginSession(session_.get(), &begin_info);
    if (XR_FAILED(result))
    {
        throw std::runtime_error("Failed to begin OpenXR session: " + std::to_string(result));
    }
}

} // namespace core
