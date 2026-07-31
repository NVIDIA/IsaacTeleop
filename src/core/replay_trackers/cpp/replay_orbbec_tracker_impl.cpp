// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "replay_orbbec_tracker_impl.hpp"

#include <stdexcept>
#include <utility>

namespace core
{

ReplayFrameMetadataTrackerOrbbecImpl::ReplayFrameMetadataTrackerOrbbecImpl(std::unique_ptr<mcap::McapReader> reader,
                                                                           std::string_view base_name,
                                                                           const std::vector<std::string>& channels)
    : viewers_(std::make_unique<McapTrackerViewers<FrameMetadataOrbbecRecord>>(std::move(reader), base_name, channels)),
      streams_(channels.size())
{
}

void ReplayFrameMetadataTrackerOrbbecImpl::update(int64_t /*monotonic_time_ns*/)
{
    for (size_t index = 0; index < streams_.size(); ++index)
    {
        auto record = viewers_->read(index);
        streams_[index].data = record ? std::move(record->data) : nullptr;
    }
}

const FrameMetadataOrbbecTrackedT& ReplayFrameMetadataTrackerOrbbecImpl::get_stream_data(size_t index) const
{
    if (index >= streams_.size())
        throw std::out_of_range("FrameMetadataTrackerOrbbec: invalid stream index");
    return streams_[index];
}

ReplayOrbbecImuTrackerImpl::ReplayOrbbecImuTrackerImpl(std::unique_ptr<mcap::McapReader> reader,
                                                       std::string_view base_name,
                                                       const std::vector<std::string>& channels)
    : viewers_(std::make_unique<McapTrackerViewers<OrbbecImuBatchRecord>>(std::move(reader), base_name, channels)),
      streams_(channels.size())
{
}

void ReplayOrbbecImuTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    for (size_t index = 0; index < streams_.size(); ++index)
    {
        auto record = viewers_->read(index);
        streams_[index].data = record ? std::move(record->data) : nullptr;
    }
}

const OrbbecImuBatchTrackedT& ReplayOrbbecImuTrackerImpl::get_stream_data(size_t index) const
{
    if (index >= streams_.size())
        throw std::out_of_range("OrbbecImuTracker: invalid stream index");
    return streams_[index];
}

ReplayOrbbecAudioTrackerImpl::ReplayOrbbecAudioTrackerImpl(std::unique_ptr<mcap::McapReader> reader,
                                                           std::string_view base_name)
    : viewers_(std::make_unique<McapTrackerViewers<OrbbecAudioChunkRecord>>(
          std::move(reader), base_name, std::vector<std::string>{ "Audio" }))
{
}

void ReplayOrbbecAudioTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    auto record = viewers_->read(0);
    tracked_.data = record ? std::move(record->data) : nullptr;
}

ReplayOrbbecCalibrationTrackerImpl::ReplayOrbbecCalibrationTrackerImpl(std::unique_ptr<mcap::McapReader> reader,
                                                                       std::string_view base_name)
    : viewers_(std::make_unique<McapTrackerViewers<OrbbecCalibrationRecord>>(
          std::move(reader), base_name, std::vector<std::string>{ "Calibration" }))
{
}

void ReplayOrbbecCalibrationTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    auto record = viewers_->read(0);
    tracked_.data = record ? std::move(record->data) : nullptr;
}

ReplayOrbbecDeviceStateTrackerImpl::ReplayOrbbecDeviceStateTrackerImpl(std::unique_ptr<mcap::McapReader> reader,
                                                                       std::string_view base_name)
    : viewers_(std::make_unique<McapTrackerViewers<OrbbecDeviceStateRecord>>(
          std::move(reader), base_name, std::vector<std::string>{ "DeviceState" }))
{
}

void ReplayOrbbecDeviceStateTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    auto record = viewers_->read(0);
    tracked_.data = record ? std::move(record->data) : nullptr;
}

} // namespace core
