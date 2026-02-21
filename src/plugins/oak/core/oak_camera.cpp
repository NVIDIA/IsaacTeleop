// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "oak_camera.hpp"

#include "frame_sink.hpp"

#include <algorithm>
#include <iostream>
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

OakCamera::OakCamera(const OakConfig& config, const std::vector<StreamConfig>& streams, FrameSink& sink) : m_sink(sink)
{
    std::cout << "OAK Camera: " << config.fps << " fps, " << (config.bitrate / 1'000'000.0) << " Mbps" << std::endl;
    for (const auto& s : streams)
    {
        std::cout << "Add Stream: " << core::EnumNameStreamType(s.camera) << std::endl;
        m_sink.add_stream(s.camera, s.output_path);
    }

    auto device_info = find_device(config.device_id);

    m_device = std::make_shared<dai::Device>(device_info);
    std::cout << "Device connected: " << m_device->getMxId() << std::endl;

    auto sensors = m_device->getCameraSensorNames();
    create_pipeline(config, streams, sensors);

    m_device->startPipeline(*m_pipeline);

    for (const auto& s : streams)
    {
        m_queues[s.camera] = m_device->getOutputQueue(core::EnumNameStreamType(s.camera), 8, false);
    }

    std::cout << "OAK camera pipeline started" << std::endl;
}

dai::DeviceInfo OakCamera::find_device(const std::string& device_id)
{
    auto devices = dai::Device::getAllAvailableDevices();

    if (devices.empty())
        throw std::runtime_error("No OAK devices found. Check USB connection and udev rules.");

    if (device_id.empty())
    {
        std::cout << "Found " << devices.size() << " OAK device(s), using: " << devices[0].getMxId() << std::endl;
        return devices[0];
    }

    for (const auto& device : devices)
    {
        if (device.getMxId() == device_id)
        {
            std::cout << "Found device with ID: " << device.getMxId() << std::endl;
            return device;
        }
    }

    throw std::runtime_error("Device with ID " + device_id + " not found.");
}

// =============================================================================
// Pipeline construction
// =============================================================================

void OakCamera::create_pipeline(const OakConfig& config,
                                const std::vector<StreamConfig>& streams,
                                const std::unordered_map<dai::CameraBoardSocket, std::string>& sensors)
{
    m_pipeline = std::make_shared<dai::Pipeline>();

    bool need_color = has_stream(streams, core::StreamType_Color);
    bool need_mono_left = has_stream(streams, core::StreamType_MonoLeft);
    bool need_mono_right = has_stream(streams, core::StreamType_MonoRight);

    auto create_h264_output = [&](dai::Node::Output& source, const char* stream_name)
    {
        auto enc = m_pipeline->create<dai::node::VideoEncoder>();
        enc->setDefaultProfilePreset(config.fps, dai::VideoEncoderProperties::Profile::H264_BASELINE);
        enc->setBitrate(config.bitrate);
        enc->setQuality(config.quality);
        enc->setKeyframeFrequency(config.keyframe_frequency);
        enc->setNumBFrames(0);
        enc->setRateControlMode(dai::VideoEncoderProperties::RateControlMode::CBR);

        auto xout = m_pipeline->create<dai::node::XLinkOut>();
        xout->setStreamName(stream_name);

        source.link(enc->input);
        enc->bitstream.link(xout->input);
    };

    // ---- Color camera ----
    if (need_color)
    {
        auto it = sensors.find(dai::CameraBoardSocket::CAM_A);
        if (it == sensors.end())
            throw std::runtime_error("Color stream requested but no sensor found on CAM_A");

        auto resolution = it->second == "OV9782" ? dai::ColorCameraProperties::SensorResolution::THE_800_P :
                                                   dai::ColorCameraProperties::SensorResolution::THE_1080_P;

        auto camRgb = m_pipeline->create<dai::node::ColorCamera>();
        camRgb->setBoardSocket(dai::CameraBoardSocket::CAM_A);
        camRgb->setResolution(resolution);
        camRgb->setFps(config.fps);
        camRgb->setColorOrder(dai::ColorCameraProperties::ColorOrder::BGR);

        create_h264_output(camRgb->video, core::EnumNameStreamType(core::StreamType_Color));
    }

    // ---- Mono cameras ----
    if (need_mono_left)
    {
        auto monoLeft = m_pipeline->create<dai::node::MonoCamera>();
        monoLeft->setBoardSocket(dai::CameraBoardSocket::CAM_B);
        monoLeft->setResolution(dai::MonoCameraProperties::SensorResolution::THE_400_P);
        monoLeft->setFps(config.fps);

        create_h264_output(monoLeft->out, core::EnumNameStreamType(core::StreamType_MonoLeft));
    }

    if (need_mono_right)
    {
        auto monoRight = m_pipeline->create<dai::node::MonoCamera>();
        monoRight->setBoardSocket(dai::CameraBoardSocket::CAM_C);
        monoRight->setResolution(dai::MonoCameraProperties::SensorResolution::THE_400_P);
        monoRight->setFps(config.fps);

        create_h264_output(monoRight->out, core::EnumNameStreamType(core::StreamType_MonoRight));
    }
}

// =============================================================================
// update() -- poll all queues and dispatch to FrameSink
// =============================================================================

size_t OakCamera::update()
{
    size_t count = 0;

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
        frame.data.assign(raw.begin(), raw.end());
        frame.metadata.stream = type;
        frame.metadata.timestamp = std::make_unique<core::Timestamp>(device_time_ns, common_time_ns);
        frame.metadata.sequence_number = packet->getSequenceNum();

        m_sink.on_frame(frame);
        ++count;
    }

    return count;
}

} // namespace oak
} // namespace plugins
