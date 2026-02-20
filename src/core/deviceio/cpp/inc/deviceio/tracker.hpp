// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <flatbuffers/flatbuffer_builder.h>
#include <openxr/openxr.h>
#include <schema/timestamp_generated.h>

#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

// Forward declarations
class DeviceIOSession;
struct OpenXRSessionHandles;

// Base interface for tracker implementations
// These are the actual worker objects that get updated by the session
class ITrackerImpl
{
public:
    virtual ~ITrackerImpl() = default;

    // Update the tracker with the current time
    virtual bool update(XrTime time) = 0;

    /**
     * @brief Serialize a single record channel to a FlatBuffer.
     *
     * Each call serializes the XXRecord type (data + DeviceDataTimestamp) for
     * the given channel. Multi-channel trackers (e.g., left/right hand) are
     * called once per channel.
     *
     * @param builder Output FlatBufferBuilder to write serialized data into.
     * @param channel_index Which record channel to serialize (0-based).
     * @return DeviceDataTimestamp for MCAP log time.
     */
    virtual DeviceDataTimestamp serialize(flatbuffers::FlatBufferBuilder& builder, size_t channel_index) const = 0;
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
    virtual std::string_view get_name() const = 0;

    /**
     * @brief Get the FlatBuffer schema name (root type) for MCAP recording.
     *
     * Returns the fully qualified FlatBuffer record type name (e.g.,
     * "core.HandPoseRecord") matching the root_type in the .fbs schema.
     */
    virtual std::string_view get_schema_name() const = 0;

    /**
     * @brief Get the binary FlatBuffer schema for MCAP recording.
     */
    virtual std::string_view get_schema_text() const = 0;

    /**
     * @brief Get the MCAP channel names this tracker produces.
     *
     * Single-channel trackers return one name (e.g., {"head"}).
     * Multi-channel trackers return multiple (e.g., {"left_hand", "right_hand"}).
     * The indices correspond to the channel_index parameter in
     * ITrackerImpl::serialize().
     */
    virtual std::vector<std::string> get_record_channels() const = 0;

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
