// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "rawdata_writer.hpp"
#include "sensing_types.hpp"

#include <map>
#include <memory>
#include <string>
#include <vector>

namespace plugins
{
namespace sensing
{

/**
 * @brief Interface to push per-sensor frame metadata.
 *
 * Concrete implementations push metadata over OpenXR (SchemaMetadataPusher)
 * or write it to an MCAP file (McapMetadataPusher).
 */
class IMetadataPusher
{
public:
    virtual ~IMetadataPusher() = default;
    virtual void on_frame_metadata(const core::FrameMetadataSensingT& metadata,
                                   int64_t sample_time_local_common_clock_ns,
                                   int64_t sample_time_raw_device_clock_ns) = 0;
};

/**
 * @brief Multi-sensor output sink for SENSING frames.
 *
 * Always writes raw H.264 data per sensor. Optionally delegates to an
 * IMetadataPusher for additional output (OXR schema push, MCAP recording).
 */
class FrameSink
{
public:
    explicit FrameSink(const std::vector<StreamConfig>& streams,
                       std::unique_ptr<IMetadataPusher> metadata_pusher = nullptr);

    FrameSink(const FrameSink&) = delete;
    FrameSink& operator=(const FrameSink&) = delete;

    void on_frame(const SensingFrame& frame);

private:
    std::map<uint32_t, std::unique_ptr<RawDataWriter>> m_writers;
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

} // namespace sensing
} // namespace plugins
