// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/xr/openxr_instance.hpp>
#include <vulkan/vulkan.h>

#define XR_USE_GRAPHICS_API_VULKAN
#include <openxr/openxr_platform.h>

#include <chrono>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <thread>

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

OpenXrInstance::OpenXrInstance(const std::string& app_name,
                               const std::vector<std::string>& extra_extensions,
                               int system_wait_seconds)
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
        // Poll xrGetSystem; XR_ERROR_FORM_FACTOR_UNAVAILABLE means the
        // runtime is up but no headset is currently connected. CloudXR /
        // streaming runtimes return this between app start and client
        // connect — common enough that we expose system_wait_seconds
        // to keep retrying. Other failures (loader / extension issues)
        // throw immediately even within the wait window.
        //   system_wait_seconds < 0  → poll forever (Ctrl-C to break)
        //   system_wait_seconds = 0  → fail fast on first failure
        //   system_wait_seconds > 0  → bounded deadline
        constexpr auto kPollInterval = std::chrono::milliseconds(200);
        constexpr auto kLogEvery = std::chrono::seconds(3);
        const bool wait_forever = system_wait_seconds < 0;
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(system_wait_seconds);
        auto last_log = std::chrono::steady_clock::now();
        bool announced = false;
        while (true)
        {
            const XrResult r = xrGetSystem(instance_, &sys_info, &system_id_);
            if (XR_SUCCEEDED(r))
            {
                if (announced)
                {
                    std::fprintf(stderr, "OpenXrInstance: HMD connected.\n");
                }
                break;
            }
            if (r != XR_ERROR_FORM_FACTOR_UNAVAILABLE)
            {
                throw std::runtime_error(std::string("OpenXrInstance: xrGetSystem failed: XrResult=") + std::to_string(r));
            }
            const auto now = std::chrono::steady_clock::now();
            if (!wait_forever && now >= deadline)
            {
                throw std::runtime_error(
                    "OpenXrInstance: xrGetSystem timed out waiting for HMD "
                    "(XR_ERROR_FORM_FACTOR_UNAVAILABLE) after " +
                    std::to_string(system_wait_seconds) + "s");
            }
            if (!announced || (now - last_log) >= kLogEvery)
            {
                if (wait_forever)
                {
                    std::fprintf(stderr, "OpenXrInstance: waiting for HMD to connect...\n");
                }
                else
                {
                    const auto remaining = std::chrono::duration_cast<std::chrono::seconds>(deadline - now).count();
                    std::fprintf(stderr, "OpenXrInstance: waiting for HMD to connect (%llds remaining)...\n",
                                 static_cast<long long>(remaining));
                }
                std::fflush(stderr);
                announced = true;
                last_log = now;
            }
            std::this_thread::sleep_for(kPollInterval);
        }
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
