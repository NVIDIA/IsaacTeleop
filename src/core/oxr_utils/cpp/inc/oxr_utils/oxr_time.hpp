// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "oxr_session_handles.hpp"

// Include platform-specific headers first
#if defined(XR_USE_PLATFORM_WIN32)
#    include <windows.h>
#elif defined(XR_USE_TIMESPEC)
#    include <time.h>
#endif
// Include OpenXR platform header after platform-specific includes
#include <openxr/openxr_platform.h>

#include <iostream>
#include <stdexcept>

namespace core
{

/*!
 * @brief Utility class for converting platform time to OpenXR time.
 *
 * This class encapsulates the platform-specific time conversion logic
 * using OpenXR extension functions. It can be used by any component that
 * needs to obtain the current XrTime from system clocks.
 *
 * Usage:
 * @code
 *     XrTimeConverter converter(handles);  // throws if extension not available
 *     XrTime time;
 *     if (converter.get_current_time(time)) {
 *         // use time
 *     }
 * @endcode
 */
class XrTimeConverter
{
public:
    /*!
     * @brief Constructs the converter and initializes platform-specific time conversion.
     * @param handles OpenXR session handles with valid instance and xrGetInstanceProcAddr.
     * @throws std::runtime_error if the required time conversion extension is not available.
     */
    explicit XrTimeConverter(const OpenXRSessionHandles& handles) : handles_(handles)
    {
#if defined(XR_USE_PLATFORM_WIN32)
        handles_.xrGetInstanceProcAddr(handles_.instance, "xrConvertWin32PerformanceCounterToTimeKHR",
                                       reinterpret_cast<PFN_xrVoidFunction*>(&pfn_convert_win32_));
        if (!pfn_convert_win32_)
        {
            throw std::runtime_error("xrConvertWin32PerformanceCounterToTimeKHR not available");
        }
#elif defined(XR_USE_TIMESPEC)
        handles_.xrGetInstanceProcAddr(handles_.instance, "xrConvertTimespecTimeToTimeKHR",
                                       reinterpret_cast<PFN_xrVoidFunction*>(&pfn_convert_timespec_));
        if (!pfn_convert_timespec_)
        {
            throw std::runtime_error("xrConvertTimespecTimeToTimeKHR not available");
        }
#endif
    }

    /*!
     * @brief Gets the current time as XrTime using platform-specific conversion.
     * @param[out] time The current XrTime value.
     * @return true on success, false if time conversion failed.
     */
    bool get_current_time(XrTime& time) const
    {
#if defined(XR_USE_PLATFORM_WIN32)
        LARGE_INTEGER counter;
        QueryPerformanceCounter(&counter);

        if (pfn_convert_win32_)
        {
            pfn_convert_win32_(handles_.instance, &counter, &time);
            return true;
        }
#elif defined(XR_USE_TIMESPEC)
        struct timespec ts;
        clock_gettime(CLOCK_MONOTONIC, &ts);

        if (pfn_convert_timespec_)
        {
            pfn_convert_timespec_(handles_.instance, &ts, &time);
            return true;
        }
#endif
        std::cerr << "Cannot get time - time conversion not available" << std::endl;
        return false;
    }

private:
    OpenXRSessionHandles handles_;

#if defined(XR_USE_PLATFORM_WIN32)
    PFN_xrConvertWin32PerformanceCounterToTimeKHR pfn_convert_win32_{};
#elif defined(XR_USE_TIMESPEC)
    PFN_xrConvertTimespecTimeToTimeKHR pfn_convert_timespec_{};
#endif
};

} // namespace core
