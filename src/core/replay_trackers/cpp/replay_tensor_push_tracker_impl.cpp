// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "replay_tensor_push_tracker_impl.hpp"

#include <iostream>

namespace core
{

void ReplayTensorPushTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
}

void ReplayTensorPushTrackerImpl::push(const std::vector<uint8_t>& /*payload*/) const
{
    bool expected = false;
    if (m_drop_logged.compare_exchange_strong(expected, true))
    {
        std::cerr << "ReplayTensorPushTrackerImpl::push: no peer in replay mode; "
                     "pushes are dropped (silenced after this message)."
                  << std::endl;
    }
}

} // namespace core
