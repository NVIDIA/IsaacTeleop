// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <schema/serialized.hpp>

#include <cstddef>

namespace core
{

struct FrameMetadataOak;

// Abstract base interface for FrameMetadataTrackerOak implementations.
class IFrameMetadataTrackerOakImpl : public ITrackerImpl
{
public:
    virtual const Serialized<FrameMetadataOak>& get_stream_data(size_t stream_index) const = 0;
};

} // namespace core
