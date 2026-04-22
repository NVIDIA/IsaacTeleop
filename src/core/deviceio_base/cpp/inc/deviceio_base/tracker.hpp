// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>

namespace core
{

// Base interface for tracker implementations.
// The actual worker objects updated each frame by DeviceIOSession.
class ITrackerImpl
{
public:
    virtual ~ITrackerImpl() = default;

    /**
     * @brief Updates tracker state for the current frame.
     *
     * @param monotonic_time_ns Current time from the system monotonic clock, in nanoseconds
     *        (same domain as core::os_monotonic_now_ns()).
     *
     * @throws std::runtime_error On critical tracker/runtime failures.
     * @note A thrown exception indicates a fatal condition; the application is
     *       expected to terminate rather than continue running.
     */
    virtual void update(int64_t monotonic_time_ns) = 0;
};

/**
 * @brief Session handle for resolving `ITracker` implementations.
 *
 * @note Identity contract: Implementations (e.g. `DeviceIOSession`) resolve
 *       `get_tracker_impl(const ITracker& tracker)` by the tracker object's
 *       address (`&tracker`), not by value equality. Callers must pass the
 *       same underlying `ITracker` object that was registered with the session
 *       — for example the same instance whose `shared_ptr` was in the vector
 *       passed to `DeviceIOSession::run`. Copying that `shared_ptr` (or taking
 *       another reference/pointer to the same tracker object) is fine. Creating
 *       a new, distinct `ITracker` instance, even if it is logically equivalent,
 *       will not match the map and typically yields "Tracker implementation not found".
 */
// Interface for looking up tracker implementations from a session.
// DeviceIOSession implements this so that typed tracker get_*() methods can
// retrieve their impl without depending on the concrete session class.
class ITrackerSession
{
public:
    virtual ~ITrackerSession() = default;
    virtual const ITrackerImpl& get_tracker_impl(const class ITracker& tracker) const = 0;
};

// Base interface for all trackers.
// Public API: identity and typed data accessors.
// DeviceIOSession::get_required_extensions(trackers) aggregates required extensions for the session.
class ITracker
{
public:
    virtual ~ITracker() = default;

    virtual std::string_view get_name() const = 0;
};

} // namespace core
