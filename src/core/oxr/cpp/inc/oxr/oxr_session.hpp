// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>
#include <oxr_utils/oxr_session_handles.hpp>

#include <memory>
#include <string>
#include <vector>

namespace core
{

// OpenXR session management - creates and manages a headless OpenXR session
class OpenXRSession
{
public:
    ~OpenXRSession();

    // Static factory method - returns nullptr on failure
    static std::shared_ptr<OpenXRSession> Create(const std::string& app_name,
                                                 const std::vector<std::string>& extensions = {});

    // Get session handles for use with trackers
    OpenXRSessionHandles get_handles() const;

private:
    // Private constructor - use Create() instead
    OpenXRSession();

    // Initialization methods
    void create_instance(const std::string& app_name, const std::vector<std::string>& extensions);
    void create_system();
    void create_session();
    void create_reference_space();
    void begin();

    XrInstance instance_;
    XrSystemId system_id_;
    XrSession session_;
    XrSpace space_;
};

} // namespace core
