// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "oak_camera.hpp"

#include <algorithm>
#include <iostream>
#include <thread>

namespace plugins
{
namespace oak
{

// Sensor name -> best resolution and max dimensions.
// Extend this table as new OAK-D hardware revisions ship.
static SensorInfo resolve_sensor(const std::string& sensor_name)
{
    if (sensor_name == "OV9782" || sensor_name == "OV9281")
    {
        return { sensor_name, dai::ColorCameraProperties::SensorResolution::THE_800_P, 1280, 800 };
    }
    if (sensor_name == "OV9282")
    {
        return { sensor_name, dai::ColorCameraProperties::SensorResolution::THE_800_P, 1280, 800 };
    }
    if (sensor_name == "IMX214")
    {
        return { sensor_name, dai::ColorCameraProperties::SensorResolution::THE_1080_P, 1920, 1080 };
    }
    // IMX378, IMX477, AR0234, and other 1080p+ sensors
    return { sensor_name, dai::ColorCameraProperties::SensorResolution::THE_1080_P, 1920, 1080 };
}

OakCamera::OakCamera(const OakConfig& config)
{
    std::cout << "OAK Camera: requested " << config.width << "x" << config.height << " @ " << config.fps << "fps, "
              << (config.bitrate / 1'000'000.0) << "Mbps" << std::endl;

    auto device_info = find_device_with_retry();
    auto sensor = probe_color_sensor(device_info);

    int video_width = std::min(config.width, sensor.max_width);
    int video_height = std::min(config.height, sensor.max_height);
    if (video_width != config.width || video_height != config.height)
    {
        std::cout << "Clamped video size to " << video_width << "x" << video_height << " (sensor " << sensor.name
                  << " max: " << sensor.max_width << "x" << sensor.max_height << ")" << std::endl;
    }

    create_pipeline(config, sensor);

    std::cout << "Opening device with pipeline..." << std::endl;
    m_device = std::make_shared<dai::Device>(*m_pipeline, device_info);
    std::cout << "Device connected: " << m_device->getMxId() << std::endl;

    m_h264_queue = m_device->getOutputQueue("h264", 8, false);

    std::cout << "OAK camera pipeline started (" << video_width << "x" << video_height << ")" << std::endl;
}

dai::DeviceInfo OakCamera::find_device_with_retry(int max_attempts, int retry_delay_ms)
{
    for (int attempt = 1; attempt <= max_attempts; ++attempt)
    {
        auto devices = dai::Device::getAllAvailableDevices();
        if (!devices.empty())
        {
            std::cout << "Found " << devices.size() << " OAK device(s), using: " << devices[0].getMxId() << std::endl;
            return devices[0];
        }
        if (attempt < max_attempts)
        {
            std::cerr << "No OAK devices found (attempt " << attempt << "/" << max_attempts << "), retrying in "
                      << retry_delay_ms << "ms..." << std::endl;
            std::this_thread::sleep_for(std::chrono::milliseconds(retry_delay_ms));
        }
    }
    throw std::runtime_error("No OAK devices found after " + std::to_string(max_attempts) +
                             " attempts. Check USB connection and udev rules.");
}

SensorInfo OakCamera::probe_color_sensor(const dai::DeviceInfo& device_info)
{
    std::cout << "Probing device sensors..." << std::endl;
    dai::Device device(device_info);

    auto sensors = device.getCameraSensorNames();
    std::cout << "  Sensors found: " << sensors.size() << std::endl;
    for (const auto& [socket, name] : sensors)
    {
        std::cout << "    Socket " << static_cast<int>(socket) << ": " << name << std::endl;
    }

    auto it = sensors.find(dai::CameraBoardSocket::CAM_A);
    if (it == sensors.end())
    {
        throw std::runtime_error("No color sensor found on CAM_A (socket 0)");
    }

    auto info = resolve_sensor(it->second);
    std::cout << "  Color sensor: " << info.name << " (max " << info.max_width << "x" << info.max_height << ")"
              << std::endl;

    // Small delay to let the USB fully release before reopening with pipeline
    std::this_thread::sleep_for(std::chrono::milliseconds(500));
    return info;
}

void OakCamera::create_pipeline(const OakConfig& config, const SensorInfo& sensor)
{
    m_pipeline = std::make_shared<dai::Pipeline>();

    int video_width = std::min(config.width, sensor.max_width);
    int video_height = std::min(config.height, sensor.max_height);

    auto camRgb = m_pipeline->create<dai::node::ColorCamera>();
    camRgb->setBoardSocket(dai::CameraBoardSocket::CAM_A);
    camRgb->setResolution(sensor.resolution);
    camRgb->setVideoSize(video_width, video_height);
    camRgb->setFps(static_cast<float>(config.fps));
    camRgb->setColorOrder(dai::ColorCameraProperties::ColorOrder::BGR);

    auto videoEnc = m_pipeline->create<dai::node::VideoEncoder>();
    videoEnc->setDefaultProfilePreset(
        static_cast<float>(config.fps), dai::VideoEncoderProperties::Profile::H264_BASELINE);
    videoEnc->setBitrate(config.bitrate);
    videoEnc->setQuality(config.quality);
    videoEnc->setKeyframeFrequency(config.keyframe_frequency);
    videoEnc->setNumBFrames(0);
    videoEnc->setRateControlMode(dai::VideoEncoderProperties::RateControlMode::CBR);

    auto xoutH264 = m_pipeline->create<dai::node::XLinkOut>();
    xoutH264->setStreamName("h264");

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
