// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"

#include <deviceio_trackers/keyboard_tracker.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <schema/keyboard_generated.h>

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

using KeyboardMcapChannels = McapTrackerChannels<KeyboardOutputRecord, KeyboardOutput>;
using KeyboardSchemaTracker = SchemaTracker<KeyboardOutputRecord, KeyboardOutput>;

class LiveKeyboardTrackerImpl : public IKeyboardTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }
    static std::unique_ptr<KeyboardMcapChannels> create_mcap_channels(mcap::McapWriter& writer,
                                                                      std::string_view base_name);

    LiveKeyboardTrackerImpl(const OpenXRSessionHandles& handles,
                            const KeyboardTracker* tracker,
                            std::unique_ptr<KeyboardMcapChannels> mcap_channels);

    LiveKeyboardTrackerImpl(const LiveKeyboardTrackerImpl&) = delete;
    LiveKeyboardTrackerImpl& operator=(const LiveKeyboardTrackerImpl&) = delete;
    LiveKeyboardTrackerImpl(LiveKeyboardTrackerImpl&&) = delete;
    LiveKeyboardTrackerImpl& operator=(LiveKeyboardTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const KeyboardOutputTrackedT& get_data() const override;

private:
    std::unique_ptr<KeyboardMcapChannels> mcap_channels_;
    KeyboardSchemaTracker m_schema_reader;
    KeyboardOutputTrackedT m_tracked;
};

} // namespace core
