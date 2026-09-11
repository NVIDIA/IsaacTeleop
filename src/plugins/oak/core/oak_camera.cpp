// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "oak_camera.hpp"

#include "frame_sink.hpp"
#include "preview_stream.hpp"

#include <log_bridge/logger.hpp>

#include <algorithm>
#include <stdexcept>

namespace plugins
{
namespace oak
{

// =============================================================================
// Free helpers
// =============================================================================

static bool has_stream(const std::vector<StreamConfig>& streams, core::StreamType type)
{
    return std::any_of(streams.begin(), streams.end(), [type](const StreamConfig& s) { return s.camera == type; });
}

// =============================================================================
// OakCamera
// =============================================================================

OakCamera::OakCamera(const OakConfig& config, const std::vector<StreamConfig>& streams, std::unique_ptr<FrameSink> sink)
    : m_sink(std::move(sink))
{
    m_logger->info("OAK Camera: {} fps, {} Mbps", config.fps, config.bitrate / 1e6);

    auto device_info = find_device(config.device_id);

    m_device = std::make_shared<dai::Device>(device_info);
    m_logger->info("Device connected: {}", m_device->getDeviceInfo().getDeviceId());

    auto sensors = m_device->getCameraSensorNames();
    m_logger->info("Sensors found: {}", sensors.size());
    for (const auto& [socket, name] : sensors)
        m_logger->info("  Socket {}: {}", static_cast<int>(socket), name);

    m_pipeline = create_pipeline(m_device, config, streams);

    if (config.preview)
        m_preview = PreviewStream::create("ColorPreview", *m_pipeline);

    m_pipeline->start();

    m_logger->info("OAK camera pipeline started");
}

OakCamera::~OakCamera() = default;

dai::DeviceInfo OakCamera::find_device(const std::string& device_id)
{
    // static: no `this`, so this can't reuse the m_logger member -- resolve the
    // same memoized logger by name instead (see LiveHandTrackerImpl for precedent).
    auto logger = isaacteleop::Logger::get("isaacteleop.plugins.oak.OakCamera");

    auto devices = dai::DeviceBootloader::getAllAvailableDevices();
    if (devices.empty())
        throw std::runtime_error("No OAK devices found. Check USB connection and udev rules.");

    if (device_id.empty())
    {
        logger->info("Found {} OAK device(s), using: {}", devices.size(), devices[0].getMxId());
        return devices[0];
    }

    for (const auto& device : devices)
    {
        if (device.getDeviceId() == device_id)
        {
            logger->info("Found device with ID: {}", device_id);
            return device;
        }
    }

    throw std::runtime_error("Device with ID " + device_id + " not found.");
}

// =============================================================================
// Pipeline construction (DepthAI v3.x)
// =============================================================================

std::unique_ptr<dai::Pipeline> OakCamera::create_pipeline(std::shared_ptr<dai::Device> device,
                                                          const OakConfig& config,
                                                          const std::vector<StreamConfig>& streams)
{
    auto pipeline = std::make_unique<dai::Pipeline>(device);

    static constexpr std::pair<int, int> kRes1080p = { 1920, 1080 };
    static constexpr std::pair<int, int> kRes800p = { 1280, 800 };
    static constexpr std::pair<int, int> kRes400p = { 640, 400 };

    bool need_color = has_stream(streams, core::StreamType_Color);
    bool need_mono_left = has_stream(streams, core::StreamType_MonoLeft);
    bool need_mono_right = has_stream(streams, core::StreamType_MonoRight);

    auto create_encoder = [&]() -> std::shared_ptr<dai::node::VideoEncoder>
    {
        auto enc = pipeline->create<dai::node::VideoEncoder>();
        enc->setDefaultProfilePreset(static_cast<float>(config.fps), dai::VideoEncoderProperties::Profile::H264_BASELINE);
        enc->setBitrate(config.bitrate);
        enc->setQuality(config.quality);
        enc->setKeyframeFrequency(config.keyframe_frequency);
        enc->setNumBFrames(0);
        enc->setRateControlMode(dai::VideoEncoderProperties::RateControlMode::CBR);
        return enc;
    };

    auto add_stream = [&](dai::CameraBoardSocket socket, core::StreamType type, std::pair<int, int> resolution)
    {
        auto cam = pipeline->create<dai::node::Camera>();
        cam->build(socket);
        auto output = cam->requestOutput(resolution, dai::ImgFrame::Type::NV12);
        auto enc = create_encoder();
        output->link(enc->input);
        m_queues[type] = enc->bitstream.createOutputQueue();
    };

    // ---- Color camera ----
    if (need_color)
    {
        auto color_sensor = device->getCameraSensorNames()[dai::CameraBoardSocket::CAM_A];
        auto color_res = (color_sensor == "OV9782") ? kRes800p : kRes1080p;
        add_stream(dai::CameraBoardSocket::CAM_A, core::StreamType_Color, color_res);
    }

    // ---- Mono cameras ----
    if (need_mono_left)
        add_stream(dai::CameraBoardSocket::CAM_B, core::StreamType_MonoLeft, kRes400p);
    if (need_mono_right)
        add_stream(dai::CameraBoardSocket::CAM_C, core::StreamType_MonoRight, kRes400p);

    return pipeline;
}

// =============================================================================
// update() -- poll all queues and dispatch to FrameSink
// =============================================================================

void OakCamera::update()
{
    for (auto& [type, queue] : m_queues)
    {
        auto packet = queue->tryGet<dai::ImgFrame>();
        if (!packet)
            continue;

        const auto& raw = packet->getData();
        if (raw.empty())
            continue;

        auto device_time_ns =
            std::chrono::duration_cast<std::chrono::nanoseconds>(packet->getTimestampDevice().time_since_epoch()).count();
        auto common_time_ns =
            std::chrono::duration_cast<std::chrono::nanoseconds>(packet->getTimestamp().time_since_epoch()).count();

        OakFrame frame;
        frame.stream = type;
        frame.h264_data.assign(raw.begin(), raw.end());
        frame.metadata.stream = type;
        frame.metadata.sequence_number = static_cast<uint64_t>(packet->getSequenceNum());
        frame.sample_time_local_common_clock_ns = common_time_ns;
        frame.sample_time_raw_device_clock_ns = device_time_ns;

        m_sink->on_frame(frame);
        ++m_frame_counts[type];
    }

    if (m_preview)
        m_preview->update();
}

// =============================================================================
// print_stats()
// =============================================================================

void OakCamera::print_stats() const
{
    for (const auto& [type, count] : m_frame_counts)
    {
        m_logger->info("  {}: {} frames", core::EnumNameStreamType(type), count);
    }
}

} // namespace oak
} // namespace plugins
