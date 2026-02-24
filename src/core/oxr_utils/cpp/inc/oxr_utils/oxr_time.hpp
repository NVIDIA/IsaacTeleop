// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "os_time.hpp"
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
 *     XrTime time = converter.os_monotonic_now();          // throws on failure
 *     int64_t ns   = core::os_monotonic_now_ns();         // no OpenXR needed
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
        loadExtensionFunction(handles_.instance, handles_.xrGetInstanceProcAddr,
                              "xrConvertTimeToWin32PerformanceCounterKHR",
                              reinterpret_cast<PFN_xrVoidFunction*>(&pfn_time_to_win32_));
#elif defined(XR_USE_TIMESPEC)
        loadExtensionFunction(handles_.instance, handles_.xrGetInstanceProcAddr, "xrConvertTimespecTimeToTimeKHR",
                              reinterpret_cast<PFN_xrVoidFunction*>(&pfn_convert_timespec_));
        loadExtensionFunction(handles_.instance, handles_.xrGetInstanceProcAddr, "xrConvertTimeToTimespecTimeKHR",
                              reinterpret_cast<PFN_xrVoidFunction*>(&pfn_time_to_timespec_));
#endif
    }

    /*!
     * @brief Returns the current OS monotonic time as XrTime.
     *
     * Reads the current monotonic time via os_monotonic_now_ns() (no OpenXR
     * dependency) and converts it to XrTime using the runtime extension.
     *
     * @return The current XrTime value aligned to the system monotonic clock.
     * @throws std::runtime_error if the OS clock query or time conversion fails.
     */
    XrTime os_monotonic_now() const
    {
        return convert_monotonic_ns_to_xrtime(os_monotonic_now_ns());
    }

    /*!
     * @brief Converts a system monotonic time (in nanoseconds) to XrTime.
     *
     * @param monotonic_ns Time in nanoseconds from the system monotonic clock
     *                     (CLOCK_MONOTONIC on Linux; on Windows, nanoseconds
     *                     derived from QueryPerformanceCounter / QueryPerformanceFrequency).
     *
     * @note On Windows, monotonic_ns **must** originate from the high-resolution
     *       performance counter (QueryPerformanceCounter) used internally by
     *       pfn_convert_win32_ (xrConvertWin32PerformanceCounterToTimeKHR).
     *       Passing nanoseconds from any other clock domain (e.g., std::chrono::system_clock,
     *       a device-specific clock) will produce an incorrect XrTime value because the
     *       tick-to-nanosecond scaling assumed here is only valid for that counter.
     *
     * @return The equivalent XrTime value.
     * @throws std::runtime_error if time conversion failed.
     */
    XrTime convert_monotonic_ns_to_xrtime(int64_t monotonic_ns) const
    {
        XrTime time;
#if defined(XR_USE_PLATFORM_WIN32)
        // monotonic_ns must be derived from QueryPerformanceCounter; inputs from other
        // clock sources will yield incorrect results when passed to pfn_convert_win32_.
        LARGE_INTEGER frequency;
        if (!QueryPerformanceFrequency(&frequency))
        {
            throw std::runtime_error("convert_monotonic_ns_to_xrtime: QueryPerformanceFrequency failed");
        }

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

    /*!
     * @brief Converts an XrTime value to system monotonic nanoseconds.
     * @param time XrTime value to convert.
     * @return Nanoseconds on the system monotonic clock (CLOCK_MONOTONIC on Linux).
     * @throws std::runtime_error if time conversion failed.
     */
    int64_t convert_xrtime_to_monotonic_ns(XrTime time) const
    {
#if defined(XR_USE_PLATFORM_WIN32)
        LARGE_INTEGER counter;
        XrResult result = pfn_time_to_win32_(handles_.instance, time, &counter);
        if (result != XR_SUCCESS)
        {
            throw std::runtime_error("xrConvertTimeToWin32PerformanceCounterKHR failed with code " +
                                     std::to_string(result));
        }

        LARGE_INTEGER frequency;
        if (!QueryPerformanceFrequency(&frequency))
        {
            throw std::runtime_error("convert_xrtime_to_monotonic_ns: QueryPerformanceFrequency failed");
        }
        int64_t seconds = counter.QuadPart / frequency.QuadPart;
        int64_t remainder_ticks = counter.QuadPart % frequency.QuadPart;
        return seconds * 1000000000LL + remainder_ticks * 1000000000LL / frequency.QuadPart;
#elif defined(XR_USE_TIMESPEC)
        struct timespec ts;
        XrResult result = pfn_time_to_timespec_(handles_.instance, time, &ts);
        if (result != XR_SUCCESS)
        {
            throw std::runtime_error("xrConvertTimeToTimespecTimeKHR failed with code " + std::to_string(result));
        }
        return static_cast<int64_t>(ts.tv_sec) * 1000000000LL + static_cast<int64_t>(ts.tv_nsec);
#else
        static_assert(false, "OpenXR time conversion not implemented on this platform.");
#endif
    }

private:
    OpenXRSessionHandles handles_;

#if defined(XR_USE_PLATFORM_WIN32)
    PFN_xrConvertWin32PerformanceCounterToTimeKHR pfn_convert_win32_{};
    PFN_xrConvertTimeToWin32PerformanceCounterKHR pfn_time_to_win32_{};
#elif defined(XR_USE_TIMESPEC)
    PFN_xrConvertTimespecTimeToTimeKHR pfn_convert_timespec_{};
    PFN_xrConvertTimeToTimespecTimeKHR pfn_time_to_timespec_{};
#endif
};

} // namespace core
