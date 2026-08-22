// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "argus_camera.hpp"
#include "cuda_ipc_publisher.hpp"
#include "jetson_encoder.hpp"
#include "sensing_types.hpp"

#include <cstdint>
#include <memory>
#include <vector>

namespace plugins
{
namespace sensing
{

class FrameSink;

/**
 * @brief Multi-sensor SENSING camera manager.
 *
 * One independent Argus session per sensor: the GMSL drivers on this carrier
 * reject a multi-sensor Argus session, so sensors are never grouped even when
 * they form a stereo pair. Each update() polls every sensor's latest-frame
 * mailbox and fans the new frame out to whichever destinations that stream
 * configured — an H.264 encoder, a CUDA IPC socket, or both. A stream may have
 * an encoder or not; the CUDA path deliberately needs neither.
 */
class SensingCamera
{
public:
    SensingCamera(const SensingConfig& config, const std::vector<StreamConfig>& streams, std::unique_ptr<FrameSink> sink);
    ~SensingCamera();

    SensingCamera(const SensingCamera&) = delete;
    SensingCamera& operator=(const SensingCamera&) = delete;
    SensingCamera(SensingCamera&&) = delete;
    SensingCamera& operator=(SensingCamera&&) = delete;

    /** @brief Poll every sensor and dispatch newly encoded frames. */
    void update();

    /** @brief Flush each encoder's queued packets into the sink. */
    void flush();

    /** @brief Print per-sensor frame counts to stdout. */
    void print_stats() const;

private:
    struct Stream
    {
        uint32_t sensor_id = 0;
        std::unique_ptr<camera_viz::argus::ArgusCamera> camera;
        /// Null when the stream requested no H.264 output.
        std::unique_ptr<JetsonEncoder> encoder;
        /// Null when the stream requested no CUDA IPC socket.
        std::unique_ptr<CudaIpcPublisher> publisher;
        /// Argus publish counter of the frame already encoded; skips re-reads.
        uint64_t last_sequence = 0;
        /// Capture stamp of the most recent submission. The encoder reorders
        /// nothing (no B-frames) but is pipelined, so an emitted unit is
        /// attributed to the latest frame submitted, not necessarily its own.
        int64_t pending_timestamp_ns = 0;
        uint64_t frame_count = 0;
    };

    void dispatch(Stream& stream, std::vector<uint8_t> h264, int64_t timestamp_ns);

    SensingConfig m_config;
    std::vector<Stream> m_streams;
    std::unique_ptr<FrameSink> m_sink;
};

} // namespace sensing
} // namespace plugins
