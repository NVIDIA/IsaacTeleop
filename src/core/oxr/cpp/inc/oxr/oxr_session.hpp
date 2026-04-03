// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>
#include <oxr_utils/oxr_session_handles.hpp>

#include <memory>
#include <string>
#include <type_traits>
#include <vector>

namespace core
{

// OpenXR session management - creates and manages a headless OpenXR session
class OpenXRSession
{
public:
    OpenXRSession(const std::string& app_name, const std::vector<std::string>& extensions);

    // Get session handles for use with trackers
    OpenXRSessionHandles get_handles() const;

private:
    // PFN_* deleter types work when OpenXR was already included with XR_NO_PROTOTYPES (no xrDestroy* declarations).
    using InstanceHandle = std::unique_ptr<std::remove_pointer_t<XrInstance>, PFN_xrDestroyInstance>;
    using SessionHandle = std::unique_ptr<std::remove_pointer_t<XrSession>, PFN_xrDestroySession>;
    using SpaceHandle = std::unique_ptr<std::remove_pointer_t<XrSpace>, PFN_xrDestroySpace>;

    // Initialization methods
    void create_instance(const std::string& app_name, const std::vector<std::string>& extensions);
    void create_system();
    void create_session();
    void create_reference_space();
    void begin();

    InstanceHandle instance_;
    XrSystemId system_id_;
    SessionHandle session_;
    SpaceHandle space_;
};

} // namespace core
