// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

namespace core
{

struct ControllerSnapshotTrackedT;

// Abstract base interface for controller tracker implementations.
class IControllerTrackerImpl : public ITrackerImpl
{
public:
    virtual const ControllerSnapshotTrackedT& get_left_controller() const = 0;
    virtual const ControllerSnapshotTrackedT& get_right_controller() const = 0;
};

} // namespace core
