// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"

#include <deviceio_trackers/orbbec_ego_trackers.hpp>
#include <oxr_utils/oxr_session_handles.hpp>

#include <memory>
#include <string_view>
#include <vector>

namespace core
{

using OrbbecImuMcapChannels = McapTrackerChannels<OrbbecImuBatchRecord, OrbbecImuBatch>;
using OrbbecAudioMcapChannels = McapTrackerChannels<OrbbecAudioChunkRecord, OrbbecAudioChunk>;
using OrbbecCalibrationMcapChannels = McapTrackerChannels<OrbbecCalibrationRecord, OrbbecCalibration>;
using OrbbecDeviceStateMcapChannels = McapTrackerChannels<OrbbecDeviceStateRecord, OrbbecDeviceState>;

class LiveOrbbecImuTrackerImpl : public IOrbbecImuTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }
    static std::unique_ptr<OrbbecImuMcapChannels> create_mcap_channels(mcap::McapWriter& writer,
                                                                       std::string_view base_name,
                                                                       const OrbbecImuTracker* tracker);
    LiveOrbbecImuTrackerImpl(const OpenXRSessionHandles& handles,
                             const OrbbecImuTracker* tracker,
                             std::unique_ptr<OrbbecImuMcapChannels> channels);
    void update(int64_t monotonic_time_ns) override;
    const OrbbecImuBatchTrackedT& get_stream_data(size_t stream_index) const override;

private:
    struct StreamState
    {
        std::unique_ptr<SchemaTracker<OrbbecImuBatchRecord, OrbbecImuBatch>> reader;
        OrbbecImuBatchTrackedT tracked;
    };
    std::unique_ptr<OrbbecImuMcapChannels> channels_;
    std::vector<StreamState> streams_;
};

class LiveOrbbecAudioTrackerImpl : public IOrbbecAudioTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }
    static std::unique_ptr<OrbbecAudioMcapChannels> create_mcap_channels(mcap::McapWriter& writer,
                                                                         std::string_view base_name);
    LiveOrbbecAudioTrackerImpl(const OpenXRSessionHandles& handles,
                               const OrbbecAudioTracker* tracker,
                               std::unique_ptr<OrbbecAudioMcapChannels> channels);
    void update(int64_t monotonic_time_ns) override;
    const OrbbecAudioChunkTrackedT& get_data() const override
    {
        return tracked_;
    }

private:
    std::unique_ptr<OrbbecAudioMcapChannels> channels_;
    SchemaTracker<OrbbecAudioChunkRecord, OrbbecAudioChunk> reader_;
    OrbbecAudioChunkTrackedT tracked_;
};

class LiveOrbbecCalibrationTrackerImpl : public IOrbbecCalibrationTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }
    static std::unique_ptr<OrbbecCalibrationMcapChannels> create_mcap_channels(mcap::McapWriter& writer,
                                                                               std::string_view base_name);
    LiveOrbbecCalibrationTrackerImpl(const OpenXRSessionHandles& handles,
                                     const OrbbecCalibrationTracker* tracker,
                                     std::unique_ptr<OrbbecCalibrationMcapChannels> channels);
    void update(int64_t monotonic_time_ns) override;
    const OrbbecCalibrationTrackedT& get_data() const override
    {
        return tracked_;
    }

private:
    std::unique_ptr<OrbbecCalibrationMcapChannels> channels_;
    SchemaTracker<OrbbecCalibrationRecord, OrbbecCalibration> reader_;
    OrbbecCalibrationTrackedT tracked_;
};

class LiveOrbbecDeviceStateTrackerImpl : public IOrbbecDeviceStateTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }
    static std::unique_ptr<OrbbecDeviceStateMcapChannels> create_mcap_channels(mcap::McapWriter& writer,
                                                                               std::string_view base_name);
    LiveOrbbecDeviceStateTrackerImpl(const OpenXRSessionHandles& handles,
                                     const OrbbecDeviceStateTracker* tracker,
                                     std::unique_ptr<OrbbecDeviceStateMcapChannels> channels);
    void update(int64_t monotonic_time_ns) override;
    const OrbbecDeviceStateTrackedT& get_data() const override
    {
        return tracked_;
    }

private:
    std::unique_ptr<OrbbecDeviceStateMcapChannels> channels_;
    SchemaTracker<OrbbecDeviceStateRecord, OrbbecDeviceState> reader_;
    OrbbecDeviceStateTrackedT tracked_;
};

} // namespace core
