// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <cstdint>
#include <optional>
#include <vector>

namespace core
{

// Abstract base interface for opaque data channel tracker implementations.
// Returns raw bytes received from the XR_NV_opaque_data_channel extension.
class IOpaqueDataChannelTrackerImpl : public ITrackerImpl
{
public:
    virtual std::optional<std::vector<uint8_t>> get_latest_message() const = 0;
};

} // namespace core
