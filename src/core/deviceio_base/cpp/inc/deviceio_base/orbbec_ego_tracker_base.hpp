// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <cstddef>

namespace core
{

struct OrbbecImuBatchTrackedT;
struct OrbbecAudioChunkTrackedT;
struct OrbbecCalibrationTrackedT;
struct OrbbecDeviceStateTrackedT;

class IOrbbecImuTrackerImpl : public ITrackerImpl
{
public:
    virtual const OrbbecImuBatchTrackedT& get_stream_data(size_t stream_index) const = 0;
};

class IOrbbecAudioTrackerImpl : public ITrackerImpl
{
public:
    virtual const OrbbecAudioChunkTrackedT& get_data() const = 0;
};

class IOrbbecCalibrationTrackerImpl : public ITrackerImpl
{
public:
    virtual const OrbbecCalibrationTrackedT& get_data() const = 0;
};

class IOrbbecDeviceStateTrackerImpl : public ITrackerImpl
{
public:
    virtual const OrbbecDeviceStateTrackedT& get_data() const = 0;
};

} // namespace core
