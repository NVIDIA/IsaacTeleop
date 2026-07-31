// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>
#include <schema/orbbec_audio_generated.h>
#include <schema/orbbec_calibration_generated.h>
#include <schema/orbbec_camera_generated.h>
#include <schema/orbbec_device_state_generated.h>
#include <schema/orbbec_imu_generated.h>
#include <schema/timestamp_generated.h>

#include <cstdint>
#include <memory>

#define VT(field) (field + 2) * 2

static_assert(core::FrameMetadataOrbbec::VT_STREAM == VT(0));
static_assert(core::FrameMetadataOrbbec::VT_SEQUENCE_NUMBER == VT(1));
static_assert(core::FrameMetadataOrbbec::VT_WIDTH == VT(2));
static_assert(core::FrameMetadataOrbbec::VT_HEIGHT == VT(3));
static_assert(core::FrameMetadataOrbbec::VT_FPS == VT(4));
static_assert(core::FrameMetadataOrbbec::VT_PIXEL_FORMAT == VT(5));
static_assert(core::FrameMetadataOrbbec::VT_ENCODED_BYTES == VT(6));
static_assert(core::FrameMetadataOrbbec::VT_SDK_METADATA == VT(7));
static_assert(core::OrbbecPixelFormat_Mjpg == 0);

TEST_CASE("Orbbec camera metadata round trips", "[orbbec][schema]")
{
    core::FrameMetadataOrbbecT original;
    original.stream = core::OrbbecCameraStream_ColorRight;
    original.sequence_number = UINT64_MAX;
    original.width = 1280;
    original.height = 720;
    original.fps = 30;
    original.pixel_format = core::OrbbecPixelFormat_Mjpg;
    original.encoded_bytes = 1234;
    original.sdk_metadata.emplace_back(1, 99);

    flatbuffers::FlatBufferBuilder builder;
    builder.Finish(core::FrameMetadataOrbbec::Pack(builder, &original));

    core::FrameMetadataOrbbecT restored;
    flatbuffers::GetRoot<core::FrameMetadataOrbbec>(builder.GetBufferPointer())->UnPackTo(&restored);
    CHECK(restored.stream == core::OrbbecCameraStream_ColorRight);
    CHECK(restored.sequence_number == UINT64_MAX);
    CHECK(restored.width == 1280);
    CHECK(restored.height == 720);
    CHECK(restored.fps == 30);
    CHECK(restored.pixel_format == core::OrbbecPixelFormat_Mjpg);
    CHECK(restored.encoded_bytes == 1234);
    REQUIRE(restored.sdk_metadata.size() == 1);
    CHECK(restored.sdk_metadata[0].value() == 99);
}

TEST_CASE("Orbbec Ego auxiliary schemas round trip", "[orbbec][schema]")
{
    core::OrbbecImuBatchT imu;
    imu.sensor = core::OrbbecImuSensor_Gyro;
    imu.sequence_number = 5;
    imu.sample_rate_hz = 1000;
    imu.full_scale = 500;
    imu.samples.emplace_back(1, 2, 3, 24, 100, 200);
    flatbuffers::FlatBufferBuilder imu_builder;
    imu_builder.Finish(core::OrbbecImuBatch::Pack(imu_builder, &imu));
    core::OrbbecImuBatchT restored_imu;
    flatbuffers::GetRoot<core::OrbbecImuBatch>(imu_builder.GetBufferPointer())->UnPackTo(&restored_imu);
    REQUIRE(restored_imu.samples.size() == 1);
    CHECK(restored_imu.samples[0].z_si() == 3);

    core::OrbbecAudioChunkT audio;
    audio.sample_rate_hz = 48000;
    audio.channel_count = 1;
    audio.bits_per_sample = 16;
    audio.sample_count = 480;
    audio.wav_data_offset = 44;
    flatbuffers::FlatBufferBuilder audio_builder;
    audio_builder.Finish(core::OrbbecAudioChunk::Pack(audio_builder, &audio));
    core::OrbbecAudioChunkT restored_audio;
    flatbuffers::GetRoot<core::OrbbecAudioChunk>(audio_builder.GetBufferPointer())->UnPackTo(&restored_audio);
    CHECK(restored_audio.wav_data_offset == 44);
    CHECK(restored_audio.sample_count == 480);

    core::OrbbecCalibrationT calibration;
    calibration.device_uid = "ego";
    calibration.raw_alignment_yaml = "camera: left";
    flatbuffers::FlatBufferBuilder calibration_builder;
    calibration_builder.Finish(core::OrbbecCalibration::Pack(calibration_builder, &calibration));
    core::OrbbecCalibrationT restored_calibration;
    flatbuffers::GetRoot<core::OrbbecCalibration>(calibration_builder.GetBufferPointer())->UnPackTo(&restored_calibration);
    CHECK(restored_calibration.device_uid == "ego");

    core::OrbbecDeviceStateT state;
    state.sequence_number = 7;
    state.temperature_c = 31.5f;
    state.properties.emplace_back(279, 8'000'000);
    flatbuffers::FlatBufferBuilder state_builder;
    state_builder.Finish(core::OrbbecDeviceState::Pack(state_builder, &state));
    core::OrbbecDeviceStateT restored_state;
    flatbuffers::GetRoot<core::OrbbecDeviceState>(state_builder.GetBufferPointer())->UnPackTo(&restored_state);
    CHECK(restored_state.temperature_c == 31.5f);
    REQUIRE(restored_state.properties.size() == 1);
}

TEST_CASE("Orbbec camera record retains timestamp", "[orbbec][schema]")
{
    auto record = std::make_shared<core::FrameMetadataOrbbecRecordT>();
    record->data = std::make_shared<core::FrameMetadataOrbbecT>();
    record->timestamp = std::make_shared<core::DeviceDataTimestamp>(1, 2, 3);

    flatbuffers::FlatBufferBuilder builder;
    builder.Finish(core::FrameMetadataOrbbecRecord::Pack(builder, record.get()));
    const auto* restored = flatbuffers::GetRoot<core::FrameMetadataOrbbecRecord>(builder.GetBufferPointer());
    REQUIRE(restored->timestamp() != nullptr);
    CHECK(restored->timestamp()->available_time_local_common_clock() == 1);
    CHECK(restored->timestamp()->sample_time_local_common_clock() == 2);
    CHECK(restored->timestamp()->sample_time_raw_device_clock() == 3);
}
