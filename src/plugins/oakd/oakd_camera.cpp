// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "oakd_camera.hpp"

#include <iostream>

namespace core
{

OakDCamera::OakDCamera(const CameraConfig& config) : m_config(config)
{
    std::cout << "OAK-D Camera: " << m_config.width << "x" << m_config.height << " @ " << m_config.fps << "fps, "
              << (m_config.bitrate / 1'000'000.0) << "Mbps" << std::endl;

    create_pipeline();

    // Find and connect to device
    std::cout << "Connecting to OAK-D device..." << std::endl;
    m_device = std::make_shared<dai::Device>(*m_pipeline);
    std::cout << "Device connected: " << m_device->getMxId() << std::endl;

    // Get output queue (blocking=false to not wait for frames)
    m_h264_queue = m_device->getOutputQueue("h264", 8, false);

    std::cout << "OAK-D camera pipeline started" << std::endl;
}

void OakDCamera::create_pipeline()
{
    m_pipeline = std::make_shared<dai::Pipeline>();

    // Create camera node
    auto camRgb = m_pipeline->create<dai::node::ColorCamera>();
    camRgb->setBoardSocket(dai::CameraBoardSocket::CAM_A);
    camRgb->setResolution(dai::ColorCameraProperties::SensorResolution::THE_1080_P);
    camRgb->setVideoSize(m_config.width, m_config.height);
    camRgb->setFps(static_cast<float>(m_config.fps));
    camRgb->setColorOrder(dai::ColorCameraProperties::ColorOrder::BGR);

    // Create video encoder for H.264
    auto videoEnc = m_pipeline->create<dai::node::VideoEncoder>();
    videoEnc->setDefaultProfilePreset(
        static_cast<float>(m_config.fps), dai::VideoEncoderProperties::Profile::H264_BASELINE);
    videoEnc->setBitrate(m_config.bitrate);
    videoEnc->setQuality(m_config.quality);
    videoEnc->setKeyframeFrequency(m_config.keyframe_frequency);
    videoEnc->setNumBFrames(0); // No B-frames for lower latency
    videoEnc->setRateControlMode(dai::VideoEncoderProperties::RateControlMode::CBR);

    // Create output for encoded H.264
    auto xoutH264 = m_pipeline->create<dai::node::XLinkOut>();
    xoutH264->setStreamName("h264");

    // Link: Camera -> Encoder -> Output
    camRgb->video.link(videoEnc->input);
    videoEnc->bitstream.link(xoutH264->input);
}

std::optional<Frame> OakDCamera::get_frame()
{
    if (!m_h264_queue)
    {
        return std::nullopt;
    }

    // Try to get a frame (non-blocking)
    // Video encoder outputs ImgFrame with encoded data in getData()
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

    // Build frame with metadata
    Frame frame;
    frame.data = std::vector<uint8_t>(data.begin(), data.end());
    frame.timestamp = packet->getTimestamp();
    frame.timestamp_device = packet->getTimestampDevice();
    frame.sequence_num = packet->getSequenceNum();

    static std::chrono::steady_clock::time_point last_log_time{};
    if (frame.timestamp - last_log_time >= std::chrono::seconds(5))
    {
        std::cout << "H.264 frame #" << frame.sequence_num << ": " << data.size() << " bytes" << std::endl;
        last_log_time = frame.timestamp;
    }

    return frame;
}

} // namespace core
