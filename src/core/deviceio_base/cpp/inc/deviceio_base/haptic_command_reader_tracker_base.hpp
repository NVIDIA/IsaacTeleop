// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

namespace core
{

struct HapticCommandTrackedT;

// Abstract base interface for HapticCommandReaderTracker implementations.
class IHapticCommandReaderTrackerImpl : public ITrackerImpl
{
public:
    virtual const HapticCommandTrackedT& get_data() const = 0;
};

} // namespace core
