// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

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
class ITrackerImpl;
class ControllerTracker;
class IControllerTrackerImpl;
class FrameMetadataTrackerOak;
class IFrameMetadataTrackerOakImpl;
class MessageChannelTracker;
class IMessageChannelTrackerImpl;
class FullBodyTrackerPico;
class IFullBodyTrackerPicoImpl;
class Generic3AxisPedalTracker;
class IGeneric3AxisPedalTrackerImpl;
class OgloTactileTracker;
class IOgloTactileTrackerImpl;
class TensorPushTracker;
class ITensorPushTrackerImpl;
class HapticCommandReaderTracker;
class IHapticCommandReaderTrackerImpl;
class JointStateTracker;
class IJointStateTrackerImpl;
class Se3Tracker;
class ISe3TrackerImpl;
class HandTracker;
class IHandTrackerImpl;
class HeadTracker;
class IHeadTrackerImpl;
struct OpenXRSessionHandles;

/**
 * @brief Factory for live OpenXR tracker implementations.
 *
 * Used by DeviceIOSession to construct OpenXR-backed tracker implementations.
 * When writer is non-null, each simple impl receives a typed McapTrackerChannels
 * for MCAP recording.
 */
class LiveDeviceIOFactory
{
public:
    /** Aggregate OpenXR extensions required by the given trackers for a live session. */
    static std::vector<std::string> get_required_extensions(const std::vector<std::shared_ptr<ITracker>>& trackers);
    /** Create tracker impl from a tracker instance using the same dispatch table as extension discovery. */
    std::unique_ptr<ITrackerImpl> create_tracker_impl(const ITracker& tracker);

    LiveDeviceIOFactory(const OpenXRSessionHandles& handles,
                        mcap::McapWriter* writer,
                        const std::vector<std::pair<const ITracker*, std::string>>& tracker_names);

    std::unique_ptr<IHeadTrackerImpl> create_head_tracker_impl(const HeadTracker* tracker);
    std::unique_ptr<IHandTrackerImpl> create_hand_tracker_impl(const HandTracker* tracker);
    std::unique_ptr<IControllerTrackerImpl> create_controller_tracker_impl(const ControllerTracker* tracker);
    std::unique_ptr<IMessageChannelTrackerImpl> create_message_channel_tracker_impl(const MessageChannelTracker* tracker);
    std::unique_ptr<IFullBodyTrackerPicoImpl> create_full_body_tracker_pico_impl(const FullBodyTrackerPico* tracker);
    std::unique_ptr<IGeneric3AxisPedalTrackerImpl> create_generic_3axis_pedal_tracker_impl(
        const Generic3AxisPedalTracker* tracker);
    std::unique_ptr<IOgloTactileTrackerImpl> create_oglo_tactile_tracker_impl(const OgloTactileTracker* tracker);
    std::unique_ptr<ITensorPushTrackerImpl> create_tensor_push_tracker_impl(const TensorPushTracker* tracker);
    std::unique_ptr<IHapticCommandReaderTrackerImpl> create_haptic_command_reader_tracker_impl(
        const HapticCommandReaderTracker* tracker);
    std::unique_ptr<IJointStateTrackerImpl> create_joint_state_tracker_impl(const JointStateTracker* tracker);
    std::unique_ptr<ISe3TrackerImpl> create_se3_tracker_impl(const Se3Tracker* tracker);
    std::unique_ptr<IFrameMetadataTrackerOakImpl> create_frame_metadata_tracker_oak_impl(
        const FrameMetadataTrackerOak* tracker);

private:
    bool should_record(const ITracker* tracker) const;
    std::string_view get_name(const ITracker* tracker) const;

    const OpenXRSessionHandles& handles_;
    mcap::McapWriter* writer_;
    std::unordered_map<const ITracker*, std::string> name_map_;
};

} // namespace core
