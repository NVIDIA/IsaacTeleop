// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/haptic_command_reader_tracker_base.hpp>
#include <schema/haptic_command_generated.h>

#include <cstdint>
#include <string_view>

namespace core
{

// Haptic commands are not recorded to MCAP, so replay always returns empty
// tracked data (data == nullptr).
class ReplayHapticCommandReaderTrackerImpl : public IHapticCommandReaderTrackerImpl
{
public:
    ReplayHapticCommandReaderTrackerImpl() = default;

    void update(int64_t monotonic_time_ns) override;
    const HapticCommandTrackedT& get_data() const override;
    const HapticCommandTrackedT& get_data(std::string_view endpoint) const override;

private:
    HapticCommandTrackedT tracked_;
};

} // namespace core
