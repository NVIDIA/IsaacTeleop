// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio/tracker.hpp>

#include <memory>
#include <string>

namespace core
{

/**
 * @brief MCAP Recorder for recording tracking data to MCAP files.
 *
 * This class provides a simple interface to record HeadPose data
 * to MCAP format files, which can be visualized with tools like Foxglove.
 */
class McapRecorder
{
public:
    /**
     * @brief Construct a new McapRecorder.
     */
    McapRecorder();

    /**
     * @brief Destructor - closes the file if open.
     */
    ~McapRecorder();

    // Non-copyable
    McapRecorder(const McapRecorder&) = delete;
    McapRecorder& operator=(const McapRecorder&) = delete;

    /**
     * @brief Open an MCAP file for writing.
     *
     * @param filename Path to the output MCAP file.
     * @return true if file was opened successfully, false otherwise.
     */
    bool open(const std::string& filename);

    /**
     * @brief Close the MCAP file.
     */
    void close();

    /**
     * @brief Check if a file is currently open for recording.
     *
     * @return true if file is open, false otherwise.
     */
    bool is_open() const;

    /**
     * @brief Add a tracker implementation to the recorder.
     *
     * @param tracker_impl The tracker implementation to register.
     */
    void add_tracker(const std::shared_ptr<ITrackerImpl> tracker_impl);

    /**
     * @brief Record the current state of a tracker implementation.
     *
     * @param tracker_impl The tracker implementation to record.
     * @return true if recording succeeded, false otherwise.
     */
    bool record(const std::shared_ptr<ITrackerImpl> tracker_impl);

    /**
     * @brief Get the path to the currently open file.
     *
     * @return The filename, or empty string if no file is open.
     */
    std::string get_filename() const;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace core
