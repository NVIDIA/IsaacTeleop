// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/frame_metadata_tracker_orbbec_base.hpp>
#include <deviceio_base/orbbec_ego_tracker_base.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/orbbec_audio_generated.h>
#include <schema/orbbec_calibration_generated.h>
#include <schema/orbbec_camera_generated.h>
#include <schema/orbbec_device_state_generated.h>
#include <schema/orbbec_imu_generated.h>

#include <memory>
#include <string_view>
#include <vector>

namespace core
{

class ReplayFrameMetadataTrackerOrbbecImpl : public IFrameMetadataTrackerOrbbecImpl
{
public:
    ReplayFrameMetadataTrackerOrbbecImpl(std::unique_ptr<mcap::McapReader> reader,
                                         std::string_view base_name,
                                         const std::vector<std::string>& channels);
    void update(int64_t monotonic_time_ns) override;
    const FrameMetadataOrbbecTrackedT& get_stream_data(size_t stream_index) const override;

private:
    std::unique_ptr<McapTrackerViewers<FrameMetadataOrbbecRecord>> viewers_;
    std::vector<FrameMetadataOrbbecTrackedT> streams_;
};

class ReplayOrbbecImuTrackerImpl : public IOrbbecImuTrackerImpl
{
public:
    ReplayOrbbecImuTrackerImpl(std::unique_ptr<mcap::McapReader> reader,
                               std::string_view base_name,
                               const std::vector<std::string>& channels);
    void update(int64_t monotonic_time_ns) override;
    const OrbbecImuBatchTrackedT& get_stream_data(size_t stream_index) const override;

private:
    std::unique_ptr<McapTrackerViewers<OrbbecImuBatchRecord>> viewers_;
    std::vector<OrbbecImuBatchTrackedT> streams_;
};

class ReplayOrbbecAudioTrackerImpl : public IOrbbecAudioTrackerImpl
{
public:
    ReplayOrbbecAudioTrackerImpl(std::unique_ptr<mcap::McapReader> reader, std::string_view base_name);
    void update(int64_t monotonic_time_ns) override;
    const OrbbecAudioChunkTrackedT& get_data() const override
    {
        return tracked_;
    }

private:
    std::unique_ptr<McapTrackerViewers<OrbbecAudioChunkRecord>> viewers_;
    OrbbecAudioChunkTrackedT tracked_;
};

class ReplayOrbbecCalibrationTrackerImpl : public IOrbbecCalibrationTrackerImpl
{
public:
    ReplayOrbbecCalibrationTrackerImpl(std::unique_ptr<mcap::McapReader> reader, std::string_view base_name);
    void update(int64_t monotonic_time_ns) override;
    const OrbbecCalibrationTrackedT& get_data() const override
    {
        return tracked_;
    }

private:
    std::unique_ptr<McapTrackerViewers<OrbbecCalibrationRecord>> viewers_;
    OrbbecCalibrationTrackedT tracked_;
};

class ReplayOrbbecDeviceStateTrackerImpl : public IOrbbecDeviceStateTrackerImpl
{
public:
    ReplayOrbbecDeviceStateTrackerImpl(std::unique_ptr<mcap::McapReader> reader, std::string_view base_name);
    void update(int64_t monotonic_time_ns) override;
    const OrbbecDeviceStateTrackedT& get_data() const override
    {
        return tracked_;
    }

private:
    std::unique_ptr<McapTrackerViewers<OrbbecDeviceStateRecord>> viewers_;
    OrbbecDeviceStateTrackedT tracked_;
};

} // namespace core
