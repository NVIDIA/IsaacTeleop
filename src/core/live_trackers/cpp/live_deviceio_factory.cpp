// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/live_trackers/live_deviceio_factory.hpp"

#include "live_controller_tracker_impl.hpp"
#include "live_frame_metadata_tracker_oak_impl.hpp"
#include "live_full_body_tracker_pico_impl.hpp"
#include "live_generic_3axis_pedal_tracker_impl.hpp"
#include "live_hand_tracker_impl.hpp"
#include "live_head_tracker_impl.hpp"

#include <deviceio_trackers/controller_tracker.hpp>
#include <deviceio_trackers/frame_metadata_tracker_oak.hpp>
#include <deviceio_trackers/full_body_tracker_pico.hpp>
#include <deviceio_trackers/generic_3axis_pedal_tracker.hpp>
#include <deviceio_trackers/hand_tracker.hpp>
#include <deviceio_trackers/head_tracker.hpp>

namespace core
{

LiveDeviceIOFactory::LiveDeviceIOFactory(const OpenXRSessionHandles& handles) : handles_(handles)
{
}

std::unique_ptr<HeadTrackerImpl> LiveDeviceIOFactory::create_head_tracker_impl(const HeadTracker* /*tracker*/)
{
    return std::make_unique<LiveHeadTrackerImpl>(handles_);
}

std::unique_ptr<HandTrackerImpl> LiveDeviceIOFactory::create_hand_tracker_impl(const HandTracker* /*tracker*/)
{
    return std::make_unique<LiveHandTrackerImpl>(handles_);
}

std::unique_ptr<ControllerTrackerImpl> LiveDeviceIOFactory::create_controller_tracker_impl(const ControllerTracker* /*tracker*/)
{
    return std::make_unique<LiveControllerTrackerImpl>(handles_);
}

std::unique_ptr<FullBodyTrackerPicoImpl> LiveDeviceIOFactory::create_full_body_tracker_pico_impl(
    const FullBodyTrackerPico* /*tracker*/)
{
    return std::make_unique<LiveFullBodyTrackerPicoImpl>(handles_);
}

std::unique_ptr<Generic3AxisPedalTrackerImpl> LiveDeviceIOFactory::create_generic_3axis_pedal_tracker_impl(
    const Generic3AxisPedalTracker* tracker)
{
    return std::make_unique<LiveGeneric3AxisPedalTrackerImpl>(handles_, tracker);
}

std::unique_ptr<FrameMetadataTrackerOakImpl> LiveDeviceIOFactory::create_frame_metadata_tracker_oak_impl(
    const FrameMetadataTrackerOak* tracker)
{
    return std::make_unique<LiveFrameMetadataTrackerOakImpl>(handles_, tracker);
}

} // namespace core
