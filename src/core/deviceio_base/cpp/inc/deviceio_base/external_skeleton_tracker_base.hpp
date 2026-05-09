// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

namespace core
{

struct ExternalSkeletonPoseTrackedT;

// Abstract base interface for ExternalSkeletonTracker implementations.
//
// Stays runtime-agnostic per deviceio_base/AGENTS.md: no XrTime, no OpenXR
// includes. The live backend (LiveExternalSkeletonTrackerImpl) handles all
// transport via SchemaTracker.
class IExternalSkeletonTrackerImpl : public ITrackerImpl
{
public:
    virtual const ExternalSkeletonPoseTrackedT& get_skeleton_pose() const = 0;
};

} // namespace core
