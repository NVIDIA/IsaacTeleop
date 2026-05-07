// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/xr/openxr_instance.hpp>
#include <vulkan/vulkan.h>

#define XR_USE_TIMESPEC
#include <viz/core/openxr_platform_compat.hpp>

#include <chrono>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <thread>
#include <unordered_set>

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
    // Enumerate runtime-advertised extensions once. Used to opt-in to
    // optional extensions (depth / time conversion) and to validate
    // caller-requested extras before xrCreateInstance.
    std::unordered_set<std::string> available_exts;
    {
        uint32_t count = 0;
        if (xrEnumerateInstanceExtensionProperties(nullptr, 0, &count, nullptr) == XR_SUCCESS && count > 0)
        {
            std::vector<XrExtensionProperties> available(count, XrExtensionProperties{ XR_TYPE_EXTENSION_PROPERTIES });
            if (xrEnumerateInstanceExtensionProperties(nullptr, count, &count, available.data()) == XR_SUCCESS)
            {
                available_exts.reserve(available.size());
                for (const auto& ext : available)
                {
                    available_exts.emplace(ext.extensionName);
                }
            }
        }
    }
    const bool runtime_has_depth_layer = available_exts.count(XR_KHR_COMPOSITION_LAYER_DEPTH_EXTENSION_NAME) > 0;
    const bool runtime_has_time_conversion = available_exts.count(XR_KHR_CONVERT_TIMESPEC_TIME_EXTENSION_NAME) > 0;

    // Build the request list deduped: required → opt-in → caller extras.
    // Caller extras are validated; passing an unsupported one is fatal.
    std::vector<const char*> exts;
    std::unordered_set<std::string> requested;
    auto add_unique = [&](const char* name)
    {
        if (requested.emplace(name).second)
        {
            exts.push_back(name);
        }
    };
    add_unique(XR_KHR_VULKAN_ENABLE2_EXTENSION_NAME);
    if (runtime_has_depth_layer)
    {
        add_unique(XR_KHR_COMPOSITION_LAYER_DEPTH_EXTENSION_NAME);
    }
    if (runtime_has_time_conversion)
    {
        add_unique(XR_KHR_CONVERT_TIMESPEC_TIME_EXTENSION_NAME);
    }
    for (const auto& e : extra_extensions)
    {
        if (available_exts.count(e) == 0)
        {
            throw std::runtime_error(std::string("OpenXrInstance: requested extension '") + e +
                                     "' is not advertised by the runtime");
        }
        add_unique(e.c_str());
    }

    XrInstanceCreateInfo info{ XR_TYPE_INSTANCE_CREATE_INFO };
    info.applicationInfo.apiVersion = XR_CURRENT_API_VERSION;
    std::strncpy(info.applicationInfo.applicationName, app_name.c_str(), XR_MAX_APPLICATION_NAME_SIZE - 1);
    std::strncpy(info.applicationInfo.engineName, "Televiz", XR_MAX_ENGINE_NAME_SIZE - 1);
    info.enabledExtensionCount = static_cast<uint32_t>(exts.size());
    info.enabledExtensionNames = exts.data();
    check(xrCreateInstance(&info, &instance_), "xrCreateInstance");
    has_depth_composition_layer_ = runtime_has_depth_layer;

    // Resolve PFNs only if both succeed — leave the feature off rather
    // than half-working.
    if (runtime_has_time_conversion)
    {
        PFN_xrVoidFunction to_time_fn = nullptr;
        PFN_xrVoidFunction from_time_fn = nullptr;
        if (xrGetInstanceProcAddr(instance_, "xrConvertTimespecTimeToTimeKHR", &to_time_fn) == XR_SUCCESS &&
            xrGetInstanceProcAddr(instance_, "xrConvertTimeToTimespecTimeKHR", &from_time_fn) == XR_SUCCESS &&
            to_time_fn != nullptr && from_time_fn != nullptr)
        {
            xr_convert_timespec_time_to_time_ = to_time_fn;
            xr_convert_time_to_timespec_time_ = from_time_fn;
            has_time_conversion_ = true;
        }
    }

    XrSystemGetInfo sys_info{ XR_TYPE_SYSTEM_GET_INFO };
    sys_info.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;
    try
    {
        // FORM_FACTOR_UNAVAILABLE = runtime up but HMD not connected yet
        // (typical for streaming runtimes). Poll within the wait window;
        // any other XrResult fails immediately.
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

std::chrono::steady_clock::time_point OpenXrInstance::xr_time_to_steady_clock(XrTime time) const
{
    if (!has_time_conversion_)
    {
        throw std::runtime_error(
            "OpenXrInstance::xr_time_to_steady_clock: XR_KHR_convert_timespec_time not available on this runtime");
    }
    timespec ts{};
    auto fn = reinterpret_cast<PFN_xrConvertTimeToTimespecTimeKHR>(xr_convert_time_to_timespec_time_);
    const XrResult r = fn(instance_, time, &ts);
    if (XR_FAILED(r))
    {
        throw std::runtime_error("OpenXrInstance: xrConvertTimeToTimespecTimeKHR failed: XrResult=" + std::to_string(r));
    }
    // CLOCK_MONOTONIC = std::chrono::steady_clock on Linux per spec.
    return std::chrono::steady_clock::time_point{ std::chrono::seconds{ ts.tv_sec } +
                                                  std::chrono::nanoseconds{ ts.tv_nsec } };
}

XrTime OpenXrInstance::steady_clock_to_xr_time(std::chrono::steady_clock::time_point t) const
{
    if (!has_time_conversion_)
    {
        throw std::runtime_error(
            "OpenXrInstance::steady_clock_to_xr_time: XR_KHR_convert_timespec_time not available on this runtime");
    }
    const auto duration = t.time_since_epoch();
    const auto secs = std::chrono::duration_cast<std::chrono::seconds>(duration);
    const auto nsecs = std::chrono::duration_cast<std::chrono::nanoseconds>(duration - secs);
    timespec ts{ static_cast<time_t>(secs.count()), static_cast<long>(nsecs.count()) };
    XrTime out = 0;
    auto fn = reinterpret_cast<PFN_xrConvertTimespecTimeToTimeKHR>(xr_convert_timespec_time_to_time_);
    const XrResult r = fn(instance_, &ts, &out);
    if (XR_FAILED(r))
    {
        throw std::runtime_error("OpenXrInstance: xrConvertTimespecTimeToTimeKHR failed: XrResult=" + std::to_string(r));
    }
    return out;
}

} // namespace viz
