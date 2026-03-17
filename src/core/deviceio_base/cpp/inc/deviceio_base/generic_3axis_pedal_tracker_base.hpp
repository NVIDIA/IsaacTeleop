// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

namespace core
{

struct Generic3AxisPedalOutputTrackedT;

// Abstract base for Generic3AxisPedalTracker implementations.
class Generic3AxisPedalTrackerImpl : public ITrackerImpl
{
public:
    virtual const Generic3AxisPedalOutputTrackedT& get_data() const = 0;
};

} // namespace core
