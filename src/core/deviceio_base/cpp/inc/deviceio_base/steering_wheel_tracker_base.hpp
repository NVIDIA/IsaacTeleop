// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

namespace core
{

struct SteeringWheelOutputTrackedT;

// Abstract base interface for SteeringWheelTracker implementations.
class ISteeringWheelTrackerImpl : public ITrackerImpl
{
public:
    virtual const SteeringWheelOutputTrackedT& get_data() const = 0;
};

} // namespace core
