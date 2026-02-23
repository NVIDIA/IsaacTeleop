// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "oxr_funcs.hpp"
#include "oxr_session_handles.hpp"

// Include platform-specific headers first
#if defined(XR_USE_PLATFORM_WIN32)
#    include <Unknwn.h>
#    include <Windows.h>
#elif defined(XR_USE_TIMESPEC)
#    include <time.h>
#endif
// Include OpenXR platform header after platform-specific includes
#include <openxr/openxr_platform.h>

#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

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
 *     XrTime time = converter.get_current_time();  // throws on failure
 * @endcode
 */
class XrTimeConverter
{
public:
    /*!
     * @brief Returns the OpenXR extensions required for time conversion on this platform.
     * @return Vector of extension name strings required for XrTime conversion.
     */
    static std::vector<std::string> get_required_extensions()
    {
#if defined(XR_USE_PLATFORM_WIN32)
        return { XR_KHR_WIN32_CONVERT_PERFORMANCE_COUNTER_TIME_EXTENSION_NAME };
#elif defined(XR_USE_TIMESPEC)
        return { XR_KHR_CONVERT_TIMESPEC_TIME_EXTENSION_NAME };
#else
        return {};
#endif
    }

    /*!
     * @brief Constructs the converter and initializes platform-specific time conversion.
     * @param handles OpenXR session handles with valid instance and xrGetInstanceProcAddr.
     * @throws std::runtime_error if the required time conversion extension is not available.
     */
    explicit XrTimeConverter(const OpenXRSessionHandles& handles) : handles_(handles)
    {
#if defined(XR_USE_PLATFORM_WIN32)
        loadExtensionFunction(handles_.instance, handles_.xrGetInstanceProcAddr,
                              "xrConvertWin32PerformanceCounterToTimeKHR",
                              reinterpret_cast<PFN_xrVoidFunction*>(&pfn_convert_win32_));
#elif defined(XR_USE_TIMESPEC)
        loadExtensionFunction(handles_.instance, handles_.xrGetInstanceProcAddr, "xrConvertTimespecTimeToTimeKHR",
                              reinterpret_cast<PFN_xrVoidFunction*>(&pfn_convert_timespec_));
#endif
    }

    /*!
     * @brief Gets the current time as XrTime using platform-specific conversion.
     * @return The current XrTime value.
     * @throws std::runtime_error if time conversion failed.
     */
    XrTime get_current_time() const
    {
        XrTime time;
#if defined(XR_USE_PLATFORM_WIN32)
        LARGE_INTEGER counter;
        if (!QueryPerformanceCounter(&counter))
        {
            throw std::runtime_error("get_current_time: QueryPerformanceCounter failed");
        }

        XrResult result = pfn_convert_win32_(handles_.instance, &counter, &time);
        if (result != XR_SUCCESS)
        {
            throw std::runtime_error("xrConvertWin32PerformanceCounterToTimeKHR failed with code " +
                                     std::to_string(result));
        }
#elif defined(XR_USE_TIMESPEC)
        struct timespec ts;
        if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0)
        {
            throw std::runtime_error(std::string("clock_gettime failed: ") + std::strerror(errno));
        }

        XrResult result = pfn_convert_timespec_(handles_.instance, &ts, &time);
        if (result != XR_SUCCESS)
        {
            throw std::runtime_error("xrConvertTimespecTimeToTimeKHR failed with code " + std::to_string(result));
        }
#else
        static_assert(false, "OpenXR time conversion not implemented on this platform.");
#endif
        return time;
    }

    /*!
     * @brief Converts a system monotonic time (in nanoseconds) to XrTime.
     * @param monotonic_ns Time in nanoseconds from the system monotonic clock
     *                     (CLOCK_MONOTONIC on Linux).
     * @return The equivalent XrTime value.
     * @throws std::runtime_error if time conversion failed.
     */
    XrTime convert_monotonic_ns_to_xrtime(int64_t monotonic_ns) const
    {
        XrTime time;
#if defined(XR_USE_PLATFORM_WIN32)
        LARGE_INTEGER frequency;
        QueryPerformanceFrequency(&frequency);

        // Convert nanoseconds back to QPC ticks, splitting to avoid overflow:
        //   ticks = seconds * freq + (remainder_ns * freq) / 1e9
        int64_t seconds = monotonic_ns / 1000000000LL;
        int64_t remainder_ns = monotonic_ns % 1000000000LL;

        LARGE_INTEGER counter;
        counter.QuadPart = seconds * frequency.QuadPart + remainder_ns * frequency.QuadPart / 1000000000LL;

        XrResult result = pfn_convert_win32_(handles_.instance, &counter, &time);
        if (result != XR_SUCCESS)
        {
            throw std::runtime_error("xrConvertWin32PerformanceCounterToTimeKHR failed with code " +
                                     std::to_string(result));
        }
#elif defined(XR_USE_TIMESPEC)
        struct timespec ts;
        ts.tv_sec = static_cast<time_t>(monotonic_ns / 1000000000LL);
        ts.tv_nsec = static_cast<long>(monotonic_ns % 1000000000LL);

        XrResult result = pfn_convert_timespec_(handles_.instance, &ts, &time);
        if (result != XR_SUCCESS)
        {
            throw std::runtime_error("xrConvertTimespecTimeToTimeKHR failed with code " + std::to_string(result));
        }
#else
        static_assert(false, "OpenXR time conversion not implemented on this platform.");
#endif
        return time;
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
