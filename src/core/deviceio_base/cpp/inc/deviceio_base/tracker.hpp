// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>

#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

// Forward declarations
struct OpenXRSessionHandles;
class ITrackerFactory;

// Base interface for tracker implementations.
// The actual worker objects updated each frame by DeviceIOSession.
class ITrackerImpl
{
public:
    virtual ~ITrackerImpl() = default;

    virtual bool update(XrTime time) = 0;
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
// Public API: configuration, extension requirements, and typed data accessors.
class ITracker
{
public:
    virtual ~ITracker() = default;

    virtual std::vector<std::string> get_required_extensions() const = 0;
    virtual std::string_view get_name() const = 0;

    /**
     * @brief Create the tracker's implementation via the provided factory.
     *
     * Uses double dispatch: the tracker calls the factory method specific to its
     * concrete type. The factory (e.g. LiveDeviceIOFactory) owns the optional
     * MCAP writer and creates typed McapTrackerChannels for each impl that
     * should record.
     *
     * @param factory Session-provided factory.
     * @return Owning pointer to the newly created impl.
     */
    virtual std::unique_ptr<ITrackerImpl> create_tracker_impl(ITrackerFactory& factory) const = 0;
};

} // namespace core
