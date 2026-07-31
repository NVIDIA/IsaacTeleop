# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from isaacteleop.schema import (
    DeviceDataTimestamp,
    FrameMetadataOrbbec,
    FrameMetadataOrbbecRecord,
    OrbbecCameraStream,
    OrbbecPixelFormat,
    OrbbecAudioChunk,
    OrbbecCalibration,
    OrbbecDevicePropertyValue,
    OrbbecDeviceState,
    OrbbecFrameMetadataEntry,
    OrbbecImuBatch,
    OrbbecImuSample,
    OrbbecImuSensor,
)


def test_orbbec_metadata_defaults_and_properties():
    metadata = FrameMetadataOrbbec()
    assert metadata.stream == OrbbecCameraStream.ColorLeft
    assert metadata.pixel_format == OrbbecPixelFormat.Mjpg

    metadata.stream = OrbbecCameraStream.ColorRight
    metadata.sequence_number = 2**64 - 1
    metadata.width = 1280
    metadata.height = 720
    metadata.fps = 30
    metadata.pixel_format = OrbbecPixelFormat.H265
    metadata.encoded_bytes = 123
    metadata.sdk_metadata = [OrbbecFrameMetadataEntry(1, 99)]

    assert metadata.stream == OrbbecCameraStream.ColorRight
    assert metadata.sequence_number == 2**64 - 1
    assert "ColorRight" in repr(metadata)
    assert metadata.pixel_format == OrbbecPixelFormat.H265
    assert metadata.sdk_metadata[0].value == 99


def test_orbbec_record_keeps_timestamp():
    metadata = FrameMetadataOrbbec()
    timestamp = DeviceDataTimestamp(1, 2, 3)
    record = FrameMetadataOrbbecRecord(metadata, timestamp)

    assert record.data is not None
    assert record.timestamp.sample_time_raw_device_clock == 3


def test_orbbec_ego_auxiliary_types():
    imu = OrbbecImuBatch()
    imu.sensor = OrbbecImuSensor.Gyro
    imu.sample_rate_hz = 1000
    imu.samples = [OrbbecImuSample(1, 2, 3, 24, 100, 200)]
    assert imu.samples[0].z_si == 3

    audio = OrbbecAudioChunk()
    audio.sample_rate_hz = 48000
    audio.wav_data_offset = 44
    assert audio.wav_data_offset == 44

    calibration = OrbbecCalibration()
    calibration.device_uid = "ego"
    assert calibration.device_uid == "ego"

    state = OrbbecDeviceState()
    state.properties = [OrbbecDevicePropertyValue(279, 8_000_000)]
    assert state.properties[0].property_id == 279
