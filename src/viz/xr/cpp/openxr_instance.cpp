// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/xr/openxr_instance.hpp>

#include <vulkan/vulkan.h>

#define XR_USE_GRAPHICS_API_VULKAN
#include <openxr/openxr_platform.h>

#include <cstring>
#include <stdexcept>

namespace viz
{

namespace
{

void check(XrResult r, const char* what)
{
    if (XR_FAILED(r))
    {
        throw std::runtime_error(std::string("OpenXrInstance: ") + what + " failed: XrResult=" + std::to_string(r));
    }
}

} // namespace

OpenXrInstance::OpenXrInstance(const std::string& app_name, const std::vector<std::string>& extra_extensions)
{
    std::vector<const char*> exts;
    exts.reserve(1 + extra_extensions.size());
    exts.push_back(XR_KHR_VULKAN_ENABLE2_EXTENSION_NAME);
    for (const auto& e : extra_extensions)
    {
        exts.push_back(e.c_str());
    }

    XrInstanceCreateInfo info{ XR_TYPE_INSTANCE_CREATE_INFO };
    info.applicationInfo.apiVersion = XR_CURRENT_API_VERSION;
    std::strncpy(info.applicationInfo.applicationName, app_name.c_str(), XR_MAX_APPLICATION_NAME_SIZE - 1);
    std::strncpy(info.applicationInfo.engineName, "Televiz", XR_MAX_ENGINE_NAME_SIZE - 1);
    info.enabledExtensionCount = static_cast<uint32_t>(exts.size());
    info.enabledExtensionNames = exts.data();
    check(xrCreateInstance(&info, &instance_), "xrCreateInstance");

    XrSystemGetInfo sys_info{ XR_TYPE_SYSTEM_GET_INFO };
    sys_info.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;
    try
    {
        check(xrGetSystem(instance_, &sys_info, &system_id_), "xrGetSystem");
    }
    catch (...)
    {
        xrDestroyInstance(instance_);
        instance_ = XR_NULL_HANDLE;
        throw;
    }
}

OpenXrInstance::~OpenXrInstance()
{
    if (instance_ != XR_NULL_HANDLE)
    {
        xrDestroyInstance(instance_);
        instance_ = XR_NULL_HANDLE;
    }
}

} // namespace viz
