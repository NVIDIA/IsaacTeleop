// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

namespace core
{

struct FoottrollerOutputTrackedT;

// Abstract base interface for FoottrollerTracker implementations.
class IFoottrollerTrackerImpl : public ITrackerImpl
{
public:
    virtual const FoottrollerOutputTrackedT& get_data() const = 0;
};

} // namespace core
