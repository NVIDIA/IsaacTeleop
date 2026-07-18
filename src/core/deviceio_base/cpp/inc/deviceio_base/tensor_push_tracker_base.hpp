// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <cstdint>
#include <vector>

namespace core
{

// Abstract base interface for TensorPushTracker implementations.
class ITensorPushTrackerImpl : public ITrackerImpl
{
public:
    // `payload` is an opaque serialised buffer (the caller's schema); the
    // impl pads to the configured per-sample size and attaches timestamps
    // before pushing it as a tensor sample.
    virtual void push(const std::vector<uint8_t>& payload) const = 0;
};

} // namespace core
