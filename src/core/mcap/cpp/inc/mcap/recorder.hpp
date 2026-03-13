// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio/tracker.hpp>

#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace core
{

class DeviceIOSession;

/**
 * @brief MCAP Recorder for recording tracking data to MCAP files.
 *
 * Records from a live DeviceIOSession only (OpenXR tracker impls).
 * Replay sessions are not supported; recording is capture-time only.
 *
 * Usage:
 *   auto recorder = McapRecorder::create("output.mcap", {
 *       {hand_tracker, "hands"},
 *       {head_tracker, "head"},
 *   });
 *   // In your loop, after session.update():
 *   recorder->record(deviceio_session);
 *   // When done, let the recorder go out of scope or reset it
 */
class McapRecorder
{
public:
    /// Tracker configuration: pair of (tracker, base_channel_name).
    /// The base_channel_name must be non-empty. It is combined with each tracker's
    /// record channel names as "base_channel_name/channel_name" to form the final
    /// MCAP topic names. For example, registering a hand tracker with base name
    /// "hands" that returns channels {"left_hand", "right_hand"} produces MCAP
    /// topics "hands/left_hand" and "hands/right_hand".
    using TrackerChannelPair = std::pair<std::shared_ptr<ITracker>, std::string>;

    /**
     * @brief Create a recorder for the specified MCAP file and trackers.
     *
     * This is the main factory method. Opens the file, registers schemas/channels,
     * and returns a recorder ready for use.
     *
     * MCAP logTime and publishTime are the monotonic nanoseconds supplied by
     * each tracker's serialize_all callback (the update-tick time for that
     * frame, derived from the session's update(monotonic_ns)). The tracker's
     * DeviceDataTimestamp fields (available_time, sample times) are embedded
     * in the FlatBuffer payload and remain available for downstream latency
     * analysis.
     *
     * @param filename Path to the output MCAP file.
     * @param trackers List of (tracker, base_channel_name) pairs to record.
     *                 Both base_channel_name and the tracker's channel names must be non-empty.
     * @return A unique_ptr to the McapRecorder.
     * @throws std::runtime_error if the recorder cannot be created, or if any
     *         base_channel_name or tracker channel name is empty.
     */
    static std::unique_ptr<McapRecorder> create(const std::string& filename,
                                                const std::vector<TrackerChannelPair>& trackers);

    /**
     * @brief Destructor - closes the MCAP file.
     */
    ~McapRecorder();

    /**
     * @brief Record the current state of all registered trackers.
     *
     * Call after session.update() in your main loop. Only supports live
     * DeviceIOSession (replay sessions are not recordable).
     *
     * @param session The live DeviceIOSession to record from.
     */
    void record(const DeviceIOSession& session);

private:
    // Private constructor - use create() factory method
    McapRecorder(const std::string& filename, const std::vector<TrackerChannelPair>& trackers);

    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace core
