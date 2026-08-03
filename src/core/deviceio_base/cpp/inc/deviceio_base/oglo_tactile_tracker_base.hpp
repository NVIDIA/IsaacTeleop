// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <schema/serialized.hpp>

namespace core
{

struct OgloGloveSample;

// Abstract base interface for OgloTactileTracker implementations.
class IOgloTactileTrackerImpl : public ITrackerImpl
{
public:
    virtual const Serialized<OgloGloveSample>& get_data() const = 0;
};

} // namespace core
