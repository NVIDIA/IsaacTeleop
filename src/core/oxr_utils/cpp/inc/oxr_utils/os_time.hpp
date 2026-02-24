// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// Platform-specific monotonic clock utilities — no OpenXR dependency.

#if defined(_WIN32)
#    include <Windows.h>
#else
#    include <cerrno>
#    include <cstring>
#    include <time.h>
#endif

#include <cstdint>
#include <stdexcept>
#include <string>

namespace core
{

/*!
 * @brief Returns the current OS monotonic time in nanoseconds.
 *
 * On Linux this reads CLOCK_MONOTONIC via clock_gettime().
 * On Windows this reads the high-resolution performance counter via
 * QueryPerformanceCounter() / QueryPerformanceFrequency().
 *
 * The returned value is suitable as the local-common-clock nanosecond
 * argument to XrTimeConverter::convert_monotonic_ns_to_xrtime() and for
 * populating DeviceDataTimestamp::available_time_local_common_clock /
 * sample_time_local_common_clock.
 *
 * @return Nanoseconds on the system monotonic clock.
 * @throws std::runtime_error if the OS clock query fails.
 */
inline int64_t os_monotonic_now_ns()
{
#if defined(_WIN32)
    // Cache the QPC frequency: it is constant after boot and QueryPerformanceFrequency
    // is expensive to call in a tight loop. The static initialiser is thread-safe (C++11).
    static const LARGE_INTEGER frequency = []()
    {
        LARGE_INTEGER f;
        if (!QueryPerformanceFrequency(&f))
        {
            throw std::runtime_error("os_monotonic_now_ns: QueryPerformanceFrequency failed");
        }
        return f;
    }();
    LARGE_INTEGER counter;
    if (!QueryPerformanceCounter(&counter))
    {
        throw std::runtime_error("os_monotonic_now_ns: QueryPerformanceCounter failed");
    }
    int64_t seconds = counter.QuadPart / frequency.QuadPart;
    int64_t remainder_ticks = counter.QuadPart % frequency.QuadPart;
    return seconds * 1000000000LL + remainder_ticks * 1000000000LL / frequency.QuadPart;
#else
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0)
    {
        throw std::runtime_error(std::string("os_monotonic_now_ns: clock_gettime failed: ") + std::strerror(errno));
    }
    return static_cast<int64_t>(ts.tv_sec) * 1000000000LL + static_cast<int64_t>(ts.tv_nsec);
#endif
}

} // namespace core
