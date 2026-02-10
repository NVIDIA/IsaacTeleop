// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <schema/camera_generated.h>

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

    /// Frame metadata (timestamp and sequence number)
    FrameMetadataT metadata;
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
};

} // namespace core
