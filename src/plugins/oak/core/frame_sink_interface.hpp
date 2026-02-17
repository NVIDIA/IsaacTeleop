// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <schema/oak_generated.h>

#include <cstdint>
#include <vector>

namespace plugins
{
namespace oak
{

/**
 * @brief OAK encoded video frame with metadata.
 */
struct OakFrame
{
    /// H.264 encoded frame data
    std::vector<uint8_t> h264_data;

    /// Frame metadata (timestamp + sequence number) from oak.fbs
    core::FrameMetadataT metadata;
};

/**
 * @brief Interface for consuming OAK frames.
 */
class IFrameSink
{
public:
    virtual ~IFrameSink() = default;

    /**
     * @brief Process a single frame.
     */
    virtual void on_frame(const OakFrame& frame) = 0;
};

} // namespace oak
} // namespace plugins
