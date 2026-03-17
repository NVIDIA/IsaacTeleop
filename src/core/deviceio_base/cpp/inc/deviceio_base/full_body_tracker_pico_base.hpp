// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

namespace core
{

struct FullBodyPosePicoTrackedT;

// Abstract base for full body tracker (PICO) implementations.
class FullBodyTrackerPicoImpl : public ITrackerImpl
{
public:
    virtual const FullBodyPosePicoTrackedT& get_body_pose() const = 0;
};

} // namespace core
