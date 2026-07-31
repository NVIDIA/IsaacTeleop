// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_orbbec_ego_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/orbbec_audio_bfbs_generated.h>
#include <schema/orbbec_calibration_bfbs_generated.h>
#include <schema/orbbec_device_state_bfbs_generated.h>
#include <schema/orbbec_imu_bfbs_generated.h>

#include <stdexcept>
#include <utility>

namespace core
{
namespace
{
SchemaTrackerConfig config(std::string collection_id, size_t max_size, const char* tensor, const char* name)
{
    return { .collection_id = std::move(collection_id),
             .max_flatbuffer_size = max_size,
             .tensor_identifier = tensor,
             .localized_name = name };
}
} // namespace

std::unique_ptr<OrbbecImuMcapChannels> LiveOrbbecImuTrackerImpl::create_mcap_channels(mcap::McapWriter& writer,
                                                                                      std::string_view base_name,
                                                                                      const OrbbecImuTracker* tracker)
{
    return std::make_unique<OrbbecImuMcapChannels>(
        writer, base_name, OrbbecImuRecordingTraits::schema_name, tracker->stream_names());
}

LiveOrbbecImuTrackerImpl::LiveOrbbecImuTrackerImpl(const OpenXRSessionHandles& handles,
                                                   const OrbbecImuTracker* tracker,
                                                   std::unique_ptr<OrbbecImuMcapChannels> channels)
    : channels_(std::move(channels))
{
    for (const auto& name : tracker->stream_names())
    {
        StreamState state;
        state.reader = std::make_unique<SchemaTracker<OrbbecImuBatchRecord, OrbbecImuBatch>>(
            handles,
            config(tracker->collection_prefix() + "/" + name, tracker->max_flatbuffer_size(), "imu_batch",
                   "Orbbec IMU batch"),
            channels_.get(), streams_.size());
        streams_.push_back(std::move(state));
    }
}

void LiveOrbbecImuTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    for (auto& stream : streams_)
        stream.reader->update(stream.tracked.data);
}

const OrbbecImuBatchTrackedT& LiveOrbbecImuTrackerImpl::get_stream_data(size_t stream_index) const
{
    if (stream_index >= streams_.size())
        throw std::out_of_range("OrbbecImuTracker: invalid stream index");
    return streams_[stream_index].tracked;
}

std::unique_ptr<OrbbecAudioMcapChannels> LiveOrbbecAudioTrackerImpl::create_mcap_channels(mcap::McapWriter& writer,
                                                                                          std::string_view base_name)
{
    return std::make_unique<OrbbecAudioMcapChannels>(
        writer, base_name, OrbbecAudioRecordingTraits::schema_name, std::vector<std::string>{ "Audio" });
}

LiveOrbbecAudioTrackerImpl::LiveOrbbecAudioTrackerImpl(const OpenXRSessionHandles& handles,
                                                       const OrbbecAudioTracker* tracker,
                                                       std::unique_ptr<OrbbecAudioMcapChannels> channels)
    : channels_(std::move(channels)),
      reader_(handles,
              config(tracker->collection_prefix() + "/Audio",
                     tracker->max_flatbuffer_size(),
                     "audio_chunk",
                     "Orbbec audio index"),
              channels_.get())
{
}

void LiveOrbbecAudioTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    reader_.update(tracked_.data);
}

std::unique_ptr<OrbbecCalibrationMcapChannels> LiveOrbbecCalibrationTrackerImpl::create_mcap_channels(
    mcap::McapWriter& writer, std::string_view base_name)
{
    return std::make_unique<OrbbecCalibrationMcapChannels>(
        writer, base_name, OrbbecCalibrationRecordingTraits::schema_name, std::vector<std::string>{ "Calibration" });
}

LiveOrbbecCalibrationTrackerImpl::LiveOrbbecCalibrationTrackerImpl(const OpenXRSessionHandles& handles,
                                                                   const OrbbecCalibrationTracker* tracker,
                                                                   std::unique_ptr<OrbbecCalibrationMcapChannels> channels)
    : channels_(std::move(channels)),
      reader_(handles,
              config(tracker->collection_prefix() + "/Calibration",
                     tracker->max_flatbuffer_size(),
                     "calibration",
                     "Orbbec calibration"),
              channels_.get())
{
}

void LiveOrbbecCalibrationTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    reader_.update(tracked_.data);
}

std::unique_ptr<OrbbecDeviceStateMcapChannels> LiveOrbbecDeviceStateTrackerImpl::create_mcap_channels(
    mcap::McapWriter& writer, std::string_view base_name)
{
    return std::make_unique<OrbbecDeviceStateMcapChannels>(
        writer, base_name, OrbbecDeviceStateRecordingTraits::schema_name, std::vector<std::string>{ "DeviceState" });
}

LiveOrbbecDeviceStateTrackerImpl::LiveOrbbecDeviceStateTrackerImpl(const OpenXRSessionHandles& handles,
                                                                   const OrbbecDeviceStateTracker* tracker,
                                                                   std::unique_ptr<OrbbecDeviceStateMcapChannels> channels)
    : channels_(std::move(channels)),
      reader_(handles,
              config(tracker->collection_prefix() + "/DeviceState",
                     tracker->max_flatbuffer_size(),
                     "device_state",
                     "Orbbec device state"),
              channels_.get())
{
}

void LiveOrbbecDeviceStateTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    reader_.update(tracked_.data);
}

} // namespace core
