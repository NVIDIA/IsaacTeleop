// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/keyboard_tracker_base.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/keyboard_generated.h>

#include <cstdint>
#include <memory>
#include <string_view>

namespace core
{

using KeyboardMcapViewers = McapTrackerViewers<KeyboardOutputRecord>;

class ReplayKeyboardTrackerImpl : public IKeyboardTrackerImpl
{
public:
    ReplayKeyboardTrackerImpl(std::unique_ptr<mcap::McapReader> reader, std::string_view base_name);

    ReplayKeyboardTrackerImpl(const ReplayKeyboardTrackerImpl&) = delete;
    ReplayKeyboardTrackerImpl& operator=(const ReplayKeyboardTrackerImpl&) = delete;
    ReplayKeyboardTrackerImpl(ReplayKeyboardTrackerImpl&&) = delete;
    ReplayKeyboardTrackerImpl& operator=(ReplayKeyboardTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const KeyboardOutputTrackedT& get_data() const override;

private:
    KeyboardOutputTrackedT tracked_;
    std::unique_ptr<KeyboardMcapViewers> mcap_viewers_;
};

} // namespace core
