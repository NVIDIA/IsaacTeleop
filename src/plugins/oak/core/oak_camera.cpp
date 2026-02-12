// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "oak_camera.hpp"

#include <iostream>

namespace plugins
{
namespace oak
{

OakCamera::OakCamera(const OakConfig& config)
{
    std::cout << "OAK Camera: " << config.width << "x" << config.height << " @ " << config.fps << "fps, "
              << (config.bitrate / 1'000'000.0) << "Mbps" << std::endl;

    create_pipeline(config);

    // Find and connect to device
    std::cout << "Connecting to OAK device..." << std::endl;
    m_device = std::make_shared<dai::Device>(*m_pipeline);
    std::cout << "Device connected: " << m_device->getMxId() << std::endl;

    // Get output queue (blocking=false to not wait for frames)
    m_h264_queue = m_device->getOutputQueue("h264", 8, false);

    std::cout << "OAK camera pipeline started" << std::endl;
}

void OakCamera::create_pipeline(const OakConfig& config)
{
    m_pipeline = std::make_shared<dai::Pipeline>();

    // Create camera node
    auto camRgb = m_pipeline->create<dai::node::ColorCamera>();
    camRgb->setBoardSocket(dai::CameraBoardSocket::CAM_A);
    camRgb->setResolution(dai::ColorCameraProperties::SensorResolution::THE_1080_P);
    camRgb->setVideoSize(config.width, config.height);
    camRgb->setFps(static_cast<float>(config.fps));
    camRgb->setColorOrder(dai::ColorCameraProperties::ColorOrder::BGR);

    // Create video encoder for H.264
    auto videoEnc = m_pipeline->create<dai::node::VideoEncoder>();
    videoEnc->setDefaultProfilePreset(
        static_cast<float>(config.fps), dai::VideoEncoderProperties::Profile::H264_BASELINE);
    videoEnc->setBitrate(config.bitrate);
    videoEnc->setQuality(config.quality);
    videoEnc->setKeyframeFrequency(config.keyframe_frequency);
    videoEnc->setNumBFrames(0); // No B-frames for lower latency
    videoEnc->setRateControlMode(dai::VideoEncoderProperties::RateControlMode::CBR);

    // Create output for encoded H.264
    auto xoutH264 = m_pipeline->create<dai::node::XLinkOut>();
    xoutH264->setStreamName("h264");

    // Link: Camera -> Encoder -> Output
    camRgb->video.link(videoEnc->input);
    videoEnc->bitstream.link(xoutH264->input);
}

std::optional<OakFrame> OakCamera::get_frame()
{
    if (!m_h264_queue)
    {
        return std::nullopt;
    }

    // Try to get a frame (non-blocking)
    auto packet = m_h264_queue->tryGet<dai::ImgFrame>();
    if (!packet)
    {
        return std::nullopt;
    }

    const auto& data = packet->getData();
    if (data.empty())
    {
        return std::nullopt;
    }

    auto device_time_ns =
        std::chrono::duration_cast<std::chrono::nanoseconds>(packet->getTimestampDevice().time_since_epoch()).count();
    auto common_time_ns =
        std::chrono::duration_cast<std::chrono::nanoseconds>(packet->getTimestamp().time_since_epoch()).count();

    OakFrame frame;
    frame.h264_data = std::vector<uint8_t>(data.begin(), data.end());
    frame.metadata.timestamp = std::make_shared<core::Timestamp>(device_time_ns, common_time_ns);
    frame.metadata.sequence_number = static_cast<int32_t>(packet->getSequenceNum());

    static std::chrono::steady_clock::time_point last_log_time{};
    if (packet->getTimestamp() - last_log_time >= std::chrono::seconds(5))
    {
        std::cout << "H.264 frame #" << packet->getSequenceNum() << ": " << data.size() << " bytes" << std::endl;
        last_log_time = packet->getTimestamp();
    }

    return frame;
}

} // namespace oak
} // namespace plugins
