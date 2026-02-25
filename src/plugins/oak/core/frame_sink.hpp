// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "oak_camera.hpp"
#include "rawdata_writer.hpp"

#include <map>
#include <memory>
#include <string>

namespace plugins
{
namespace oak
{

/**
 * @brief Interface to push oak per-stream frame metadata.
 *
 * Concrete implementations push metadata over OpenXR (SchemaMetadataPusher)
 * or write it to an MCAP file (McapMetadataPusher).
 */
class IMetadataPusher
{
public:
    virtual ~IMetadataPusher() = default;
    virtual void on_frame_metadata(const core::FrameMetadataOakT& metadata) = 0;
};

/**
 * @brief Multi-stream output sink for OAK frames.
 *
 * Always writes raw H.264 data per stream. Optionally delegates to an
 * IMetadataPusher for additional output (OXR schema push, MCAP recording, etc.).
 */
class FrameSink
{
public:
    FrameSink(const std::vector<StreamConfig>& streams, std::unique_ptr<IMetadataPusher> metadata_pusher = nullptr);

    FrameSink(const FrameSink&) = delete;
    FrameSink& operator=(const FrameSink&) = delete;

    void on_frame(const OakFrame& frame);

private:
    std::map<core::StreamType, std::unique_ptr<RawDataWriter>> m_writers;
    std::unique_ptr<IMetadataPusher> m_metadata_pusher;
};

/**
 * @brief Factory that creates a FrameSink with the appropriate metadata pusher.
 *
 * - If collection_prefix is non-empty, attaches a SchemaMetadataPusher.
 * - If mcap_filename is non-empty, attaches a McapMetadataPusher.
 * - Otherwise creates a plain FrameSink (raw-data only).
 */
std::unique_ptr<FrameSink> create_frame_sink(const std::vector<StreamConfig>& streams,
                                             const std::string& collection_prefix,
                                             const std::string& mcap_filename);

} // namespace oak
} // namespace plugins
