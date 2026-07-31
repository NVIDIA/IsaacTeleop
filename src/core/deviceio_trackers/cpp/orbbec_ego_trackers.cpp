// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/orbbec_ego_trackers.hpp"

#include <set>
#include <stdexcept>
#include <utility>

namespace core
{

namespace
{
void validate_common(const std::string& tracker, const std::string& prefix, size_t max_size)
{
    if (prefix.empty())
        throw std::invalid_argument(tracker + ": collection_prefix is required");
    if (max_size == 0)
        throw std::invalid_argument(tracker + ": max_flatbuffer_size must be positive");
}
} // namespace

OrbbecImuTracker::OrbbecImuTracker(std::string collection_prefix,
                                   std::vector<OrbbecImuSensor> sensors,
                                   size_t max_flatbuffer_size)
    : collection_prefix_(std::move(collection_prefix)),
      sensors_(std::move(sensors)),
      max_flatbuffer_size_(max_flatbuffer_size)
{
    validate_common("OrbbecImuTracker", collection_prefix_, max_flatbuffer_size_);
    if (sensors_.empty())
        throw std::invalid_argument("OrbbecImuTracker: at least one sensor is required");
    std::set<OrbbecImuSensor> unique;
    for (const auto sensor : sensors_)
    {
        const char* name = EnumNameOrbbecImuSensor(sensor);
        if (name == nullptr || *name == '\0')
            throw std::invalid_argument("OrbbecImuTracker: invalid sensor");
        if (!unique.insert(sensor).second)
            throw std::invalid_argument("OrbbecImuTracker: duplicate sensor " + std::string(name));
        stream_names_.emplace_back(name);
    }
}

const OrbbecImuBatchTrackedT& OrbbecImuTracker::get_stream_data(const ITrackerSession& session, size_t stream_index) const
{
    return static_cast<const IOrbbecImuTrackerImpl&>(session.get_tracker_impl(*this)).get_stream_data(stream_index);
}

OrbbecAudioTracker::OrbbecAudioTracker(std::string collection_prefix, size_t max_flatbuffer_size)
    : collection_prefix_(std::move(collection_prefix)), max_flatbuffer_size_(max_flatbuffer_size)
{
    validate_common("OrbbecAudioTracker", collection_prefix_, max_flatbuffer_size_);
}

const OrbbecAudioChunkTrackedT& OrbbecAudioTracker::get_data(const ITrackerSession& session) const
{
    return static_cast<const IOrbbecAudioTrackerImpl&>(session.get_tracker_impl(*this)).get_data();
}

OrbbecCalibrationTracker::OrbbecCalibrationTracker(std::string collection_prefix, size_t max_flatbuffer_size)
    : collection_prefix_(std::move(collection_prefix)), max_flatbuffer_size_(max_flatbuffer_size)
{
    validate_common("OrbbecCalibrationTracker", collection_prefix_, max_flatbuffer_size_);
}

const OrbbecCalibrationTrackedT& OrbbecCalibrationTracker::get_data(const ITrackerSession& session) const
{
    return static_cast<const IOrbbecCalibrationTrackerImpl&>(session.get_tracker_impl(*this)).get_data();
}

OrbbecDeviceStateTracker::OrbbecDeviceStateTracker(std::string collection_prefix, size_t max_flatbuffer_size)
    : collection_prefix_(std::move(collection_prefix)), max_flatbuffer_size_(max_flatbuffer_size)
{
    validate_common("OrbbecDeviceStateTracker", collection_prefix_, max_flatbuffer_size_);
}

const OrbbecDeviceStateTrackedT& OrbbecDeviceStateTracker::get_data(const ITrackerSession& session) const
{
    return static_cast<const IOrbbecDeviceStateTrackerImpl&>(session.get_tracker_impl(*this)).get_data();
}

} // namespace core
