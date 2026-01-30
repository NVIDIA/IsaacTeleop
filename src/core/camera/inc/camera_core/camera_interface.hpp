// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "camera_config.hpp"

#include <chrono>
#include <cstdint>
#include <optional>
#include <vector>

namespace core
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
 * Camera starts in constructor and stops in destructor (RAII).
 */
class ICamera
{
public:
    virtual ~ICamera() = default;

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

} // namespace core
