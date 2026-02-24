// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>
#include <schema/timestamp_generated.h>

#include <functional>
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
     * @brief Callback type for serialize_all.
     *
     * Receives (timestamp, data_ptr, data_size) for each serialized record.
     *
     * @warning The data_ptr and data_size are only valid for the duration of the
     *          callback invocation. The buffer is owned by a FlatBufferBuilder
     *          local to the tracker's serialize_all implementation and will be
     *          destroyed on return. If you need the bytes after the callback
     *          returns, copy them into your own storage before returning.
     */
    using RecordCallback = std::function<void(const DeviceDataTimestamp&, const uint8_t*, size_t)>;

    /**
     * @brief Serialize all records accumulated since the last update() call.
     *
     * Each call to update() clears the previous batch and accumulates a fresh
     * set of records (one for OpenXR-direct trackers; potentially many for
     * SchemaTracker-based tensor-device trackers). serialize_all emits every
     * record in that batch via the callback.
     *
     * For read access without MCAP recording, use the tracker's typed get_*()
     * accessors, which always reflect the last record in the current batch.
     *
     * @note The buffer pointer passed to the callback is only valid for the
     *       duration of that callback call. Copy if you need it beyond return.
     *
     * @param channel_index Which record channel to serialize (0-based).
     * @param callback Invoked once per record with (timestamp, data_ptr, data_size).
     */
    virtual void serialize_all(size_t channel_index, const RecordCallback& callback) const = 0;
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
     * This should return the fully qualified FlatBuffer type name (e.g., "core.HandPose")
     * which matches the root_type defined in the .fbs schema file.
     */
    virtual std::string_view get_schema_name() const = 0;

    /**
     * @brief Get the binary FlatBuffer schema text for MCAP recording.
     */
    virtual std::string_view get_schema_text() const = 0;

    /**
     * @brief Get the channel names for MCAP recording.
     *
     * Every tracker must return at least one non-empty channel name. The returned
     * vector size determines how many times serialize_all() is called per update,
     * with the vector index used as the channel_index argument.
     *
     * Single-channel trackers return one name (e.g. {"head"}).
     * Multi-channel trackers return multiple (e.g. {"left_hand", "right_hand"}).
     *
     * The MCAP recorder combines each channel name with the base channel name
     * provided at registration as "base_name/channel_name". For example, a
     * single-channel head tracker registered with base name "tracking" produces
     * the MCAP channel "tracking/head". A multi-channel hand tracker registered
     * with base name "hands" produces "hands/left_hand" and "hands/right_hand".
     *
     * @return Non-empty vector of non-empty channel name strings.
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
