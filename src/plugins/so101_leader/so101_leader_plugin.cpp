// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "so101_leader_plugin.hpp"

#include <flatbuffers/flatbuffers.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/os_time.hpp>
#include <schema/joint_state_generated.h>

#include <array>
#include <cmath>
#include <cstddef>
#include <iostream>
#include <memory>
#include <numbers>

namespace plugins
{
namespace so101_leader
{

namespace
{

// Must agree with JointStateTracker::DEFAULT_MAX_FLATBUFFER_SIZE on the consumer side; sizes the
// fixed tensor buffer (6 named joints + optional channels fit comfortably).
constexpr size_t kMaxFlatbufferSize = 4096;

// SO-101 DOF order (matches Simulation/SO101/so101_new_calib.urdf and the schema name keys).
constexpr std::array<const char*, 6> kJointNames = { "shoulder_pan", "shoulder_lift", "elbow_flex",
                                                     "wrist_flex",   "wrist_roll",    "gripper" };

constexpr double kSynthAmplitude = 0.6; // [rad] arm-joint motion amplitude for the synthetic signal
constexpr double kSynthPeriodFrames = 90.0; // one cycle per ~1 s at 90 Hz

} // namespace

So101LeaderPlugin::So101LeaderPlugin(const std::string& device_path, const std::string& collection_id)
    : device_path_(device_path),
      collection_id_(collection_id),
      session_(std::make_shared<core::OpenXRSession>("So101LeaderPlugin", core::SchemaPusher::get_required_extensions())),
      pusher_(session_->get_handles(),
              core::SchemaPusherConfig{ .collection_id = collection_id,
                                        .max_flatbuffer_size = kMaxFlatbufferSize,
                                        .tensor_identifier = "joint_state",
                                        .localized_name = "SO-101 Leader Arm",
                                        .app_name = "So101LeaderPlugin" })
{
    // This reference ships the synthetic backend only; the real Feetech read is a seam in
    // read_hardware(). A device_path is accepted for that future backend but ignored for now.
    if (!device_path_.empty())
    {
        std::cout << "So101LeaderPlugin: device path " << device_path_
                  << " given, but the Feetech serial backend is not yet implemented; "
                     "using synthetic data (see read_hardware())"
                  << std::endl;
    }
    else
    {
        std::cout << "So101LeaderPlugin: using synthetic joint backend" << std::endl;
    }
}

So101LeaderPlugin::~So101LeaderPlugin() = default;

void So101LeaderPlugin::read_hardware()
{
    // SEAM: real hardware read goes here.
    //
    // For the SO-101 leader this reads the 6 Feetech STS3215 bus servos over `device_path_`
    // (using LeRobot's calibration to convert ticks -> radians) into positions_, in kJointNames
    // order. Until that is wired up, synthesize a smooth, phase-shifted trajectory so the full
    // device -> tracker -> retargeter path can run with no hardware.
    const double phase = 2.0 * std::numbers::pi * static_cast<double>(frame_) / kSynthPeriodFrames;
    for (size_t i = 0; i < kJointNames.size() - 1; ++i)
    {
        positions_[i] = kSynthAmplitude * std::sin(phase + 0.5 * static_cast<double>(i));
    }
    // Gripper: normalized open/close oscillation in [0, 1].
    positions_[kJointNames.size() - 1] = 0.5 * (1.0 + std::sin(phase));
}

void So101LeaderPlugin::push_current_state()
{
    core::JointStateOutputT out;
    out.device_id = collection_id_;
    out.has_velocity = false;
    out.has_effort = false;
    out.ee_pose_valid = false;
    for (size_t i = 0; i < kJointNames.size(); ++i)
    {
        auto joint = std::make_shared<core::JointStateT>();
        joint->name = kJointNames[i];
        joint->position = static_cast<float>(positions_[i]);
        joint->valid = true;
        out.joints.push_back(std::move(joint));
    }

    const auto sample_time_ns = core::os_monotonic_now_ns();

    flatbuffers::FlatBufferBuilder builder(kMaxFlatbufferSize);
    auto offset = core::JointStateOutput::Pack(builder, &out);
    builder.Finish(offset);
    pusher_.push_buffer(builder.GetBufferPointer(), builder.GetSize(), sample_time_ns, sample_time_ns);
}

void So101LeaderPlugin::update()
{
    read_hardware();
    push_current_state();
    ++frame_;
}

} // namespace so101_leader
} // namespace plugins
