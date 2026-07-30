// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <array>
#include <string_view>

namespace core
{

/**
 * @brief Compile-time MCAP recording metadata per tracker type.
 *
 * Centralizes schema names and default channel names used for MCAP recording
 * and replay. Each tracker impl's create_mcap_channels references these
 * instead of embedding string literals.
 */

struct HeadRecordingTraits
{
    static constexpr std::string_view schema_name = "core.HeadPoseRecord";
    static constexpr std::array recording_channels = { "head" };
    static constexpr std::array replay_channels = { "head" };
};

struct HandRecordingTraits
{
    static constexpr std::string_view schema_name = "core.HandPoseRecord";
    static constexpr std::array recording_channels = { "left_hand", "right_hand" };
    static constexpr std::array replay_channels = { "left_hand", "right_hand" };
};

struct ControllerRecordingTraits
{
    static constexpr std::string_view schema_name = "core.ControllerSnapshotRecord";
    static constexpr std::array recording_channels = { "left_controller", "right_controller" };
    static constexpr std::array replay_channels = { "left_controller", "right_controller" };
};

struct FullBodyRecordingTraits
{
    static constexpr std::string_view schema_name = "core.FullBodyPoseRecord";
    static constexpr std::array recording_channels = { "full_body" };
    static constexpr std::array replay_channels = { "full_body" };
};

// Deprecated alias for the renamed FullBodyRecordingTraits (was
// FullBodyPicoRecordingTraits before the vendor-agnostic rename). Retained so source
// referencing the old type name keeps compiling (with a deprecation warning); prefer
// FullBodyRecordingTraits.
using FullBodyPicoRecordingTraits [[deprecated("renamed to core::FullBodyRecordingTraits")]] = FullBodyRecordingTraits;

struct PedalRecordingTraits
{
    static constexpr std::string_view schema_name = "core.Generic3AxisPedalOutputRecord";
    static constexpr std::array recording_channels = { "pedals", "pedals_tracked" };
    static constexpr std::array replay_channels = { "pedals_tracked" };
};

struct OgloRecordingTraits
{
    static constexpr std::string_view schema_name = "core.OgloGloveSampleRecord";
    static constexpr std::array recording_channels = { "oglo", "oglo_tracked" };
    static constexpr std::array replay_channels = { "oglo_tracked" };
};

struct JointStateRecordingTraits
{
    static constexpr std::string_view schema_name = "core.JointStateOutputRecord";
    static constexpr std::array recording_channels = { "joint_state", "joint_state_tracked" };
    static constexpr std::array replay_channels = { "joint_state_tracked" };
};

struct Se3TrackerRecordingTraits
{
    static constexpr std::string_view schema_name = "core.Se3TrackerPoseRecord";
    static constexpr std::array recording_channels = { "se3_tracker", "se3_tracker_tracked" };
    static constexpr std::array replay_channels = { "se3_tracker_tracked" };
};

struct OakRecordingTraits
{
    static constexpr std::string_view schema_name = "core.FrameMetadataOakRecord";
};

struct MessageChannelRecordingTraits
{
    static constexpr std::string_view schema_name = "core.MessageChannelMessagesRecord";
    static constexpr std::array channels = { "message_channel" };
};

} // namespace core
