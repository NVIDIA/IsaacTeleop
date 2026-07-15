// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

namespace core
{

struct Se3TrackerPoseTrackedT;

// Abstract base interface for Se3Tracker implementations.
//
// Backs a generic SE3 (6-DoF pose) tracker device (tracker puck, mocap rigid body, logical
// tracker derived from another device, ...): the implementation keeps the last-known
// Se3TrackerPose snapshot, which the Se3Tracker facade exposes.
class ISe3TrackerImpl : public ITrackerImpl
{
public:
    virtual const Se3TrackerPoseTrackedT& get_data() const = 0;
};

} // namespace core
