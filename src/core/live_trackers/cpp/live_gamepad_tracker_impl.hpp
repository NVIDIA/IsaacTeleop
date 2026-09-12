// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"

#include <deviceio_trackers/gamepad_tracker.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <schema/gamepad_generated.h>

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

using GamepadMcapChannels = McapTrackerChannels<GamepadOutputRecord, GamepadOutput>;
using GamepadSchemaTracker = SchemaTracker<GamepadOutputRecord, GamepadOutput>;

class LiveGamepadTrackerImpl : public IGamepadTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }
    static std::unique_ptr<GamepadMcapChannels> create_mcap_channels(mcap::McapWriter& writer,
                                                                     std::string_view base_name);

    LiveGamepadTrackerImpl(const OpenXRSessionHandles& handles,
                           const GamepadTracker* tracker,
                           std::unique_ptr<GamepadMcapChannels> mcap_channels);

    LiveGamepadTrackerImpl(const LiveGamepadTrackerImpl&) = delete;
    LiveGamepadTrackerImpl& operator=(const LiveGamepadTrackerImpl&) = delete;
    LiveGamepadTrackerImpl(LiveGamepadTrackerImpl&&) = delete;
    LiveGamepadTrackerImpl& operator=(LiveGamepadTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const GamepadOutputTrackedT& get_data() const override;

private:
    std::unique_ptr<GamepadMcapChannels> mcap_channels_;
    GamepadSchemaTracker m_schema_reader;
    GamepadOutputTrackedT m_tracked;
};

} // namespace core
