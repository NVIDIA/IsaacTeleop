// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>
#include <oxr_utils/oxr_types.hpp>

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
    bool create_instance(const std::string& app_name, const std::vector<std::string>& extensions);
    bool create_system();
    bool create_session();
    bool create_reference_space();
    bool begin();

    XrInstance instance_;
    XrSystemId system_id_;
    XrSession session_;
    XrSpace space_;
};

} // namespace core
