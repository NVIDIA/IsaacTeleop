// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <orbbec_camera/orbbec_camera.hpp>

#include <filesystem>
#include <fstream>
#include <iterator>
#include <memory>
#include <vector>

namespace
{

class RecordingMetadataSink final : public plugins::orbbec::IMetadataSink
{
public:
    void on_frame_metadata(const plugins::orbbec::CapturedFrame& frame) override
    {
        frames.push_back(frame);
    }
    std::vector<plugins::orbbec::CapturedFrame> frames;
};

} // namespace

TEST_CASE("Orbbec FrameSink writes raw MJPEG and forwards metadata", "[orbbec][writer][metadata]")
{
    const auto output = std::filesystem::temp_directory_path() / "isaacteleop_orbbec_camera_test.mjpg";
    auto metadata_sink = std::make_unique<RecordingMetadataSink>();
    auto* metadata_sink_ptr = metadata_sink.get();
    {
        plugins::orbbec::FrameSink sink(
            { { core::OrbbecCameraStream_ColorLeft, output.string() } }, std::move(metadata_sink));
        plugins::orbbec::CapturedFrame frame;
        frame.metadata.stream = core::OrbbecCameraStream_ColorLeft;
        frame.metadata.sequence_number = 42;
        frame.metadata.width = 1280;
        frame.metadata.height = 720;
        frame.metadata.fps = 30;
        frame.metadata.pixel_format = core::OrbbecPixelFormat_Mjpg;
        frame.encoded_data = { 0xff, 0xd8, 0x01, 0x02, 0xff, 0xd9 };
        frame.sample_time_local_common_clock_ns = 100;
        frame.sample_time_raw_device_clock_ns = 200;
        sink.on_frame(frame);
        REQUIRE(metadata_sink_ptr->frames.size() == 1);
        REQUIRE(metadata_sink_ptr->frames.front().metadata.sequence_number == 42);
    }

    std::ifstream input(output, std::ios::binary);
    std::vector<char> bytes((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    REQUIRE(bytes.size() == 6);
    REQUIRE(static_cast<uint8_t>(bytes.front()) == 0xff);
    REQUIRE(static_cast<uint8_t>(bytes.back()) == 0xd9);
    std::filesystem::remove(output);
}

TEST_CASE("Orbbec FrameSink preserves H264 and H265 elementary stream bytes", "[orbbec][writer]")
{
    for (const auto format : { core::OrbbecPixelFormat_H264, core::OrbbecPixelFormat_H265 })
    {
        const auto suffix = format == core::OrbbecPixelFormat_H264 ? ".h264" : ".h265";
        const auto output = std::filesystem::temp_directory_path() / (std::string("isaacteleop_orbbec") + suffix);
        size_t expected_size = 0;
        {
            plugins::orbbec::StreamConfig stream{ core::OrbbecCameraStream_ColorLeft, output.string() };
            stream.pixel_format = format;
            plugins::orbbec::FrameSink sink({ stream });
            plugins::orbbec::CapturedFrame frame;
            frame.metadata.stream = stream.camera;
            frame.metadata.pixel_format = format;
            if (format == core::OrbbecPixelFormat_H264)
                frame.encoded_data = { 0, 0, 0, 1, 0x67, 0x01, 0, 0, 0, 1, 0x68, 0x01, 0, 0, 0, 1, 0x65, 0x01 };
            else
                frame.encoded_data = { 0, 0, 0, 1, 0x40, 0x01, 0, 0, 0, 1, 0x42, 0x01,
                                       0, 0, 0, 1, 0x44, 0x01, 0, 0, 0, 1, 0x26, 0x01 };
            expected_size = frame.encoded_data.size();
            sink.on_frame(frame);
        }
        std::ifstream input(output, std::ios::binary);
        std::vector<char> bytes((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
        REQUIRE(bytes.size() == expected_size);
        CHECK(bytes[3] == 1);
        std::filesystem::remove(output);
    }
}

TEST_CASE("Orbbec FrameSink resumes compressed recording at an IDR after a sequence gap", "[orbbec][writer]")
{
    const auto output = std::filesystem::temp_directory_path() / "isaacteleop_orbbec_gap.h264";
    plugins::orbbec::StreamConfig stream{ core::OrbbecCameraStream_ColorLeft, output.string() };
    stream.pixel_format = core::OrbbecPixelFormat_H264;
    const std::vector<uint8_t> idr = { 0, 0, 0, 1, 0x67, 0x01, 0, 0, 0, 1, 0x68, 0x01, 0, 0, 0, 1, 0x65, 0x01 };
    const std::vector<uint8_t> p_frame = { 0, 0, 0, 1, 0x41, 0x01 };
    {
        plugins::orbbec::FrameSink sink({ stream });
        plugins::orbbec::CapturedFrame frame;
        frame.metadata.stream = stream.camera;
        frame.metadata.pixel_format = stream.pixel_format;
        frame.metadata.sequence_number = 1;
        frame.encoded_data = idr;
        sink.on_frame(frame);

        frame.metadata.sequence_number = 3;
        frame.encoded_data = p_frame;
        sink.on_frame(frame);

        frame.metadata.sequence_number = 4;
        sink.on_frame(frame);

        frame.metadata.sequence_number = 5;
        frame.encoded_data = idr;
        sink.on_frame(frame);
    }
    std::ifstream input(output, std::ios::binary);
    std::vector<char> bytes((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    REQUIRE(bytes.size() == idr.size() * 2);
    std::filesystem::remove(output);
}

TEST_CASE("Orbbec FrameSink excludes H264 timestamp SEI", "[orbbec][writer]")
{
    const auto output = std::filesystem::temp_directory_path() / "isaacteleop_orbbec_sei.h264";
    plugins::orbbec::StreamConfig stream{ core::OrbbecCameraStream_ColorLeft, output.string() };
    stream.pixel_format = core::OrbbecPixelFormat_H264;
    size_t image_size = 0;
    {
        plugins::orbbec::FrameSink sink({ stream });
        plugins::orbbec::CapturedFrame frame;
        frame.metadata.stream = stream.camera;
        frame.metadata.pixel_format = stream.pixel_format;
        frame.encoded_data = { 0, 0, 0, 1, 0x67, 0x01, 0,   0,   0,   1,   0x68, 0x01, 0,   0,   0,   1,   0x65, 0x01,
                               0, 0, 0, 1, 0x06, 0x05, 'O', 'R', 'B', 'B', 'E',  'C',  ',', 'E', 'G', 'O', '_' };
        sink.on_frame(frame);
        image_size = frame.encoded_data.size() - 17;
        frame.encoded_data = { 0, 0, 0, 1, 0x06, 0x05, 'O', 'R', 'B', 'B', 'E', 'C' };
        sink.on_frame(frame);
    }
    std::ifstream input(output, std::ios::binary);
    std::vector<char> bytes((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    REQUIRE(bytes.size() == image_size);
    std::filesystem::remove(output);
}

TEST_CASE("Orbbec local MCAP and SchemaPusher modes are mutually exclusive", "[orbbec][cli][mcap]")
{
    plugins::orbbec::CaptureConfig config;
    config.collection_prefix = "ego";
    config.mcap_filename = "metadata.mcap";
    REQUIRE_THROWS_AS(plugins::orbbec::create_frame_sink({}, config), std::invalid_argument);
}
