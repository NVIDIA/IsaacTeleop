// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "clock_types.hpp"

#include <memory>
#include <string>
#include <vector>

namespace core
{

/// Translates CLOCK_MONOTONIC timestamps to XrTime using the OpenXR runtime.
///
/// Creates a minimal OpenXR instance (headless, time-conversion only) and uses
/// xrConvertTimespecTimeToTimeKHR (Linux) or
/// xrConvertWin32PerformanceCounterToTimeKHR (Windows) to translate.
class XrClockTranslator : public std::enable_shared_from_this<XrClockTranslator>
{
public:
    /** @brief Create an XrClockTranslator backed by a headless OpenXR instance.
     *  @param app_name         Application name for xrCreateInstance.
     *  @param extra_extensions Additional extensions to request.
     *  @throws std::runtime_error on failure.
     */
    static std::shared_ptr<XrClockTranslator> Create(const std::string& app_name = "ClockSyncXr",
                                                     const std::vector<std::string>& extra_extensions = {});
    ~XrClockTranslator();

    XrClockTranslator(const XrClockTranslator&) = delete;
    XrClockTranslator& operator=(const XrClockTranslator&) = delete;

    /// Translate a CLOCK_MONOTONIC nanosecond timestamp to XrTime (nanoseconds).
    clock_ns_t translate(clock_ns_t monotonic_ns) const;

    /// Create a ClockTranslator function suitable for ClockClient.
    ClockTranslator make_translator();

private:
    XrClockTranslator();
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace core
