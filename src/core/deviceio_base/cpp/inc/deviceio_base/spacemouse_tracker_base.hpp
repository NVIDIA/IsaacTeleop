// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

namespace core
{

struct SpaceMouseOutputTrackedT;

// Abstract base interface for SpaceMouseTracker implementations.
class ISpaceMouseTrackerImpl : public ITrackerImpl
{
public:
    virtual const SpaceMouseOutputTrackedT& get_data() const = 0;
};

} // namespace core
