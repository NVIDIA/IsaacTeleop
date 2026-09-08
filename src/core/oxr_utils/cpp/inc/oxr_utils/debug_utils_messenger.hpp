// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <log_bridge/logger.hpp>
#include <openxr/openxr.h>

#include <memory>
#include <string_view>
#include <vector>

namespace oxr_utils
{

// Returns true if the OpenXR loader/runtime advertises `extension_name`. Safe to call
// before any XrInstance exists (xrEnumerateInstanceExtensionProperties is loader-level).
inline bool extension_supported(const char* extension_name)
{
    uint32_t count = 0;
    if (XR_FAILED(xrEnumerateInstanceExtensionProperties(nullptr, 0, &count, nullptr)))
    {
        return false;
    }
    std::vector<XrExtensionProperties> props(count, XrExtensionProperties{ XR_TYPE_EXTENSION_PROPERTIES });
    if (XR_FAILED(xrEnumerateInstanceExtensionProperties(nullptr, count, &count, props.data())))
    {
        return false;
    }
    for (const auto& p : props)
    {
        if (std::string_view(p.extensionName) == extension_name)
        {
            return true;
        }
    }
    return false;
}

namespace detail
{

inline XrBool32 XRAPI_CALL debug_utils_callback(XrDebugUtilsMessageSeverityFlagsEXT severity,
                                                XrDebugUtilsMessageTypeFlagsEXT /*type*/,
                                                const XrDebugUtilsMessengerCallbackDataEXT* callback_data,
                                                void* user_data)
{
    auto* logger = static_cast<spdlog::logger*>(user_data);
    const char* message = callback_data->message != nullptr ? callback_data->message : "";

    // Runtime-reported severity, not re-leveled: this is vendor passthrough, the same
    // policy as every other third-party log source this system captures.
    if (severity & XR_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT)
    {
        logger->error("{}", message);
    }
    else if (severity & XR_DEBUG_UTILS_MESSAGE_SEVERITY_WARNING_BIT_EXT)
    {
        logger->warn("{}", message);
    }
    else if (severity & XR_DEBUG_UTILS_MESSAGE_SEVERITY_INFO_BIT_EXT)
    {
        logger->info("{}", message);
    }
    else
    {
        // XR_DEBUG_UTILS_MESSAGE_SEVERITY_VERBOSE_BIT_EXT, or an unrecognized future bit.
        logger->trace("{}", message);
    }

    // Must not suppress the runtime's own handling of the condition.
    return XR_FALSE;
}

} // namespace detail

// RAII wrapper around an XR_EXT_debug_utils messenger. Construct after xrCreateInstance()
// succeeds; safe to construct unconditionally -- if the runtime didn't advertise (and the
// caller therefore didn't enable) XR_EXT_debug_utils, xrGetInstanceProcAddr for
// xrCreateDebugUtilsMessengerEXT simply fails to resolve and this becomes a silent no-op
// (active() == false), so callers don't need to track that state separately.
//
// `logger` must outlive this object; it is not copied into the runtime, only a raw
// pointer to it is (OpenXR's callback user-data has no notion of ownership).
class DebugUtilsMessenger
{
public:
    DebugUtilsMessenger(XrInstance instance, PFN_xrGetInstanceProcAddr get_proc_addr, std::shared_ptr<spdlog::logger> logger)
        : logger_(std::move(logger))
    {
        PFN_xrVoidFunction create_fn = nullptr;
        PFN_xrVoidFunction destroy_fn = nullptr;
        if (XR_FAILED(get_proc_addr(instance, "xrCreateDebugUtilsMessengerEXT", &create_fn)) || create_fn == nullptr ||
            XR_FAILED(get_proc_addr(instance, "xrDestroyDebugUtilsMessengerEXT", &destroy_fn)) || destroy_fn == nullptr)
        {
            return;
        }
        destroy_fn_ = reinterpret_cast<PFN_xrDestroyDebugUtilsMessengerEXT>(destroy_fn);
        auto create_messenger_fn = reinterpret_cast<PFN_xrCreateDebugUtilsMessengerEXT>(create_fn);

        XrDebugUtilsMessengerCreateInfoEXT create_info{ XR_TYPE_DEBUG_UTILS_MESSENGER_CREATE_INFO_EXT };
        // Subscribe to everything; the logger's own handlers/levels decide what's visible,
        // the same "capture broadly, filter at the sink" policy used everywhere else here.
        create_info.messageSeverities =
            XR_DEBUG_UTILS_MESSAGE_SEVERITY_VERBOSE_BIT_EXT | XR_DEBUG_UTILS_MESSAGE_SEVERITY_INFO_BIT_EXT |
            XR_DEBUG_UTILS_MESSAGE_SEVERITY_WARNING_BIT_EXT | XR_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT;
        create_info.messageTypes = XR_DEBUG_UTILS_MESSAGE_TYPE_GENERAL_BIT_EXT |
                                   XR_DEBUG_UTILS_MESSAGE_TYPE_VALIDATION_BIT_EXT |
                                   XR_DEBUG_UTILS_MESSAGE_TYPE_PERFORMANCE_BIT_EXT;
        create_info.userCallback = detail::debug_utils_callback;
        create_info.userData = logger_.get();

        if (XR_FAILED(create_messenger_fn(instance, &create_info, &messenger_)))
        {
            messenger_ = XR_NULL_HANDLE;
            destroy_fn_ = nullptr;
        }
    }

    ~DebugUtilsMessenger()
    {
        if (messenger_ != XR_NULL_HANDLE && destroy_fn_ != nullptr)
        {
            destroy_fn_(messenger_);
        }
    }

    DebugUtilsMessenger(const DebugUtilsMessenger&) = delete;
    DebugUtilsMessenger& operator=(const DebugUtilsMessenger&) = delete;
    DebugUtilsMessenger(DebugUtilsMessenger&&) = delete;
    DebugUtilsMessenger& operator=(DebugUtilsMessenger&&) = delete;

    bool active() const
    {
        return messenger_ != XR_NULL_HANDLE;
    }

private:
    std::shared_ptr<spdlog::logger> logger_;
    PFN_xrDestroyDebugUtilsMessengerEXT destroy_fn_ = nullptr;
    XrDebugUtilsMessengerEXT messenger_ = XR_NULL_HANDLE;
};

} // namespace oxr_utils
