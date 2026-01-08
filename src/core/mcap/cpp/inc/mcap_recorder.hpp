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
 *   auto recorder = McapRecorder::start_recording("output.mcap", {
 *       {hand_tracker, "hands"},
 *       {head_tracker, "head"},
 *   });
 *   // In your loop:
 *   recorder->record(session);
 *   // When done:
 *   recorder->stop_recording();  // or let destructor handle it
 */
class McapRecorder
{
public:
    /// Tracker configuration: pair of (tracker, channel_name)
    using TrackerChannelPair = std::pair<std::shared_ptr<ITracker>, std::string>;

    /**
     * @brief Start recording to an MCAP file with the specified trackers.
     *
     * This is the main factory method. Opens the file, registers schemas/channels,
     * and returns a recorder ready for use.
     *
     * @param filename Path to the output MCAP file.
     * @param trackers List of (tracker, channel_name) pairs to record.
     * @return A unique_ptr to the McapRecorder, or nullptr on failure.
     */
    static std::unique_ptr<McapRecorder> start_recording(const std::string& filename,
                                                         const std::vector<TrackerChannelPair>& trackers);

    /**
     * @brief Destructor - closes the file if open.
     */
    ~McapRecorder();

    // Non-copyable
    McapRecorder(const McapRecorder&) = delete;
    McapRecorder& operator=(const McapRecorder&) = delete;

    /**
     * @brief Stop recording and close the MCAP file.
     */
    void stop_recording();

    /**
     * @brief Check if recording is currently active.
     *
     * @return true if recording is in progress, false otherwise.
     */
    bool is_recording() const;

    /**
     * @brief Record the current state of all registered trackers.
     *
     * This should be called after session.update() in your main loop.
     *
     * @param session The DeviceIOSession to get tracker implementations from.
     * @return true if all trackers were recorded successfully, false otherwise.
     */
    bool record(const DeviceIOSession& session);

private:
    // Private constructor - use start_recording() factory method
    McapRecorder(const std::string& filename, const std::vector<TrackerChannelPair>& trackers);

    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace core
