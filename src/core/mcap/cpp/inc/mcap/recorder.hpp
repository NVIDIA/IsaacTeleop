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

// Forward declaration
class DeviceIOSession;

/**
 * @brief MCAP Recorder for recording tracking data to MCAP files.
 *
 * This class provides a simple interface to record tracker data
 * to MCAP format files, which can be visualized with tools like Foxglove.
 *
 * Usage:
 *   auto recorder = McapRecorder::create("output.mcap", {
 *       {hand_tracker, "hands"},
 *       {head_tracker, "head"},
 *   });
 *   // In your loop:
 *   recorder->record(session);
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
     * MCAP logTime and publishTime are set to os_monotonic_now_ns() at the
     * moment each record is written, not from the tracker's own timestamps.
     * The tracker's DeviceDataTimestamp fields (available_time, sample times)
     * are embedded in the FlatBuffer payload and remain available for downstream
     * latency analysis.
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
     * This should be called after session.update() in your main loop.
     *
     * @param session The DeviceIOSession to get tracker implementations from.
     */
    void record(const DeviceIOSession& session);

private:
    // Private constructor - use create() factory method
    McapRecorder(const std::string& filename, const std::vector<TrackerChannelPair>& trackers);

    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace core
