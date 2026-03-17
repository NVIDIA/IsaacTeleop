// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

namespace core
{

struct HandPoseTrackedT;

// Abstract base for hand tracker implementations.
class HandTrackerImpl : public ITrackerImpl
{
public:
    virtual const HandPoseTrackedT& get_left_hand() const = 0;
    virtual const HandPoseTrackedT& get_right_hand() const = 0;
};

} // namespace core
