// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <mcap/recording_traits.hpp>
#include <mcap/tracker_channels.hpp>
#include <mcap/writer.hpp>
#include <schema/controller_generated.h>
#include <schema/full_body_generated.h>
#include <schema/hand_generated.h>
#include <schema/head_generated.h>
#include <schema/pedals_generated.h>
#include <schema/timestamp_generated.h>

#include <cstdint>
#include <exception>
#include <filesystem>
#include <iostream>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace
{

using ControllerChannels = core::McapTrackerChannels<core::ControllerSnapshotRecord, core::ControllerSnapshot>;
using HandChannels = core::McapTrackerChannels<core::HandPoseRecord, core::HandPose>;
using HeadChannels = core::McapTrackerChannels<core::HeadPoseRecord, core::HeadPose>;
using PedalChannels = core::McapTrackerChannels<core::Generic3AxisPedalOutputRecord, core::Generic3AxisPedalOutput>;
using FullBodyChannels = core::McapTrackerChannels<core::FullBodyPosePicoRecord, core::FullBodyPosePico>;

constexpr int kDefaultFrameCount = 1800;
constexpr int64_t kFramePeriodNs = 16'666'667;

// Per-frame position drift (meters) applied to every sample source so replayed
// poses vary over time instead of staying static; the fixture only needs
// valid/finite/changing values, so the exact magnitude is arbitrary.
constexpr float kDriftRatePerFrameM = 0.0005f;

// Plausible standing-pose heights (meters) that give the sample poses physical meaning.
constexpr float kHeadHeightM = 1.60f;
constexpr float kControllerGripHeightM = 1.10f;
constexpr float kControllerAimHeightM = 1.20f;
constexpr float kFullBodyBaseHeightM = 0.80f;

// Identity orientation shared by every sample pose.
core::Quaternion identity_quaternion()
{
    return core::Quaternion(0.0f, 0.0f, 0.0f, 1.0f);
}

std::vector<std::string> to_strings(auto channels)
{
    std::vector<std::string> result;
    result.reserve(channels.size());
    for (std::string_view channel : channels)
    {
        result.emplace_back(channel);
    }
    return result;
}

std::shared_ptr<core::ControllerSnapshotT> make_controller_sample(bool left, int frame)
{
    const float side = left ? -1.0f : 1.0f;
    const float delta = kDriftRatePerFrameM * static_cast<float>(frame);
    auto sample = std::make_shared<core::ControllerSnapshotT>();
    sample->grip_pose = std::make_shared<core::ControllerPose>(
        core::Pose(core::Point(0.15f * side, 0.10f + delta, kControllerGripHeightM), identity_quaternion()), true);
    sample->aim_pose = std::make_shared<core::ControllerPose>(
        core::Pose(core::Point(0.20f * side, 0.15f + delta, kControllerAimHeightM), identity_quaternion()), true);
    sample->inputs = std::make_shared<core::ControllerInputState>(
        true, !left, false, left, 0.25f * side, left ? 0.40f : -0.40f, 0.55f, 0.70f);
    return sample;
}

std::shared_ptr<core::HandPoseT> make_hand_sample(bool left, int frame)
{
    const float side = left ? -1.0f : 1.0f;
    const float delta = kDriftRatePerFrameM * static_cast<float>(frame);
    auto sample = std::make_shared<core::HandPoseT>();
    sample->joints = std::make_unique<core::HandJoints>();
    for (int joint = 0; joint < core::HandJoint_NUM_JOINTS; ++joint)
    {
        // Per-joint offsets fan the joints out into a plausible-looking hand layout.
        const float joint_f = static_cast<float>(joint);
        const float x = 0.05f * side + 0.003f * side * joint_f;
        const float y = 0.03f + 0.006f * joint_f + delta;
        const float z = 1.00f + 0.004f * joint_f;
        const core::Point position(x, y, z);
        const core::Pose pose(position, identity_quaternion());
        sample->joints->mutable_poses()->Mutate(joint, core::HandJointPose(pose, true, 0.010f));
    }
    return sample;
}

std::shared_ptr<core::HeadPoseT> make_head_sample(int frame)
{
    // Deterministic, slowly drifting head pose at standing height.
    const float delta = kDriftRatePerFrameM * static_cast<float>(frame);
    auto sample = std::make_shared<core::HeadPoseT>();
    sample->pose = std::make_shared<core::Pose>(core::Point(0.0f, 0.10f + delta, kHeadHeightM), identity_quaternion());
    sample->is_valid = true;
    return sample;
}

std::shared_ptr<core::Generic3AxisPedalOutputT> make_pedal_sample(int frame)
{
    auto sample = std::make_shared<core::Generic3AxisPedalOutputT>();
    sample->left_pedal = 0.20f;
    sample->right_pedal = 0.80f;
    sample->rudder = (frame % 2 == 0) ? 0.15f : -0.15f;
    return sample;
}

std::shared_ptr<core::FullBodyPosePicoT> make_full_body_sample(int frame)
{
    const float delta = kDriftRatePerFrameM * static_cast<float>(frame);
    auto sample = std::make_shared<core::FullBodyPosePicoT>();
    sample->joints = std::make_unique<core::BodyJointsPico>();
    for (int joint = 0; joint < core::BodyJointPico_NUM_JOINTS; ++joint)
    {
        // Per-joint offsets spread the joints into a plausible-looking body layout.
        const float joint_f = static_cast<float>(joint);
        const float x = 0.01f * joint_f;
        const float y = -0.02f + 0.002f * joint_f + delta;
        const float z = kFullBodyBaseHeightM + 0.01f * joint_f;
        const core::Point position(x, y, z);
        const core::Pose pose(position, identity_quaternion());
        sample->joints->mutable_joints()->Mutate(joint, core::BodyJointPose(pose, true));
    }
    return sample;
}

std::unique_ptr<mcap::McapWriter> open_writer(const std::filesystem::path& path)
{
    if (path.has_parent_path())
    {
        std::filesystem::create_directories(path.parent_path());
    }

    auto writer = std::make_unique<mcap::McapWriter>();
    mcap::McapWriterOptions options("teleop-ros2-integration-test");
    options.compression = mcap::Compression::None;
    const auto status = writer->open(path.string(), options);
    if (!status.ok())
    {
        throw std::runtime_error("failed to open MCAP writer for " + path.string() + ": " + status.message);
    }
    return writer;
}

void write_fixture(const std::filesystem::path& output_path, int frame_count)
{
    auto writer = open_writer(output_path);
    const auto controller_names = to_strings(core::ControllerRecordingTraits::recording_channels);
    const auto hand_names = to_strings(core::HandRecordingTraits::recording_channels);
    const auto head_names = to_strings(core::HeadRecordingTraits::recording_channels);
    const auto pedal_names = to_strings(core::PedalRecordingTraits::recording_channels);
    const auto full_body_names = to_strings(core::FullBodyRecordingTraits::recording_channels);

    ControllerChannels controller_channels(
        *writer, "controllers", core::ControllerRecordingTraits::schema_name, controller_names);
    HandChannels hand_channels(*writer, "hands", core::HandRecordingTraits::schema_name, hand_names);
    HeadChannels head_channels(*writer, "head", core::HeadRecordingTraits::schema_name, head_names);
    PedalChannels pedal_channels(*writer, "pedals", core::PedalRecordingTraits::schema_name, pedal_names);
    FullBodyChannels full_body_channels(
        *writer, "full_body", core::FullBodyRecordingTraits::schema_name, full_body_names);

    for (int frame = 0; frame < frame_count; ++frame)
    {
        const int64_t time_ns = static_cast<int64_t>(frame + 1) * kFramePeriodNs;
        const core::DeviceDataTimestamp timestamp(time_ns, time_ns, time_ns);
        controller_channels.write(0, timestamp, make_controller_sample(true, frame));
        controller_channels.write(1, timestamp, make_controller_sample(false, frame));
        hand_channels.write(0, timestamp, make_hand_sample(true, frame));
        hand_channels.write(1, timestamp, make_hand_sample(false, frame));
        head_channels.write(0, timestamp, make_head_sample(frame));
        pedal_channels.write(0, timestamp, make_pedal_sample(frame));
        full_body_channels.write(0, timestamp, make_full_body_sample(frame));
    }

    writer->close();
}

int parse_frame_count(const char* value)
{
    const int frame_count = std::stoi(value);
    if (frame_count <= 0)
    {
        throw std::invalid_argument("frame count must be positive");
    }
    return frame_count;
}

} // namespace

int main(int argc, char** argv)
try
{
    if (argc < 2 || argc > 3)
    {
        std::cerr << "Usage: " << argv[0] << " <output.mcap> [frame_count]\n";
        return 2;
    }

    const std::filesystem::path output_path(argv[1]);
    const int frame_count = argc == 3 ? parse_frame_count(argv[2]) : kDefaultFrameCount;
    write_fixture(output_path, frame_count);
    std::cout << "Wrote " << frame_count << " teleop ROS 2 replay frames to " << output_path << "\n";
    return 0;
}
catch (const std::exception& e)
{
    std::cerr << argv[0] << ": " << e.what() << "\n";
    return 1;
}
catch (...)
{
    std::cerr << argv[0] << ": Unknown error occurred\n";
    return 1;
}
