// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstdint>
#include <cstring>
#include <functional>
#include <stdexcept>
#include <string>

#ifdef _WIN32
#    ifndef WIN32_LEAN_AND_MEAN
#        define WIN32_LEAN_AND_MEAN
#    endif
#    ifndef NOMINMAX
#        define NOMINMAX
#    endif
#    include <Windows.h>
#else
#    include <time.h>
#endif

namespace core
{

/// All timestamps are int64_t nanoseconds.
using clock_ns_t = int64_t;

/// Optional translator that converts a monotonic timestamp (ns) to another
/// time domain (e.g. XrTime).  When null, the client reports raw monotonic.
using ClockTranslator = std::function<clock_ns_t(clock_ns_t monotonic_ns)>;

constexpr uint16_t kDefaultClockPort = 5555;

// ============================================================================
// Wire Protocol
// ============================================================================

/// Fixed-size packet exchanged between client and server.
///
/// Client -> Server: only t1 is meaningful (client transmit time).
/// Server -> Client: t1 is echoed back, t2 = server receive, t3 = server transmit.
/// Client records t4 (client receive) locally on arrival.
struct ClockPacket
{
    clock_ns_t t1{ 0 }; // client transmit timestamp
    clock_ns_t t2{ 0 }; // server receive timestamp
    clock_ns_t t3{ 0 }; // server transmit timestamp

    void serialize(uint8_t* buf) const
    {
        std::memcpy(buf, this, sizeof(ClockPacket));
    }

    static ClockPacket deserialize(const uint8_t* buf)
    {
        ClockPacket pkt;
        std::memcpy(&pkt, buf, sizeof(ClockPacket));
        return pkt;
    }
};

static_assert(sizeof(ClockPacket) == 3 * sizeof(clock_ns_t), "ClockPacket must be tightly packed");

// ============================================================================
// Timestamp helpers
// ============================================================================

#ifdef _WIN32

namespace detail
{

/// Cached QPC frequency (counts per second). Initialised once on first use.
inline int64_t qpc_frequency()
{
    static int64_t freq = []()
    {
        LARGE_INTEGER f;
        QueryPerformanceFrequency(&f);
        return f.QuadPart;
    }();
    return freq;
}

/// Read QueryPerformanceCounter and convert to nanoseconds.
inline clock_ns_t qpc_ns()
{
    LARGE_INTEGER counter;
    QueryPerformanceCounter(&counter);
    return static_cast<clock_ns_t>(counter.QuadPart) * 1'000'000'000LL / qpc_frequency();
}

} // namespace detail

/// Read CLOCK_MONOTONIC equivalent (QPC) as nanoseconds.
inline clock_ns_t get_monotonic_ns()
{
    return detail::qpc_ns();
}

/// Read hardware counter (QPC) as nanoseconds — server-side default.
inline clock_ns_t get_monotonic_raw_ns()
{
    return detail::qpc_ns();
}

#else // POSIX

namespace detail
{

inline clock_ns_t posix_clock_ns(clockid_t clk)
{
    struct timespec ts;
    if (clock_gettime(clk, &ts) != 0)
    {
        throw std::runtime_error("clock_gettime failed: " + std::string(std::strerror(errno)));
    }
    return static_cast<clock_ns_t>(ts.tv_sec) * 1'000'000'000LL + static_cast<clock_ns_t>(ts.tv_nsec);
}

} // namespace detail

/// Read CLOCK_MONOTONIC as nanoseconds.
inline clock_ns_t get_monotonic_ns()
{
    return detail::posix_clock_ns(CLOCK_MONOTONIC);
}

/// Read CLOCK_MONOTONIC_RAW as nanoseconds — server-side default.
inline clock_ns_t get_monotonic_raw_ns()
{
    return detail::posix_clock_ns(CLOCK_MONOTONIC_RAW);
}

#endif

/// Convenience: convert nanoseconds to fractional seconds.
inline double ns_to_sec(clock_ns_t ns)
{
    return static_cast<double>(ns) / 1e9;
}

// ============================================================================
// Measurement record (client-side)
// ============================================================================

struct ClockMeasurement
{
    clock_ns_t t1{ 0 }; // client transmit
    clock_ns_t t2{ 0 }; // server receive
    clock_ns_t t3{ 0 }; // server transmit
    clock_ns_t t4{ 0 }; // client receive

    /// Round-trip time: (t4 - t1) - (t3 - t2)
    clock_ns_t rtt() const
    {
        return (t4 - t1) - (t3 - t2);
    }

    /// Clock offset: ((t2 - t1) + (t3 - t4)) / 2
    clock_ns_t offset() const
    {
        return ((t2 - t1) + (t3 - t4)) / 2;
    }
};

} // namespace core
