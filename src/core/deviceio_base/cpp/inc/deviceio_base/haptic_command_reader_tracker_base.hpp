// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <string_view>

namespace core
{

struct HapticCommandTrackedT;

// Abstract base interface for HapticCommandReaderTracker implementations.
class IHapticCommandReaderTrackerImpl : public ITrackerImpl
{
public:
    // Latest command across all endpoints. Correct for a single-endpoint device;
    // for a multi-endpoint device it returns whichever endpoint was pushed last,
    // so prefer the endpoint overload there. Kept for backward compatibility.
    virtual const HapticCommandTrackedT& get_data() const = 0;

    // Latest command for `endpoint` ("left"/"right"/...); `data` is null until a
    // sample for that endpoint arrives. Endpoints are tracked independently so
    // commands pushed for different endpoints on one collection do not clobber
    // each other.
    virtual const HapticCommandTrackedT& get_data(std::string_view endpoint) const = 0;
};

} // namespace core
