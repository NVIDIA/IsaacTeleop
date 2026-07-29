// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <memory>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace core
{

class ITracker;
class ITrackerImpl;
class ControllerTracker;
class IControllerTrackerImpl;
class FullBodyTracker;
class IFullBodyTrackerImpl;
class TensorPushTracker;
class ITensorPushTrackerImpl;
class HandTracker;
class IHandTrackerImpl;
class HeadTracker;
class IHeadTrackerImpl;
class HapticCommandReaderTracker;
class IHapticCommandReaderTrackerImpl;
class MessageChannelTracker;
class IMessageChannelTrackerImpl;

// Same fragment the live factory header uses: forward decls are direction-agnostic.
#include "generated_tracker_forward_decls.inc"

/**
 * @brief Factory for replay (MCAP-backed) tracker implementations.
 *
 * Opens a fresh McapReader per tracker impl so each tracker has its own
 * FileReader buffer; crossing an MCAP chunk boundary in one tracker cannot
 * overwrite another tracker's pre-fetched message data pointer.
 */
class ReplayDeviceIOFactory
{
public:
    ReplayDeviceIOFactory(std::string filename,
                          const std::vector<std::pair<const ITracker*, std::string>>& tracker_names);

    /** Create tracker impl from a tracker instance using dynamic dispatch. */
    std::unique_ptr<ITrackerImpl> create_tracker_impl(const ITracker& tracker);

    std::unique_ptr<IHeadTrackerImpl> create_head_tracker_impl(const HeadTracker* tracker);
    std::unique_ptr<IHandTrackerImpl> create_hand_tracker_impl(const HandTracker* tracker);
    std::unique_ptr<IControllerTrackerImpl> create_controller_tracker_impl(const ControllerTracker* tracker);
    std::unique_ptr<IFullBodyTrackerImpl> create_full_body_tracker_impl(const FullBodyTracker* tracker);
    std::unique_ptr<ITensorPushTrackerImpl> create_tensor_push_tracker_impl(const TensorPushTracker* tracker);
    std::unique_ptr<IMessageChannelTrackerImpl> create_message_channel_tracker_impl(const MessageChannelTracker* tracker);
    std::unique_ptr<IHapticCommandReaderTrackerImpl> create_haptic_command_reader_tracker_impl(
        const HapticCommandReaderTracker* tracker);
    // create_<name>_tracker_impl for every manifest tracker.
#include "generated_replay_factory_declarations.inc"

private:
    std::string_view get_name(const ITracker* tracker) const;

    std::string filename_;
    std::unordered_map<const ITracker*, std::string> name_map_;
};

} // namespace core
