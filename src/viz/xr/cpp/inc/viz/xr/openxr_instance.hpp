// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>

#include <chrono>
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

    // True iff XR_KHR_composition_layer_depth was advertised by the
    // runtime AND we successfully enabled it. XrBackend uses this to
    // decide whether to allocate per-eye depth swapchains and chain
    // XrCompositionLayerDepthInfoKHR into each ProjectionView. CloudXR
    // uses depth for server-side reprojection; on runtimes without
    // the extension, the projection layer goes out without depth and
    // reprojection is limited to 2D pose warp.
    bool has_depth_composition_layer() const noexcept
    {
        return has_depth_composition_layer_;
    }

    // True iff XR_KHR_convert_timespec_time was advertised AND we
    // successfully resolved the conversion entry points. When true,
    // xr_time_to_steady_clock / steady_clock_to_xr_time are valid;
    // otherwise they throw. CLOCK_MONOTONIC == std::chrono::steady_clock
    // on Linux per spec.
    bool has_time_conversion() const noexcept
    {
        return has_time_conversion_;
    }
    // XrTime → std::chrono::steady_clock::time_point (CLOCK_MONOTONIC).
    // Use to correlate XR predicted_display_time with sensor-side
    // capture timestamps. Throws if has_time_conversion() == false.
    std::chrono::steady_clock::time_point xr_time_to_steady_clock(XrTime time) const;
    // Inverse direction — CLOCK_MONOTONIC → XrTime. Useful when an
    // upstream timestamp (camera capture, host sample) needs to be
    // submitted as an XrTime (e.g. xrLocateSpace at capture time).
    XrTime steady_clock_to_xr_time(std::chrono::steady_clock::time_point t) const;

private:
    XrInstance instance_ = XR_NULL_HANDLE;
    XrSystemId system_id_ = XR_NULL_SYSTEM_ID;
    bool has_depth_composition_layer_ = false;
    bool has_time_conversion_ = false;
    // Stored as type-erased PFN_xrVoidFunction so callers of this header
    // don't need to define XR_USE_TIMESPEC. Cast back to the typed PFNs
    // in the .cpp (where the platform header is included).
    PFN_xrVoidFunction xr_convert_timespec_time_to_time_ = nullptr;
    PFN_xrVoidFunction xr_convert_time_to_timespec_time_ = nullptr;
};

} // namespace viz
