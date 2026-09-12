// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_gamepad_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/gamepad_bfbs_generated.h>

namespace core
{

namespace
{

SchemaTrackerConfig make_gamepad_tensor_config(const GamepadTracker* tracker)
{
    SchemaTrackerConfig cfg;
    cfg.collection_id = tracker->collection_id();
    cfg.max_flatbuffer_size = tracker->max_flatbuffer_size();
    cfg.tensor_identifier = "gamepad";
    cfg.localized_name = "GamepadTracker";
    return cfg;
}

} // namespace

// ============================================================================
// LiveGamepadTrackerImpl
// ============================================================================

std::unique_ptr<GamepadMcapChannels> LiveGamepadTrackerImpl::create_mcap_channels(mcap::McapWriter& writer,
                                                                                  std::string_view base_name)
{
    return std::make_unique<GamepadMcapChannels>(
        writer, base_name, GamepadRecordingTraits::schema_name,
        std::vector<std::string>(
            GamepadRecordingTraits::recording_channels.begin(), GamepadRecordingTraits::recording_channels.end()));
}

LiveGamepadTrackerImpl::LiveGamepadTrackerImpl(const OpenXRSessionHandles& handles,
                                               const GamepadTracker* tracker,
                                               std::unique_ptr<GamepadMcapChannels> mcap_channels)
    : mcap_channels_(std::move(mcap_channels)),
      m_schema_reader(handles,
                      make_gamepad_tensor_config(tracker),
                      mcap_channels_.get(),
                      /*mcap_channel_index=*/0,
                      /*mcap_channel_tracked_index=*/1)
{
}

void LiveGamepadTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    // Policy: SchemaTracker throws on critical OpenXR/tensor API failures.
    // Missing collection/no new data are treated as common non-fatal cases.
    m_schema_reader.update(m_tracked.data);
}

const GamepadOutputTrackedT& LiveGamepadTrackerImpl::get_data() const
{
    return m_tracked;
}

} // namespace core
