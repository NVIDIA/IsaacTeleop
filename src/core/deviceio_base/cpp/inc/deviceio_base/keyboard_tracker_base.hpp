// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

namespace core
{

struct KeyboardOutputTrackedT;

// Abstract base interface for KeyboardTracker implementations.
class IKeyboardTrackerImpl : public ITrackerImpl
{
public:
    virtual const KeyboardOutputTrackedT& get_data() const = 0;
};

} // namespace core
