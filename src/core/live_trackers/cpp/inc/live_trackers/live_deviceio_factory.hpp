// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/tracker_factory.hpp>

#include <memory>

namespace core
{

struct OpenXRSessionHandles;

/**
 * @brief ITrackerFactory implementation for live OpenXR sessions.
 *
 * Used by DeviceIOSession to construct OpenXR-backed tracker implementations.
 */
class LiveDeviceIOFactory : public ITrackerFactory
{
public:
    explicit LiveDeviceIOFactory(const OpenXRSessionHandles& handles);

    std::unique_ptr<HeadTrackerImpl> create_head_tracker_impl(const HeadTracker* tracker) override;
    std::unique_ptr<HandTrackerImpl> create_hand_tracker_impl(const HandTracker* tracker) override;
    std::unique_ptr<ControllerTrackerImpl> create_controller_tracker_impl(const ControllerTracker* tracker) override;
    std::unique_ptr<FullBodyTrackerPicoImpl> create_full_body_tracker_pico_impl(const FullBodyTrackerPico* tracker) override;
    std::unique_ptr<Generic3AxisPedalTrackerImpl> create_generic_3axis_pedal_tracker_impl(
        const Generic3AxisPedalTracker* tracker) override;
    std::unique_ptr<FrameMetadataTrackerOakImpl> create_frame_metadata_tracker_oak_impl(
        const FrameMetadataTrackerOak* tracker) override;

private:
    const OpenXRSessionHandles& handles_;
};

} // namespace core
