// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <memory>

namespace core
{

class HeadTracker;
class HeadTrackerImpl;
class HandTracker;
class HandTrackerImpl;
class ControllerTracker;
class ControllerTrackerImpl;
class FullBodyTrackerPico;
class FullBodyTrackerPicoImpl;
class Generic3AxisPedalTracker;
class Generic3AxisPedalTrackerImpl;
class FrameMetadataTrackerOak;
class FrameMetadataTrackerOakImpl;

/**
 * @brief Factory for creating tracker implementations.
 *
 * Every factory method receives a typed pointer to its originating tracker,
 * giving the factory access to any per-tracker configuration (e.g. schema
 * tracker configs, MCAP channel names) without extra parameters.
 *
 * Default implementations return nullptr (unsupported tracker type for this factory).
 * Subclasses override only the create_* methods they support; DeviceIOSession rejects
 * a null impl with a clear error.
 */
class ITrackerFactory
{
protected:
    ITrackerFactory() = default;

public:
    virtual ~ITrackerFactory() = default;

    virtual std::unique_ptr<HeadTrackerImpl> create_head_tracker_impl(const HeadTracker* tracker);
    virtual std::unique_ptr<HandTrackerImpl> create_hand_tracker_impl(const HandTracker* tracker);
    virtual std::unique_ptr<ControllerTrackerImpl> create_controller_tracker_impl(const ControllerTracker* tracker);
    virtual std::unique_ptr<FullBodyTrackerPicoImpl> create_full_body_tracker_pico_impl(const FullBodyTrackerPico* tracker);
    virtual std::unique_ptr<Generic3AxisPedalTrackerImpl> create_generic_3axis_pedal_tracker_impl(
        const Generic3AxisPedalTracker* tracker);
    virtual std::unique_ptr<FrameMetadataTrackerOakImpl> create_frame_metadata_tracker_oak_impl(
        const FrameMetadataTrackerOak* tracker);
};

} // namespace core
