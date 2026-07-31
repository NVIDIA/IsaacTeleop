// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/orbbec_ego_tracker_base.hpp>
#include <schema/orbbec_audio_generated.h>
#include <schema/orbbec_calibration_generated.h>
#include <schema/orbbec_device_state_generated.h>
#include <schema/orbbec_imu_generated.h>
#include <schema/orbbec_limits.hpp>

#include <cstddef>
#include <string>
#include <vector>

namespace core
{

class OrbbecImuTracker : public ITracker
{
public:
    OrbbecImuTracker(std::string collection_prefix,
                     std::vector<OrbbecImuSensor> sensors = { OrbbecImuSensor_Accel, OrbbecImuSensor_Gyro },
                     size_t max_flatbuffer_size = ORBBEC_MAX_FLATBUFFER_SIZE);
    std::string_view get_name() const override
    {
        return "OrbbecImuTracker";
    }
    const OrbbecImuBatchTrackedT& get_stream_data(const ITrackerSession& session, size_t stream_index) const;
    const std::string& collection_prefix() const
    {
        return collection_prefix_;
    }
    const std::vector<OrbbecImuSensor>& sensors() const
    {
        return sensors_;
    }
    const std::vector<std::string>& stream_names() const
    {
        return stream_names_;
    }
    size_t max_flatbuffer_size() const
    {
        return max_flatbuffer_size_;
    }
    size_t get_stream_count() const
    {
        return sensors_.size();
    }

private:
    std::string collection_prefix_;
    std::vector<OrbbecImuSensor> sensors_;
    std::vector<std::string> stream_names_;
    size_t max_flatbuffer_size_;
};

class OrbbecAudioTracker : public ITracker
{
public:
    explicit OrbbecAudioTracker(std::string collection_prefix, size_t max_flatbuffer_size = ORBBEC_MAX_FLATBUFFER_SIZE);
    std::string_view get_name() const override
    {
        return "OrbbecAudioTracker";
    }
    const OrbbecAudioChunkTrackedT& get_data(const ITrackerSession& session) const;
    const std::string& collection_prefix() const
    {
        return collection_prefix_;
    }
    size_t max_flatbuffer_size() const
    {
        return max_flatbuffer_size_;
    }

private:
    std::string collection_prefix_;
    size_t max_flatbuffer_size_;
};

class OrbbecCalibrationTracker : public ITracker
{
public:
    explicit OrbbecCalibrationTracker(std::string collection_prefix,
                                      size_t max_flatbuffer_size = ORBBEC_MAX_FLATBUFFER_SIZE);
    std::string_view get_name() const override
    {
        return "OrbbecCalibrationTracker";
    }
    const OrbbecCalibrationTrackedT& get_data(const ITrackerSession& session) const;
    const std::string& collection_prefix() const
    {
        return collection_prefix_;
    }
    size_t max_flatbuffer_size() const
    {
        return max_flatbuffer_size_;
    }

private:
    std::string collection_prefix_;
    size_t max_flatbuffer_size_;
};

class OrbbecDeviceStateTracker : public ITracker
{
public:
    explicit OrbbecDeviceStateTracker(std::string collection_prefix,
                                      size_t max_flatbuffer_size = ORBBEC_MAX_FLATBUFFER_SIZE);
    std::string_view get_name() const override
    {
        return "OrbbecDeviceStateTracker";
    }
    const OrbbecDeviceStateTrackedT& get_data(const ITrackerSession& session) const;
    const std::string& collection_prefix() const
    {
        return collection_prefix_;
    }
    size_t max_flatbuffer_size() const
    {
        return max_flatbuffer_size_;
    }

private:
    std::string collection_prefix_;
    size_t max_flatbuffer_size_;
};

} // namespace core
