// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_base/tracker_factory.hpp"

#include "inc/deviceio_base/controller_tracker_base.hpp"
#include "inc/deviceio_base/frame_metadata_tracker_oak_base.hpp"
#include "inc/deviceio_base/full_body_tracker_pico_base.hpp"
#include "inc/deviceio_base/generic_3axis_pedal_tracker_base.hpp"
#include "inc/deviceio_base/hand_tracker_base.hpp"
#include "inc/deviceio_base/head_tracker_base.hpp"

namespace core
{

std::unique_ptr<HeadTrackerImpl> ITrackerFactory::create_head_tracker_impl(const HeadTracker* /*tracker*/)
{
    return nullptr;
}

std::unique_ptr<HandTrackerImpl> ITrackerFactory::create_hand_tracker_impl(const HandTracker* /*tracker*/)
{
    return nullptr;
}

std::unique_ptr<ControllerTrackerImpl> ITrackerFactory::create_controller_tracker_impl(const ControllerTracker* /*tracker*/)
{
    return nullptr;
}

std::unique_ptr<FullBodyTrackerPicoImpl> ITrackerFactory::create_full_body_tracker_pico_impl(
    const FullBodyTrackerPico* /*tracker*/)
{
    return nullptr;
}

std::unique_ptr<Generic3AxisPedalTrackerImpl> ITrackerFactory::create_generic_3axis_pedal_tracker_impl(
    const Generic3AxisPedalTracker* /*tracker*/)
{
    return nullptr;
}

std::unique_ptr<FrameMetadataTrackerOakImpl> ITrackerFactory::create_frame_metadata_tracker_oak_impl(
    const FrameMetadataTrackerOak* /*tracker*/)
{
    return nullptr;
}

} // namespace core
