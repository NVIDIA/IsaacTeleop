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
struct OpenXRSessionHandles;
class ITrackerFactory;

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
     * Receives (log_time_ns, data_ptr, data_size) for each serialized record.
     *
     * @param log_time_ns  Monotonic nanoseconds used as the MCAP logTime/publishTime
     *                     for this record. This is the time at which the recording
     *                     system processed the record (update-tick time), not the
     *                     sample capture time. The full per-sample DeviceDataTimestamp
     *                     (including sample_time and raw_device_time) is embedded
     *                     inside the serialized FlatBuffer payload.
     *
     * @warning The data_ptr and data_size are only valid for the duration of the
     *          callback invocation. The buffer is owned by a FlatBufferBuilder
     *          local to the tracker's serialize_all implementation and will be
     *          destroyed on return. If you need the bytes after the callback
     *          returns, copy them into your own storage before returning.
     */
    using RecordCallback = std::function<void(int64_t log_time_ns, const uint8_t*, size_t)>;

    /**
     * @brief Serialize all records accumulated since the last update() call.
     *
     * Each call to update() clears the previous batch and accumulates a fresh
     * set of records (one for OpenXR-direct trackers; potentially many for
     * SchemaTracker-based tensor-device trackers). serialize_all emits every
     * record in that batch via the callback.
     *
     * @note For multi-channel trackers the recorder calls serialize_all once per
     *       channel index (channel_index = 0, 1, … N-1) after each update().
     *       All serialize_all calls for a given update() are guaranteed to
     *       complete before the next update() is issued. Implementations may
     *       therefore maintain a single shared pending batch and clear it at the
     *       start of the next update(); there is no need to track per-channel
     *       drain state.
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

// Base interface for all trackers
// PUBLIC API: Only exposes methods that external users should call
class ITracker
{
public:
    virtual ~ITracker() = default;

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

    /**
     * @brief Create the tracker's implementation via the provided factory.
     *
     * Uses double dispatch: the tracker calls the factory method specific to its
     * type (e.g., factory.create_head_tracker_impl()), so the factory controls
     * which concrete impl is constructed without the tracker needing to know the
     * session type.
     *
     * @param factory Session-provided factory (e.g., LiveDeviceIOFactory).
     * @return Owning pointer to the newly created impl.
     */
    virtual std::unique_ptr<ITrackerImpl> create_tracker_impl(ITrackerFactory& factory) const = 0;
};

} // namespace core
