// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>

#include <chrono>
#include <string>
#include <vector>

namespace viz
{

// Owns an XrInstance + queries the HMD XrSystemId.
//
// system_wait_seconds: how long to keep polling xrGetSystem when the
// runtime returns XR_ERROR_FORM_FACTOR_UNAVAILABLE (HMD not yet
// connected — common with CloudXR / streaming runtimes).
//   0 — fail fast on first error.
//   >0 — poll for that many seconds, then throw.
//   <0 — poll forever (Ctrl-C to break).
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

    // True iff XR_KHR_composition_layer_depth is enabled. Drives whether
    // XrBackend allocates depth swapchains + chains depth_info per view.
    bool has_depth_composition_layer() const noexcept
    {
        return has_depth_composition_layer_;
    }

    // True iff XR_KHR_convert_timespec_time is enabled. When false the
    // conversion methods throw. CLOCK_MONOTONIC == steady_clock on Linux.
    bool has_time_conversion() const noexcept
    {
        return has_time_conversion_;
    }
    // Correlate XrTime with steady_clock-based sensor timestamps.
    // Throw if !has_time_conversion().
    std::chrono::steady_clock::time_point xr_time_to_steady_clock(XrTime time) const;
    XrTime steady_clock_to_xr_time(std::chrono::steady_clock::time_point t) const;

private:
    XrInstance instance_ = XR_NULL_HANDLE;
    XrSystemId system_id_ = XR_NULL_SYSTEM_ID;
    bool has_depth_composition_layer_ = false;
    bool has_time_conversion_ = false;
    // Type-erased so this header doesn't need XR_USE_TIMESPEC; .cpp
    // casts back to the typed PFNs.
    PFN_xrVoidFunction xr_convert_timespec_time_to_time_ = nullptr;
    PFN_xrVoidFunction xr_convert_time_to_timespec_time_ = nullptr;
};

} // namespace viz
