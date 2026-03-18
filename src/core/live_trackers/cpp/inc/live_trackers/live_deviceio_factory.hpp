// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/tracker_factory.hpp>

#include <memory>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace mcap
{
class McapWriter;
} // namespace mcap

namespace core
{

class ITracker;
struct OpenXRSessionHandles;

/**
 * @brief ITrackerFactory implementation for live OpenXR sessions.
 *
 * Used by DeviceIOSession to construct OpenXR-backed tracker implementations.
 * When writer is non-null, each simple impl receives a typed McapTrackerChannels
 * for MCAP recording.
 */
class LiveDeviceIOFactory : public ITrackerFactory
{
public:
    LiveDeviceIOFactory(const OpenXRSessionHandles& handles,
                        mcap::McapWriter* writer,
                        const std::vector<std::pair<const ITracker*, std::string>>& tracker_names);

    std::unique_ptr<HeadTrackerImpl> create_head_tracker_impl(const HeadTracker* tracker) override;
    std::unique_ptr<HandTrackerImpl> create_hand_tracker_impl(const HandTracker* tracker) override;
    std::unique_ptr<ControllerTrackerImpl> create_controller_tracker_impl(const ControllerTracker* tracker) override;
    std::unique_ptr<FullBodyTrackerPicoImpl> create_full_body_tracker_pico_impl(const FullBodyTrackerPico* tracker) override;
    std::unique_ptr<Generic3AxisPedalTrackerImpl> create_generic_3axis_pedal_tracker_impl(
        const Generic3AxisPedalTracker* tracker) override;
    std::unique_ptr<FrameMetadataTrackerOakImpl> create_frame_metadata_tracker_oak_impl(
        const FrameMetadataTrackerOak* tracker) override;

private:
    bool should_record(const ITracker* tracker) const;
    std::string_view get_name(const ITracker* tracker) const;

    const OpenXRSessionHandles& handles_;
    mcap::McapWriter* writer_;
    std::unordered_map<const ITracker*, std::string> name_map_;
};

} // namespace core
