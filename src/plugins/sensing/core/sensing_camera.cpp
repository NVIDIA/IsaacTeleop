// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "sensing_camera.hpp"

#include "frame_sink.hpp"

#include <iostream>
#include <stdexcept>

namespace plugins
{
namespace sensing
{

namespace
{

camera_viz::argus::ArgusConfig make_argus_config(const SensingConfig& config, uint32_t sensor_id)
{
    camera_viz::argus::ArgusConfig argus{};
    argus.name = "sensor" + std::to_string(sensor_id);
    argus.sensor_ids = { sensor_id };
    argus.sensor_mode = config.sensor_mode;
    argus.width = config.width;
    argus.height = config.height;
    argus.fps = config.fps;
    argus.gpu_id = config.gpu_id;
    argus.full_range = config.full_range;
    argus.swap_uv = config.swap_uv;
    // Finite acquire timeouts return CUDA_ERROR_UNKNOWN on this JetPack/driver
    // stack before the first frame arrives, so block indefinitely instead.
    argus.acquire_timeout_ms = 0xffffffffu;
    argus.repeat_capture = true;
    return argus;
}

EncoderConfig make_encoder_config(const SensingConfig& config)
{
    EncoderConfig encoder{};
    encoder.width = config.width;
    encoder.height = config.height;
    encoder.bitrate_bps = config.bitrate_bps;
    encoder.fps = static_cast<uint32_t>(config.fps);
    encoder.gop = config.gop;
    encoder.full_range = config.full_range;
    return encoder;
}

} // namespace

SensingCamera::SensingCamera(const SensingConfig& config,
                             const std::vector<StreamConfig>& streams,
                             std::unique_ptr<FrameSink> sink)
    : m_config(config), m_sink(std::move(sink))
{
    if (streams.empty())
        throw std::runtime_error("SensingCamera: no streams requested");

    m_streams.reserve(streams.size());
    for (const auto& stream_config : streams)
    {
        Stream stream;
        stream.sensor_id = stream_config.sensor_id;
        stream.camera =
            std::make_unique<camera_viz::argus::ArgusCamera>(make_argus_config(config, stream_config.sensor_id));

        if (!stream_config.output_path.empty())
            stream.encoder = std::make_unique<JetsonEncoder>(make_encoder_config(config));

        if (!stream_config.ipc_socket_path.empty())
        {
            CudaIpcConfig ipc{};
            ipc.socket_path = stream_config.ipc_socket_path;
            ipc.width = config.width;
            ipc.height = config.height;
            ipc.sensor_id = stream_config.sensor_id;
            ipc.gpu_id = config.gpu_id;
            stream.publisher = std::make_unique<CudaIpcPublisher>(ipc);
        }

        stream.camera->start();
        m_streams.push_back(std::move(stream));

        std::cout << "Sensor " << stream_config.sensor_id << ": " << config.width << "x" << config.height << " @ "
                  << config.fps << " fps" << std::endl;
    }
}

SensingCamera::~SensingCamera()
{
    for (auto& stream : m_streams)
    {
        if (stream.camera)
            stream.camera->stop();
    }
}

void SensingCamera::update()
{
    for (auto& stream : m_streams)
    {
        // Accept consumers and reap released slots even on a frameless tick,
        // so a viewer can attach before the camera produces anything.
        if (stream.publisher)
            stream.publisher->poll();

        auto view = stream.camera->latest();
        if (view.has_value() && view->sequence != stream.last_sequence)
        {
            stream.last_sequence = view->sequence;
            stream.pending_timestamp_ns = static_cast<int64_t>(view->timestamp_ns);

            // Publish before encoding: the IPC consumer is the latency-
            // sensitive path, and the encoder submit below is pipelined anyway.
            if (stream.publisher)
                stream.publisher->publish(view->left_ptr, view->left_pitch, view->timestamp_ns);

            if (stream.encoder)
                stream.encoder->submit(view->left_ptr, view->left_pitch);
        }

        // Submission and output are decoupled: the V4L2 encoder needs several
        // input frames before it emits the first unit, so drain independently.
        // The stamp is the most recent submission, not this unit's own frame.
        if (stream.encoder)
        {
            for (auto h264 = stream.encoder->poll(); !h264.empty(); h264 = stream.encoder->poll())
                dispatch(stream, std::move(h264), stream.pending_timestamp_ns);
        }
    }
}

void SensingCamera::flush()
{
    for (auto& stream : m_streams)
    {
        if (!stream.encoder)
            continue;
        auto h264 = stream.encoder->end_of_stream();
        if (!h264.empty())
            dispatch(stream, std::move(h264), 0);
    }
}

void SensingCamera::dispatch(Stream& stream, std::vector<uint8_t> h264, int64_t timestamp_ns)
{
    SensingFrame frame;
    frame.sensor_id = stream.sensor_id;
    frame.h264_data = std::move(h264);
    frame.metadata.sensor_id = stream.sensor_id;
    frame.metadata.sequence_number = stream.frame_count;

    // ArgusCamera stamps frames with CLOCK_MONOTONIC at YUV->RGBA conversion,
    // not with Argus getSensorTimestamp(), so there is no separate device
    // clock to report: both fields carry the same host-side capture stamp and
    // include acquire + convert latency. Do not treat the difference between
    // them as sensor-to-host latency.
    frame.sample_time_local_common_clock_ns = timestamp_ns;
    frame.sample_time_raw_device_clock_ns = timestamp_ns;

    ++stream.frame_count;
    m_sink->on_frame(frame);
}

void SensingCamera::print_stats() const
{
    for (const auto& stream : m_streams)
    {
        std::cout << "  sensor " << stream.sensor_id << ": " << stream.frame_count << " frames";
        if (stream.publisher)
        {
            std::cout << " | ipc " << stream.publisher->published_count() << " published, "
                      << stream.publisher->dropped_count() << " dropped"
                      << (stream.publisher->has_consumer() ? "" : ", no consumer");
        }
        std::cout << std::endl;
    }
}

} // namespace sensing
} // namespace plugins
