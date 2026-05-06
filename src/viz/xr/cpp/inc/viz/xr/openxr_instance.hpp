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
//
// system_wait_seconds: how long to keep polling xrGetSystem when the
// runtime returns XR_ERROR_FORM_FACTOR_UNAVAILABLE (no HMD yet). This
// is the normal startup state for CloudXR / streaming runtimes — the
// runtime is up but the headset client hasn't connected.
//   0 (default) — fail fast on first xrGetSystem error.
//   > 0         — poll for up to that many seconds.
//   < 0         — poll forever (interrupt with SIGINT to break the loop).
class OpenXrInstance
{
public:
    OpenXrInstance(const std::string& app_name,
                   const std::vector<std::string>& extra_extensions,
                   int system_wait_seconds = 0);
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
