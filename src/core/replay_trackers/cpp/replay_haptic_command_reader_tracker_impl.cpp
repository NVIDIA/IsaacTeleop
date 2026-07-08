// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "replay_haptic_command_reader_tracker_impl.hpp"

namespace core
{

void ReplayHapticCommandReaderTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
}

const HapticCommandTrackedT& ReplayHapticCommandReaderTrackerImpl::get_data() const
{
    return tracked_;
}

} // namespace core
