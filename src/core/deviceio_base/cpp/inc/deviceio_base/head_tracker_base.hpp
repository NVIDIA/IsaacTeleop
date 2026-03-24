// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

namespace core
{

struct HeadPoseTrackedT;

// Abstract base interface for head tracker implementations.
class IHeadTrackerImpl : public ITrackerImpl
{
public:
    virtual const HeadPoseTrackedT& get_head() const = 0;
};

} // namespace core
