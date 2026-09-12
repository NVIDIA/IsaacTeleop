// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

namespace core
{

struct GamepadOutputTrackedT;

// Abstract base interface for GamepadTracker implementations.
class IGamepadTrackerImpl : public ITrackerImpl
{
public:
    virtual const GamepadOutputTrackedT& get_data() const = 0;
};

} // namespace core
