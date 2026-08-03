// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <schema/serialized.hpp>

namespace core
{

struct HeadPose;

// Abstract base interface for head tracker implementations.
class IHeadTrackerImpl : public ITrackerImpl
{
public:
    virtual const Serialized<HeadPose>& get_head() const = 0;
};

} // namespace core
