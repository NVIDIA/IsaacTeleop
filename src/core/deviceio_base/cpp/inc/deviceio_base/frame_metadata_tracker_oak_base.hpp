// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

namespace core
{

struct FrameMetadataOakTrackedT;

// Abstract base interface for FrameMetadataTrackerOak implementations.
class IFrameMetadataTrackerOakImpl : public ITrackerImpl
{
public:
    virtual const FrameMetadataOakTrackedT& get_data() const = 0;
};

} // namespace core
