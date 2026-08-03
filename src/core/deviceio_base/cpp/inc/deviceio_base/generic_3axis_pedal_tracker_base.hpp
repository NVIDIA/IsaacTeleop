// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <schema/serialized.hpp>

namespace core
{

struct Generic3AxisPedalOutput;

// Abstract base interface for Generic3AxisPedalTracker implementations.
class IGeneric3AxisPedalTrackerImpl : public ITrackerImpl
{
public:
    virtual const Serialized<Generic3AxisPedalOutput>& get_data() const = 0;
};

} // namespace core
