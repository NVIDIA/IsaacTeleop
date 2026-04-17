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
    static constexpr std::array channels = { "head" };
};

struct HandRecordingTraits
{
    static constexpr std::string_view schema_name = "core.HandPoseRecord";
    static constexpr std::array channels = { "left_hand", "right_hand" };
};

struct ControllerRecordingTraits
{
    static constexpr std::string_view schema_name = "core.ControllerSnapshotRecord";
    static constexpr std::array channels = { "left_controller", "right_controller" };
};

struct FullBodyPicoRecordingTraits
{
    static constexpr std::string_view schema_name = "core.FullBodyPosePicoRecord";
    static constexpr std::array channels = { "full_body" };
};

struct PedalRecordingTraits
{
    static constexpr std::string_view schema_name = "core.Generic3AxisPedalOutputRecord";
    static constexpr std::array channels = { "pedals", "pedals_tracked" };
};

struct OakRecordingTraits
{
    static constexpr std::string_view schema_name = "core.FrameMetadataOakRecord";
};

} // namespace core
