// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <core/camera_config.hpp>

#include <chrono>
#include <cstdint>
#include <optional>
#include <vector>

namespace plugins
{
namespace camera
{

/**
 * @brief Encoded video frame with metadata
 */
struct Frame
{
    /// H.264 encoded frame data
    std::vector<uint8_t> data;

    /// Frame timestamp synchronized to host clock
    std::chrono::steady_clock::time_point timestamp;

    /// Frame timestamp from device's monotonic clock (not synced to host)
    std::chrono::steady_clock::time_point timestamp_device;

    /// Frame sequence number (monotonically increasing)
    int64_t sequence_num = 0;
};

/**
 * @brief Abstract interface for camera implementations
 *
 * Decouples the camera SDK from the plugin lifecycle.
 * Each camera implementation (OAK-D, RealSense, etc.) should implement this interface.
 */
class ICamera
{
public:
    virtual ~ICamera() = default;

    /**
     * @brief Start the camera capture pipeline
     */
    virtual void start() = 0;

    /**
     * @brief Stop the camera capture pipeline
     */
    virtual void stop() = 0;

    /**
     * @brief Check if the camera pipeline is running
     */
    virtual bool is_running() const = 0;

    /**
     * @brief Process pending camera tasks. Call this regularly.
     */
    virtual void process_tasks() = 0;

    /**
     * @brief Get the next available encoded frame with metadata
     * @return Frame with H.264 data and metadata, or empty optional if no frame available
     */
    virtual std::optional<Frame> get_frame() = 0;

    /**
     * @brief Get camera configuration
     */
    virtual const CameraConfig& config() const = 0;
};

} // namespace camera
} // namespace plugins
