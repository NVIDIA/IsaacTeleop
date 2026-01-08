// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "flatbuffers/flatbuffer_builder.h"

#include <oxr_utils/oxr_funcs.hpp>
#include <oxr_utils/oxr_types.hpp>

#include <memory>
#include <string>
#include <vector>

namespace core
{


// Forward declarations
class DeviceIOSession;

// Base interface for tracker implementations
// These are the actual worker objects that get updated by the session
class ITrackerImpl
{
public:
    virtual ~ITrackerImpl() = default;

    // Update the tracker with the current time
    virtual bool update(XrTime time) = 0;

    /**
     * @brief Get the name of this tracker (used for MCAP channel naming).
     */
    virtual std::string get_name() const = 0;

    /**
     * @brief Get the FlatBuffer schema name (root type) for MCAP recording.
     *
     * This should return the fully qualified FlatBuffer type name (e.g., "core.HandPose")
     * which matches the root_type defined in the .fbs schema file.
     */
    virtual std::string get_schema_name() const = 0;

    /**
     * @brief Get the binary FlatBuffer schema text for MCAP recording.
     */
    virtual std::string get_schema_text() const = 0;

    /**
     * @brief Serialize the tracker data to a FlatBuffer.
     *
     * @param builder Output FlatBufferBuilder to write serialized data into.
     * @param out_timestamp Output timestamp in nanoseconds (XrTime) for MCAP recording.
     */
    virtual void serialize(flatbuffers::FlatBufferBuilder& builder, int64_t* out_timestamp = nullptr) const = 0;
};

// Base interface for all trackers
// PUBLIC API: Only exposes methods that external users should call
// Trackers are responsible for initialization and creating their impl
class ITracker
{
public:
    virtual ~ITracker() = default;

    // Public API - visible to all users
    virtual std::vector<std::string> get_required_extensions() const = 0;
    virtual std::string get_name() const = 0;

protected:
    // Internal lifecycle methods - only accessible to friend classes
    // External users should NOT call these directly
    friend class DeviceIOSession;

    // Initialize the tracker and return its implementation
    // The tracker will use handles.space as the base coordinate system for reporting poses
    // Returns nullptr on failure
    virtual std::shared_ptr<ITrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const = 0;
};

} // namespace core
