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
    /// Tracker configuration: pair of (tracker, channel_name)
    using TrackerChannelPair = std::pair<std::shared_ptr<ITracker>, std::string>;

    /**
     * @brief Create a recorder for the specified MCAP file and trackers.
     *
     * This is the main factory method. Opens the file, registers schemas/channels,
     * and returns a recorder ready for use.
     *
     * @param filename Path to the output MCAP file.
     * @param trackers List of (tracker, channel_name) pairs to record.
     * @return A unique_ptr to the McapRecorder.
     * @throws std::runtime_error if the recorder cannot be created.
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
