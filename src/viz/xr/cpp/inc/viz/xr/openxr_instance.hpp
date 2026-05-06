// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>

#include <string>
#include <vector>

namespace viz
{

// Owns an XrInstance + queries the HMD XrSystemId. Required input
// for both the Vulkan-via-XR device negotiation and the XrSession.
class OpenXrInstance
{
public:
    OpenXrInstance(const std::string& app_name, const std::vector<std::string>& extra_extensions);
    ~OpenXrInstance();

    OpenXrInstance(const OpenXrInstance&) = delete;
    OpenXrInstance& operator=(const OpenXrInstance&) = delete;

    XrInstance instance() const noexcept
    {
        return instance_;
    }
    XrSystemId system_id() const noexcept
    {
        return system_id_;
    }

private:
    XrInstance instance_ = XR_NULL_HANDLE;
    XrSystemId system_id_ = XR_NULL_SYSTEM_ID;
};

} // namespace viz
