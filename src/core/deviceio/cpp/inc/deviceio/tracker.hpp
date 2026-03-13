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
class ITracker;
class ITrackerImpl;
class ITrackerSession;

// Base for tracker implementations (live and replay). No schema/channel here;
// that lives on the tracker.
class ITrackerImpl
{
public:
    virtual ~ITrackerImpl() = default;
};

/** Live (OpenXR) tracker impl: update_live(monotonic_ns) and serialize_all for MCAP recording. */
class ILiveTrackerImpl : public ITrackerImpl
{
public:
    ~ILiveTrackerImpl() override = default;

    virtual bool update_live(int64_t system_monotonic_time_ns) = 0;

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
     * Each call to update_live() clears the previous batch and accumulates a fresh
     * set of records (one for OpenXR-direct trackers; potentially many for
     * SchemaTracker-based tensor-device trackers). serialize_all emits every
     * record in that batch via the callback.
     *
     * @note For multi-channel trackers the recorder calls serialize_all once per
     *       channel index (channel_index = 0, 1, … N-1) after each update_live().
     *       All serialize_all calls for a given update_live() are guaranteed to
     *       complete before the next update_live() is issued. Implementations may
     *       therefore maintain a single shared pending batch and clear it at the
     *       start of the next update_live(); there is no need to track per-channel
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

/** Replay tracker impl: update_replay(replay_time_ns). Session is passed at creation and cached by the impl. */
class IReplayTrackerImpl : public ITrackerImpl
{
public:
    ~IReplayTrackerImpl() override = default;
    virtual bool update_replay(int64_t replay_time_ns) = 0;
};

/**
 * @brief Session interface for tracker update and get_tracker_impl.
 *
 * DeviceIOSession implements this interface. ReplaySession (later) will also
 * implement it. Replay impls use the session to get the next frame; live impls
 * convert monotonic time to XrTime locally when calling OpenXR.
 */
class ITrackerSession
{
public:
    virtual ~ITrackerSession() = default;

    virtual const ITrackerImpl& get_tracker_impl(const ITracker& tracker) const = 0;

    /**
     * @brief Advance the session and all trackers to the given time.
     *
     * @param system_monotonic_time_ns Current time in system monotonic nanoseconds.
     * @return true on success.
     */
    virtual bool update(int64_t system_monotonic_time_ns) = 0;
};

/**
 * @brief Single tracker type for both live and replay.
 *
 * Schema name and record channels live on the tracker (shared by live recording
 * and replay). The tracker creates either a live impl (for DeviceIOSession) or
 * a replay impl (for ReplaySession) via create_tracker / create_replay_tracker.
 */
class ITracker
{
public:
    virtual ~ITracker() = default;

    virtual std::string_view get_name() const = 0;

    /** OpenXR extensions required when used as a live tracker. Return {} for replay-only. */
    virtual std::vector<std::string> get_required_extensions() const = 0;

    /** Schema/channel metadata used by both recording and replay. */
    virtual std::string_view get_schema_name() const = 0;
    virtual std::string_view get_schema_text() const = 0;
    virtual std::vector<std::string> get_record_channels() const = 0;

protected:
    friend class DeviceIOSession;
    // Creates live impl for DeviceIOSession.
    virtual std::shared_ptr<ILiveTrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const = 0;

    // Creates replay impl for ReplaySession. Throw if replay not supported.
    virtual std::shared_ptr<IReplayTrackerImpl> create_replay_tracker(const ITrackerSession& session) const = 0;
};

} // namespace core
