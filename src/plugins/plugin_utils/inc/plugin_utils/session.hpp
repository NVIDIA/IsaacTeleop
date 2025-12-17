// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// OpenXR initialization and session management
#pragma once

#include <openxr/openxr.h>

#include <string>
#include <vector>

namespace plugin_utils
{

struct SessionConfig
{
    std::string app_name = "ControllerSyntheticHands";
    XrFormFactor form_factor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;
    XrReferenceSpaceType reference_space_type = XR_REFERENCE_SPACE_TYPE_STAGE;
    std::vector<const char*> extensions;
    bool use_overlay_mode = true; // Overlay sessions don't receive input
};

struct SessionHandles
{
    XrInstance instance = XR_NULL_HANDLE;
    XrSystemId system_id = XR_NULL_SYSTEM_ID;
    XrSession session = XR_NULL_HANDLE;
    XrSpace reference_space = XR_NULL_HANDLE;
};

class Session
{
public:
    static Session* Create(const SessionConfig& config);

    ~Session();

    Session(const Session&) = delete;
    Session& operator=(const Session&) = delete;

    const SessionHandles& handles() const
    {
        return handles_;
    }

    bool begin();
    void end();

    template <typename T>
    bool get_extension_function(const char* name, T* func)
    {
        return XR_SUCCEEDED(xrGetInstanceProcAddr(handles_.instance, name, reinterpret_cast<PFN_xrVoidFunction*>(func)));
    }

private:
    Session() = default;
    bool initialize(const SessionConfig& config);
    bool create_instance(const SessionConfig& config);
    bool get_system();
    bool create_session();
    bool create_reference_space(XrReferenceSpaceType type);
    void cleanup();

    SessionHandles handles_;
    SessionConfig config_;
};

} // namespace plugin_utils
