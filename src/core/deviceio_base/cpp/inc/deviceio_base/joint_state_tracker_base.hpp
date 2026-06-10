// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

namespace core
{

struct JointStateOutputTrackedT;

// Abstract base interface for JointStateTracker implementations.
//
// Backs a generic joint-space device (leader arm, exoskeleton, glove, ...): the implementation
// keeps the last-known JointStateOutput snapshot, which the JointStateTracker facade exposes.
class IJointStateTrackerImpl : public ITrackerImpl
{
public:
    virtual const JointStateOutputTrackedT& get_data() const = 0;
};

} // namespace core
