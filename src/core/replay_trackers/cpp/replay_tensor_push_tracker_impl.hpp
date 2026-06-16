// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/tensor_push_tracker_base.hpp>

#include <atomic>
#include <cstdint>
#include <vector>

namespace core
{

// Replay has no peer to push to, so pushes are dropped. Push happens per
// frame, so the drop is logged only once to avoid flooding the console.
class ReplayTensorPushTrackerImpl : public ITensorPushTrackerImpl
{
public:
    ReplayTensorPushTrackerImpl() = default;

    void update(int64_t monotonic_time_ns) override;
    void push(const std::vector<uint8_t>& payload) const override;

private:
    mutable std::atomic<bool> m_drop_logged{ false };
};

} // namespace core
