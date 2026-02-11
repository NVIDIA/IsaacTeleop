// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "oxr_creator.hpp"

#include <algorithm>
#include <cstring>
#include <iostream>

#define XR_CHK_WITH_RET(RESULT, FUNC_STR, TO_RET)                                                                      \
    do                                                                                                                 \
    {                                                                                                                  \
        XrResult _result = (RESULT);                                                                                   \
        if (XR_FAILED(_result))                                                                                        \
        {                                                                                                              \
            std::cerr << "[OpenXRCreator] " << FUNC_STR << " failed with result: " << _result << std::endl;            \
            return TO_RET;                                                                                             \
        }                                                                                                              \
    } while (0)

OpenXRCreator::OpenXRCreator() : bundle_(), form_factor_(XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY)
{
}

OpenXRCreator::~OpenXRCreator()
{
    if (bundle_.session != XR_NULL_HANDLE)
    {
        xrDestroySession(bundle_.session);
        bundle_.session = XR_NULL_HANDLE;
    }
    if (bundle_.instance != XR_NULL_HANDLE)
    {
        xrDestroyInstance(bundle_.instance);
        bundle_.instance = XR_NULL_HANDLE;
    }
}

bool OpenXRCreator::initializeHeadless(const std::vector<std::string>& optional_extensions)
{
    std::vector<std::string> requested;
    requested.push_back(XR_MND_HEADLESS_EXTENSION_NAME);
    for (const auto& e : optional_extensions)
        requested.push_back(e);

    if (!createInstance(requested))
        return false;
    if (!getSystem())
        return false;
    if (!createSession())
        return false;
    return true;
}

const OpenXRBundle& OpenXRCreator::getBundle() const
{
    return bundle_;
}


/*
 *
 * Private methods.
 *
 */

bool OpenXRCreator::createInstance(const std::vector<std::string>& requested_extensions)
{
    XrResult result;
    uint32_t extension_count = 0;
    result = xrEnumerateInstanceExtensionProperties(nullptr, 0, &extension_count, nullptr);
    XR_CHK_WITH_RET(result, "xrEnumerateInstanceExtensionProperties", false);

    std::vector<XrExtensionProperties> available_extensions(extension_count, { XR_TYPE_EXTENSION_PROPERTIES });
    result =
        xrEnumerateInstanceExtensionProperties(nullptr, extension_count, &extension_count, available_extensions.data());
    XR_CHK_WITH_RET(result, "xrEnumerateInstanceExtensionProperties", false);

    std::vector<std::string> enabled;
    for (const auto& name : requested_extensions)
    {
        auto it = std::find_if(available_extensions.begin(), available_extensions.end(),
                               [&name](const XrExtensionProperties& ext) { return name == ext.extensionName; });
        if (it != available_extensions.end())
            enabled.push_back(name);
    }

    std::vector<const char*> enabled_ptrs;
    enabled_ptrs.reserve(enabled.size());
    for (const auto& s : enabled)
        enabled_ptrs.push_back(s.c_str());

    XrInstanceCreateInfo instance_ci{ XR_TYPE_INSTANCE_CREATE_INFO };
    instance_ci.enabledExtensionCount = static_cast<uint32_t>(enabled_ptrs.size());
    instance_ci.enabledExtensionNames = enabled_ptrs.data();
    strcpy(instance_ci.applicationInfo.applicationName, "OpenXR Test Application");
    instance_ci.applicationInfo.applicationVersion = 1;
    strcpy(instance_ci.applicationInfo.engineName, "Custom");
    instance_ci.applicationInfo.engineVersion = 1;
    instance_ci.applicationInfo.apiVersion = XR_API_VERSION_1_0;

    XrInstance instance{ XR_NULL_HANDLE };
    result = xrCreateInstance(&instance_ci, &instance);
    XR_CHK_WITH_RET(result, "xrCreateInstance", false);
    bundle_.instance = instance;
    return true;
}

bool OpenXRCreator::getSystem()
{
    if (bundle_.instance == XR_NULL_HANDLE)
        return false;
    XrSystemGetInfo system_gi{ XR_TYPE_SYSTEM_GET_INFO };
    system_gi.formFactor = form_factor_;
    XrSystemId system_id = XR_NULL_SYSTEM_ID;
    XrResult result = xrGetSystem(bundle_.instance, &system_gi, &system_id);
    XR_CHK_WITH_RET(result, "xrGetSystem", false);
    bundle_.system_id = system_id;
    return true;
}

bool OpenXRCreator::createSession()
{
    if (bundle_.instance == XR_NULL_HANDLE || bundle_.system_id == XR_NULL_SYSTEM_ID)
        return false;
    XrSessionCreateInfo session_ci{ XR_TYPE_SESSION_CREATE_INFO };
    session_ci.systemId = bundle_.system_id;
    session_ci.next = nullptr;
    XrSession session{ XR_NULL_HANDLE };
    XrResult result = xrCreateSession(bundle_.instance, &session_ci, &session);
    XR_CHK_WITH_RET(result, "xrCreateSession", false);
    bundle_.session = session;
    return true;
}
