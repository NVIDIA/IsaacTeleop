// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "so101_leader_plugin.hpp"

#include "feetech_bus.hpp"

#include <flatbuffers/flatbuffers.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/os_time.hpp>
#include <schema/joint_state_generated.h>

#include <array>
#include <cmath>
#include <cstddef>
#include <fstream>
#include <iostream>
#include <memory>
#include <numbers>
#include <sstream>
#include <string>

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
constexpr std::array<const char*, kNumJoints> kJointNames = { "shoulder_pan", "shoulder_lift", "elbow_flex",
                                                              "wrist_flex",   "wrist_roll",    "gripper" };

// FEETECH STS3215: 12-bit magnetic encoder, 4096 ticks per 360 deg.
constexpr double kTicksToRadians = 2.0 * std::numbers::pi / 4096.0;
constexpr int kFeetechBaud = 1000000; // STS factory default

constexpr double kSynthAmplitude = 0.6; // [rad] arm-joint motion amplitude for the synthetic signal
constexpr double kSynthPeriodFrames = 90.0; // one cycle per ~1 s at 90 Hz

} // namespace

So101LeaderPlugin::So101LeaderPlugin(const std::string& device_path,
                                     const std::string& collection_id,
                                     const std::string& calibration_path)
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
    // Defaults: servo ids 1..6 in DOF order, no sign flip, centered at the servo midpoint (2048).
    for (int i = 0; i < kNumJoints; ++i)
    {
        calibration_[i] = JointCalibration{ static_cast<uint8_t>(i + 1), 1.0, 2048 };
    }
    if (!calibration_path.empty())
    {
        load_calibration(calibration_path);
    }

    if (!device_path_.empty())
    {
        // Throws on POSIX if the port can't be opened; throws unconditionally on Windows.
        bus_ = std::make_unique<FeetechBus>(device_path_, kFeetechBaud);
        std::cout << "So101LeaderPlugin: FEETECH serial backend on " << device_path_ << std::endl;

        // Leader arm: disable torque so the operator can back-drive it by hand.
        for (int i = 0; i < kNumJoints; ++i)
        {
            if (!bus_->disable_torque(calibration_[i].servo_id))
            {
                std::cerr << "So101LeaderPlugin: warning: failed to disable torque on servo "
                          << static_cast<int>(calibration_[i].servo_id) << " (is it powered / on the bus?)" << std::endl;
            }
        }
    }
    else
    {
        std::cout << "So101LeaderPlugin: using synthetic joint backend (no device path)" << std::endl;
    }
}

So101LeaderPlugin::~So101LeaderPlugin() = default;

void So101LeaderPlugin::load_calibration(const std::string& path)
{
    std::ifstream file(path);
    if (!file)
    {
        std::cerr << "So101LeaderPlugin: warning: cannot open calibration file '" << path << "'; using defaults"
                  << std::endl;
        return;
    }

    std::string line;
    int line_no = 0;
    while (std::getline(file, line))
    {
        ++line_no;
        if (const auto hash = line.find('#'); hash != std::string::npos)
        {
            line.erase(hash);
        }

        std::istringstream iss(line);
        std::string name;
        int servo_id = 0;
        double sign = 1.0;
        int home_ticks = 2048;
        if (!(iss >> name >> servo_id >> sign >> home_ticks))
        {
            continue; // blank / comment-only / malformed line
        }

        int idx = -1;
        for (int i = 0; i < kNumJoints; ++i)
        {
            if (name == kJointNames[i])
            {
                idx = i;
                break;
            }
        }
        if (idx < 0)
        {
            std::cerr << "So101LeaderPlugin: warning: unknown joint '" << name << "' at " << path << ":" << line_no
                      << std::endl;
            continue;
        }
        calibration_[idx] = JointCalibration{ static_cast<uint8_t>(servo_id), (sign < 0.0 ? -1.0 : 1.0), home_ticks };
    }
}

void So101LeaderPlugin::read_synthetic()
{
    // Smooth, phase-shifted trajectory so the full device -> tracker -> retargeter path can run
    // with no hardware.
    const double phase = 2.0 * std::numbers::pi * static_cast<double>(frame_) / kSynthPeriodFrames;
    for (int i = 0; i < kNumJoints - 1; ++i)
    {
        positions_[i] = kSynthAmplitude * std::sin(phase + 0.5 * static_cast<double>(i));
    }
    // Gripper: normalized open/close oscillation in [0, 1].
    positions_[kNumJoints - 1] = 0.5 * (1.0 + std::sin(phase));
}

void So101LeaderPlugin::read_hardware()
{
    // Read the 6 FEETECH STS3215 bus servos and convert ticks -> radians with per-joint
    // calibration. A failed read holds the last value so a transient bus hiccup never faults.
    for (int i = 0; i < kNumJoints; ++i)
    {
        uint16_t ticks = 0;
        if (bus_->read_position(calibration_[i].servo_id, ticks))
        {
            positions_[i] =
                calibration_[i].sign * (static_cast<int>(ticks) - calibration_[i].home_ticks) * kTicksToRadians;
        }
    }
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
    if (bus_)
    {
        read_hardware();
    }
    else
    {
        read_synthetic();
    }
    push_current_state();
    ++frame_;
}

} // namespace so101_leader
} // namespace plugins
