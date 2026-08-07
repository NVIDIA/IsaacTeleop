// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <schema/orbbec_audio_generated.h>
#include <schema/orbbec_calibration_generated.h>
#include <schema/orbbec_camera_generated.h>
#include <schema/orbbec_device_state_generated.h>
#include <schema/orbbec_imu_generated.h>

#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace plugins::orbbec
{

struct StreamConfig
{
    core::OrbbecCameraStream camera;
    std::string output_path;
    core::OrbbecPixelFormat pixel_format = core::OrbbecPixelFormat_Mjpg;
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t fps = 0;
};

enum class McapMediaMode
{
    MetadataOnly,
    Embedded,
};

struct PropertySetting
{
    std::string name;
    double value = 0.0;
};

struct CaptureConfig
{
    std::string device_uid;
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t fps = 0;
    uint32_t bitrate = 0;
    bool dynamic_bitrate = false;
    bool dynamic_bitrate_set = false;
    bool preview = false;
    bool enable_imu = false;
    uint32_t imu_rate = 400;
    // These are requests, not a PID contract. start_imu validates them against
    // the profiles enumerated from the selected device.
    float accel_full_scale_g = 24.0f;
    float gyro_full_scale_dps = 2000.0f;
    bool enable_audio = false;
    std::string audio_output;
    std::string collection_prefix;
    std::string mcap_filename;
    std::string mcap_media_spool;
    McapMediaMode mcap_media_mode = McapMediaMode::MetadataOnly;
    bool keep_media_sidecars = false;
    std::string calibration_output;
    std::vector<PropertySetting> properties;
    bool persist_controls = false;
};

// Encoded 60 FPS profiles can be enumerated by an Ego firmware without being
// bitstream-integrity certified. Keep the policy here (rather than silently
// selecting a different SDK profile) so CLI and embedded callers agree.
void validate_stream_config(const StreamConfig& stream, const CaptureConfig& config);

struct CapturedFrame
{
    core::FrameMetadataOrbbecT metadata;
    std::vector<uint8_t> encoded_data;
    int64_t sample_time_local_common_clock_ns = 0;
    int64_t sample_time_raw_device_clock_ns = 0;
};

class IMetadataSink
{
public:
    virtual ~IMetadataSink() = default;
    virtual void on_frame_metadata(const CapturedFrame& frame) = 0;
    virtual void on_imu_batch(const core::OrbbecImuBatchT&, int64_t, int64_t)
    {
    }
    virtual void on_audio_chunk(const core::OrbbecAudioChunkT&, int64_t, int64_t)
    {
    }
    virtual void on_encoded_video_frame(const CapturedFrame&)
    {
    }
    virtual void on_pcm_audio_chunk(const core::OrbbecPcmAudioChunkT&, int64_t, int64_t)
    {
    }
    virtual void on_calibration(const core::OrbbecCalibrationT&, int64_t, int64_t)
    {
    }
    virtual void on_device_state(const core::OrbbecDeviceStateT&, int64_t, int64_t)
    {
    }
    virtual void close()
    {
    }
    virtual std::string error() const
    {
        return {};
    }
};

class FrameSink
{
public:
    FrameSink(const std::vector<StreamConfig>& streams,
              std::unique_ptr<IMetadataSink> metadata_sink = nullptr,
              bool write_media_sidecars = true);
    ~FrameSink();

    FrameSink(const FrameSink&) = delete;
    FrameSink& operator=(const FrameSink&) = delete;

    void on_frame(const CapturedFrame& frame);
    IMetadataSink* metadata_sink();
    void close_metadata();
    std::string metadata_error() const;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

std::unique_ptr<FrameSink> create_frame_sink(const std::vector<StreamConfig>& streams,
                                             const std::string& collection_prefix);
std::unique_ptr<FrameSink> create_frame_sink(const std::vector<StreamConfig>& streams, const CaptureConfig& config);

struct StreamStats
{
    uint64_t frame_count = 0;
    uint64_t byte_count = 0;
    uint64_t sequence_gaps = 0;
    uint64_t last_sequence = 0;
    int64_t last_device_timestamp_ns = 0;
};

struct AuxiliaryStats
{
    uint64_t accel_samples = 0;
    uint64_t gyro_samples = 0;
    uint64_t audio_samples = 0;
    uint64_t publish_queue_peak = 0;
    uint64_t dropped_events = 0;
    uint64_t dropped_video_frame_sets = 0;
};

class OrbbecCamera
{
public:
    OrbbecCamera(const CaptureConfig& config, const std::vector<StreamConfig>& streams, std::unique_ptr<FrameSink> sink);
    ~OrbbecCamera();

    OrbbecCamera(const OrbbecCamera&) = delete;
    OrbbecCamera& operator=(const OrbbecCamera&) = delete;

    void update();
    void close();
    void print_stats() const;
    const std::map<core::OrbbecCameraStream, StreamStats>& stats() const;
    const AuxiliaryStats& auxiliary_stats() const;
    bool preview_closed() const;

    static void list_capabilities(const CaptureConfig& config);

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace plugins::orbbec
