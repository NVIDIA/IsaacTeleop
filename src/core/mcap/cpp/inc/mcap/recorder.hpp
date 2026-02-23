// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio/tracker.hpp>

#include <memory>
#include <string>
#include <vector>

namespace core
{

// Forward declaration
class DeviceIOSession;

/**
 * @brief MCAP Recorder for recording tracking data to MCAP files.
 *
 * Records XXRecord FlatBuffer types (data + DeviceDataTimestamp) to MCAP.
 * Each tracker defines its own record channels via get_record_channels().
 *
 * Usage:
 *   auto recorder = McapRecorder::create("output.mcap", {hand_tracker, head_tracker});
 *   // In your loop:
 *   recorder->record(session);
 *   // When done, let the recorder go out of scope or reset it
 */
class McapRecorder
{
public:
    /**
     * @brief Create a recorder for the specified MCAP file and trackers.
     *
     * Each tracker's get_record_channels() defines which MCAP channels are
     * created (e.g., HandTracker creates "left_hand" and "right_hand").
     *
     * @param filename Path to the output MCAP file.
     * @param trackers List of trackers to record.
     * @return A unique_ptr to the McapRecorder.
     * @throws std::runtime_error if the recorder cannot be created.
     */
    static std::unique_ptr<McapRecorder> create(const std::string& filename,
                                                const std::vector<std::shared_ptr<ITracker>>& trackers);

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
    McapRecorder(const std::string& filename, const std::vector<std::shared_ptr<ITracker>>& trackers);

    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace core
