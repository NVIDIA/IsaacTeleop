// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_keyboard_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/keyboard_bfbs_generated.h>

namespace core
{

namespace
{

SchemaTrackerConfig make_keyboard_tensor_config(const KeyboardTracker* tracker)
{
    SchemaTrackerConfig cfg;
    cfg.collection_id = tracker->collection_id();
    cfg.max_flatbuffer_size = tracker->max_flatbuffer_size();
    cfg.tensor_identifier = "keyboard";
    cfg.localized_name = "KeyboardTracker";
    return cfg;
}

} // namespace

// ============================================================================
// LiveKeyboardTrackerImpl
// ============================================================================

std::unique_ptr<KeyboardMcapChannels> LiveKeyboardTrackerImpl::create_mcap_channels(mcap::McapWriter& writer,
                                                                                    std::string_view base_name)
{
    return std::make_unique<KeyboardMcapChannels>(
        writer, base_name, KeyboardRecordingTraits::schema_name,
        std::vector<std::string>(
            KeyboardRecordingTraits::recording_channels.begin(), KeyboardRecordingTraits::recording_channels.end()));
}

LiveKeyboardTrackerImpl::LiveKeyboardTrackerImpl(const OpenXRSessionHandles& handles,
                                                 const KeyboardTracker* tracker,
                                                 std::unique_ptr<KeyboardMcapChannels> mcap_channels)
    : mcap_channels_(std::move(mcap_channels)),
      m_schema_reader(handles,
                      make_keyboard_tensor_config(tracker),
                      mcap_channels_.get(),
                      /*mcap_channel_index=*/0,
                      /*mcap_channel_tracked_index=*/1)
{
}

void LiveKeyboardTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    // Policy: SchemaTracker throws on critical OpenXR/tensor API failures.
    // Missing collection/no new data are treated as common non-fatal cases.
    m_schema_reader.update(m_tracked.data);
}

const KeyboardOutputTrackedT& LiveKeyboardTrackerImpl::get_data() const
{
    return m_tracked;
}

} // namespace core
