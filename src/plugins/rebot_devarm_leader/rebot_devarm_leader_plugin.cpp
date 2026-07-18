// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "rebot_devarm_leader_plugin.hpp"

#include "damiao_bus.hpp"
#include "robstride_bus.hpp"

#include <flatbuffers/flatbuffers.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/os_time.hpp>
#include <schema/joint_state_generated.h>

#include <array>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <fstream>
#include <iostream>
#include <numbers>
#include <sstream>
#include <string>
#include <thread>

namespace plugins
{
namespace rebot_devarm_leader
{

namespace
{

// Must agree with JointStateTracker::DEFAULT_MAX_FLATBUFFER_SIZE on the consumer side; sizes the
// fixed tensor buffer (7 named joints + velocity fit comfortably).
constexpr size_t kMaxFlatbufferSize = 4096;

// reBot DevArm DOF order (matches the reBot-DevArm_fixend URDF joint names; the gripper is the
// extra 7th Damiao motor).
constexpr std::array<const char*, kNumJoints> kJointNames = { "joint1", "joint2", "joint3", "joint4",
                                                              "joint5", "joint6", "gripper" };

// Damiao model feedback limits (pmax [rad], vmax [rad/s]) -- the 16-bit position / 12-bit
// velocity fixed-point in a feedback frame spans [-limit, limit]. Values match the vendor's
// DM_Control tables (and motorbridge's damiao catalog).
struct ModelLimits
{
    const char* model;
    double p_max;
    double v_max;
};
constexpr std::array<ModelLimits, 4> kModelLimits = {
    { { "4310", 12.5, 30.0 }, { "4310P", 12.5, 50.0 }, { "4340", 12.5, 10.0 }, { "4340P", 12.5, 10.0 } }
};

// Factory reBot DevArm layout: DM4340P on joints 1-3, DM4310 on joints 4-6 and the gripper.
constexpr std::array<const char*, kNumJoints> kDefaultModels = { "4340P", "4340P", "4340P", "4310",
                                                                 "4310",  "4310",  "4310" };

// Default CAN ids (factory-flashed): command ids 0x01..0x07, MST feedback ids 0x11..0x17.
constexpr uint16_t kDefaultMotorIdBase = 0x01;
constexpr uint16_t kDefaultFeedbackIdBase = 0x11;

// Feedback velocity/torque are 12-bit; position is 16-bit.
constexpr int kPositionBits = 16;
constexpr int kVelocityBits = 12;

// Per-cycle reply collection window. One 0xCC round for 7 motors completes in a few ms on the
// 921600-baud CDC link; 5 ms keeps the 90 Hz frame budget comfortable.
constexpr int kCollectTimeoutMs = 5;

constexpr double kSynthAmplitude = 0.6; // [rad] arm-joint motion amplitude for the synthetic signal
constexpr double kSynthPeriodFrames = 90.0; // one cycle per ~1 s at 90 Hz

// Physical gripper travel in the calibrated frame (fully closed = 0, opening negative,
// ~6.8 rad of multi-turn geared travel) plus margin. The Damiao multi-turn counter is
// volatile across power cycles: the single-turn absolute zero survives but the turn count
// does not, so a gripper whose travel exceeds one turn can wake up reading
// physical + 2*pi*k (verified on a B601-DM: physically closed gripper read +6.227 rad
// = -0.056 + 2*pi). A reading outside this window is a wrapped encoder, not a pose —
// streaming it as-is would slam the follower's gripper into a soft-limit clip at t=0.
constexpr double kGripperTravelMinRad = -7.5;
constexpr double kGripperTravelMaxRad = 0.7;
constexpr int kGripperJointIndex = kNumJoints - 1;

//! Damiao fixed-point decode: an unsigned @p bits -bit integer spanning [-limit, limit].
double uint_to_float(uint32_t value, double limit, int bits)
{
    const double span = 2.0 * limit;
    return static_cast<double>(value) * span / static_cast<double>((1u << bits) - 1) - limit;
}

//! A device path with a '/' is a serial port (Damiao dm-serial adapter); a bare name is a
//! SocketCAN interface (RobStride backend). Empty selects the synthetic backend.
bool is_robstride_path(const std::string& device_path)
{
    return !device_path.empty() && device_path.find('/') == std::string::npos;
}

//! Look up a Damiao model's feedback limits; falls back to the DM4310 values with a warning.
ModelLimits model_limits(const std::string& model)
{
    for (const auto& entry : kModelLimits)
    {
        if (model == entry.model)
        {
            return entry;
        }
    }
    std::cerr << "RebotDevarmLeaderPlugin: warning: unknown Damiao model '" << model << "'; assuming 4310 limits"
              << std::endl;
    return kModelLimits[0];
}

} // namespace

RebotDevarmLeaderPlugin::RebotDevarmLeaderPlugin(const std::string& device_path,
                                                 const std::string& collection_id,
                                                 const std::string& calibration_path)
    : device_path_(device_path),
      collection_id_(collection_id),
      session_(std::make_shared<core::OpenXRSession>(
          "RebotDevarmLeaderPlugin", core::SchemaPusher::get_required_extensions())),
      pusher_(session_->get_handles(),
              core::SchemaPusherConfig{ .collection_id = collection_id,
                                        .max_flatbuffer_size = kMaxFlatbufferSize,
                                        .tensor_identifier = "joint_state",
                                        .localized_name = "reBot DevArm Leader",
                                        .app_name = "RebotDevarmLeaderPlugin" })
{
    // Defaults: factory ids (1..7 / 0x11..0x17), factory models, no sign flip, zero offset.
    for (int i = 0; i < kNumJoints; ++i)
    {
        const ModelLimits limits = model_limits(kDefaultModels[i]);
        calibration_[i] = JointCalibration{ static_cast<uint16_t>(kDefaultMotorIdBase + i),
                                            static_cast<uint16_t>(kDefaultFeedbackIdBase + i),
                                            limits.p_max,
                                            limits.v_max,
                                            1.0,
                                            0.0 };
    }
    if (!calibration_path.empty())
    {
        load_calibration(calibration_path);
    }

    if (is_robstride_path(device_path_))
    {
        // Throws if the SocketCAN interface doesn't exist; throws unconditionally off Linux.
        rs_bus_ = std::make_unique<RobStrideBus>(device_path_);
        std::cout << "RebotDevarmLeaderPlugin: RobStride SocketCAN backend on " << device_path_ << std::endl;

        // Leader arm: stop the motors so the operator can back-drive them by hand. RobStride
        // motors keep answering parameter reads while stopped (verified on RS-series hardware).
        for (int i = 0; i < kNumJoints; ++i)
        {
            if (!rs_bus_->disable(static_cast<uint8_t>(calibration_[i].motor_id)))
            {
                std::cerr << "RebotDevarmLeaderPlugin: warning: failed to send stop to motor 0x" << std::hex
                          << calibration_[i].motor_id << std::dec << " (is " << device_path_ << " up?)" << std::endl;
            }
        }
        // Drain any stop-command replies so the first feedback cycle starts clean.
        RobStrideSample scratch;
        while (rs_bus_->read_sample(scratch, kCollectTimeoutMs))
        {
        }
    }
    else if (!device_path_.empty())
    {
        // Throws on POSIX if the port can't be opened; throws unconditionally on Windows.
        bus_ = std::make_unique<DamiaoBus>(device_path_);
        std::cout << "RebotDevarmLeaderPlugin: Damiao dm-serial backend on " << device_path_ << std::endl;

        // Leader arm: disable torque so the operator can back-drive it by hand. Damiao motors
        // keep replying to feedback requests while disabled (verified on the B601-DM hardware).
        for (int i = 0; i < kNumJoints; ++i)
        {
            if (!bus_->disable(calibration_[i].motor_id))
            {
                std::cerr << "RebotDevarmLeaderPlugin: warning: failed to send disable to motor 0x" << std::hex
                          << calibration_[i].motor_id << std::dec << " (is the adapter connected?)" << std::endl;
            }
        }
        // Drain the disable-command status replies so the first feedback cycle starts clean.
        CanFrame scratch;
        while (bus_->read_frame(scratch, kCollectTimeoutMs))
        {
        }
    }
    else
    {
        std::cout << "RebotDevarmLeaderPlugin: using synthetic joint backend (no device path)" << std::endl;
    }
}

RebotDevarmLeaderPlugin::~RebotDevarmLeaderPlugin() = default;

void RebotDevarmLeaderPlugin::load_calibration(const std::string& path)
{
    std::ifstream file(path);
    if (!file)
    {
        std::cerr << "RebotDevarmLeaderPlugin: warning: cannot open calibration file '" << path << "'; using defaults"
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
        int motor_id = 0;
        int feedback_id = 0;
        std::string model;
        double sign = 1.0;
        double offset_rad = 0.0;
        if (!(iss >> name >> motor_id >> feedback_id >> model >> sign >> offset_rad))
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
            std::cerr << "RebotDevarmLeaderPlugin: warning: unknown joint '" << name << "' at " << path << ":"
                      << line_no << std::endl;
            continue;
        }
        // The RobStride backend reads exact f32 values, so the model column only selects
        // fixed-point limits on the Damiao backend; rs-* names keep the (unused) defaults.
        const bool is_robstride_model = model.rfind("rs", 0) == 0 || model.rfind("RS", 0) == 0;
        const ModelLimits limits = is_robstride_model ?
                                       ModelLimits{ model.c_str(), calibration_[idx].p_max, calibration_[idx].v_max } :
                                       model_limits(model);
        calibration_[idx] = JointCalibration{ static_cast<uint16_t>(motor_id),
                                              static_cast<uint16_t>(feedback_id),
                                              limits.p_max,
                                              limits.v_max,
                                              (sign < 0.0 ? -1.0 : 1.0),
                                              offset_rad };
    }
}

void RebotDevarmLeaderPlugin::read_synthetic()
{
    // Smooth, phase-shifted trajectory so the full device -> tracker -> retargeter path can run
    // with no hardware.
    const double phase = 2.0 * std::numbers::pi * static_cast<double>(frame_) / kSynthPeriodFrames;
    const double omega = 2.0 * std::numbers::pi / (kSynthPeriodFrames / 90.0); // [rad/s] at 90 Hz
    for (int i = 0; i < kNumJoints - 1; ++i)
    {
        positions_[i] = kSynthAmplitude * std::sin(phase + 0.5 * static_cast<double>(i));
        velocities_[i] = kSynthAmplitude * omega * std::cos(phase + 0.5 * static_cast<double>(i));
    }
    // Gripper: normalized open/close oscillation in [0, 1].
    positions_[kNumJoints - 1] = 0.5 * (1.0 + std::sin(phase));
    velocities_[kNumJoints - 1] = 0.5 * omega * std::cos(phase);
}

void RebotDevarmLeaderPlugin::read_hardware()
{
    // Request one feedback frame per motor (command 0xCC via id 0x7FF), then collect the replies
    // that arrive on each motor's MST id. A motor that doesn't reply this cycle holds its last
    // value so a transient bus hiccup never faults.
    for (int i = 0; i < kNumJoints; ++i)
    {
        bus_->request_feedback(calibration_[i].motor_id);
    }

    int replies = 0;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(kCollectTimeoutMs);
    CanFrame frame;
    while (replies < kNumJoints && std::chrono::steady_clock::now() < deadline)
    {
        if (!bus_->read_frame(frame, 1))
        {
            continue;
        }
        for (int i = 0; i < kNumJoints; ++i)
        {
            if (frame.arbitration_id != calibration_[i].feedback_id || frame.dlc < 8)
            {
                continue;
            }
            // Feedback payload: [status<<4 | id_low, pos_hi, pos_lo, vel_hi, vel_lo<<4 | torq_hi,
            // torq_lo, t_mos, t_rotor]; pos is 16-bit and vel 12-bit over the model limits.
            const uint32_t pos_u = (static_cast<uint32_t>(frame.data[1]) << 8) | frame.data[2];
            const uint32_t vel_u = (static_cast<uint32_t>(frame.data[3]) << 4) | (frame.data[4] >> 4);
            const double raw_pos = uint_to_float(pos_u, calibration_[i].p_max, kPositionBits);
            const double raw_vel = uint_to_float(vel_u, calibration_[i].v_max, kVelocityBits);
            positions_[i] = calibration_[i].sign * (raw_pos - calibration_[i].offset_rad);
            velocities_[i] = calibration_[i].sign * raw_vel;
            ++replies;
            break;
        }
    }

    check_gripper_travel();
}

void RebotDevarmLeaderPlugin::read_hardware_robstride()
{
    // Request one parameter read per motor (alternating mechPos / mechVel inside the bus), then
    // collect the exact-f32 replies. A motor that doesn't reply this cycle holds its last value
    // so a transient bus hiccup never faults.
    for (int i = 0; i < kNumJoints; ++i)
    {
        rs_bus_->request_feedback(static_cast<uint8_t>(calibration_[i].motor_id));
    }

    int replies = 0;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(kCollectTimeoutMs);
    RobStrideSample sample;
    while (replies < kNumJoints && std::chrono::steady_clock::now() < deadline)
    {
        if (!rs_bus_->read_sample(sample, 1))
        {
            continue;
        }
        for (int i = 0; i < kNumJoints; ++i)
        {
            if (sample.motor_id != calibration_[i].motor_id)
            {
                continue;
            }
            if (sample.is_velocity)
            {
                velocities_[i] = calibration_[i].sign * sample.value;
            }
            else
            {
                positions_[i] = calibration_[i].sign * (sample.value - calibration_[i].offset_rad);
            }
            ++replies;
            break;
        }
    }

    check_gripper_travel();
}

void RebotDevarmLeaderPlugin::check_gripper_travel()
{
    // Wrapped multi-turn gripper detection (see kGripperTravelMinRad). Latch the flag on a
    // rising edge only, so the warning prints once instead of at 90 Hz.
    const double gripper_pos = positions_[kGripperJointIndex];
    const bool out_of_travel = gripper_pos < kGripperTravelMinRad || gripper_pos > kGripperTravelMaxRad;
    if (out_of_travel && !gripper_out_of_travel_)
    {
        std::cerr << "RebotDevarmLeaderPlugin: warning: gripper reads " << gripper_pos
                  << " rad, outside its physical travel [" << kGripperTravelMinRad << ", " << kGripperTravelMaxRad
                  << "]. The multi-turn encoder most likely wrapped by 2*pi "
                  << "after a power cycle; the gripper joint is streamed as invalid until it reads "
                  << "in-travel again. Re-home the gripper (close against the stop and re-zero)." << std::endl;
    }
    gripper_out_of_travel_ = out_of_travel;
}

void RebotDevarmLeaderPlugin::push_current_state()
{
    core::JointStateOutputT out;
    out.device_id = collection_id_;
    out.has_velocity = true;
    out.has_effort = false;
    out.ee_pose_valid = false;
    for (size_t i = 0; i < kJointNames.size(); ++i)
    {
        auto joint = std::make_shared<core::JointStateT>();
        joint->name = kJointNames[i];
        joint->position = static_cast<float>(positions_[i]);
        joint->velocity = static_cast<float>(velocities_[i]);
        // A 2*pi-wrapped multi-turn gripper reading is not a pose: mark it invalid so
        // consumers (retargeters, lerobot leaders) can hold/ignore it instead of
        // commanding a follower through its soft-limit clip.
        joint->valid = !(static_cast<int>(i) == kGripperJointIndex && gripper_out_of_travel_);
        out.joints.push_back(std::move(joint));
    }

    const auto sample_time_ns = core::os_monotonic_now_ns();

    flatbuffers::FlatBufferBuilder builder(kMaxFlatbufferSize);
    auto offset = core::JointStateOutput::Pack(builder, &out);
    builder.Finish(offset);
    pusher_.push_buffer(builder.GetBufferPointer(), builder.GetSize(), sample_time_ns, sample_time_ns);
}

void RebotDevarmLeaderPlugin::update()
{
    if (bus_)
    {
        read_hardware();
    }
    else if (rs_bus_)
    {
        read_hardware_robstride();
    }
    else
    {
        read_synthetic();
    }
    push_current_state();
    ++frame_;
}

int run_probe(const std::string& device_path, const std::string& calibration_path, int seconds)
{
    if (device_path.empty())
    {
        std::cerr << "probe: a device is required: a serial path (e.g. /dev/ttyACM0, Damiao) or a "
                     "SocketCAN interface name (e.g. can0, RobStride)"
                  << std::endl;
        return 2;
    }

    // Mirror the plugin's defaults / calibration handling without an OpenXR session.
    struct ProbeJoint
    {
        uint16_t motor_id;
        uint16_t feedback_id;
        double p_max;
        double sign;
        double offset_rad;
        bool seen;
        double pos;
    };
    std::array<ProbeJoint, kNumJoints> joints;
    for (int i = 0; i < kNumJoints; ++i)
    {
        const ModelLimits limits = model_limits(kDefaultModels[i]);
        joints[i] = ProbeJoint{ static_cast<uint16_t>(kDefaultMotorIdBase + i),
                                static_cast<uint16_t>(kDefaultFeedbackIdBase + i),
                                limits.p_max,
                                1.0,
                                0.0,
                                false,
                                0.0 };
    }
    if (!calibration_path.empty())
    {
        // Reuse the plugin's parser via a throwaway file re-read to keep one format. Plain
        // duplication here would drift; instead parse with the same rules inline.
        std::ifstream file(calibration_path);
        std::string line;
        while (std::getline(file, line))
        {
            if (const auto hash = line.find('#'); hash != std::string::npos)
            {
                line.erase(hash);
            }
            std::istringstream iss(line);
            std::string name, model;
            int motor_id = 0, feedback_id = 0;
            double sign = 1.0, offset_rad = 0.0;
            if (!(iss >> name >> motor_id >> feedback_id >> model >> sign >> offset_rad))
            {
                continue;
            }
            for (int i = 0; i < kNumJoints; ++i)
            {
                if (name == kJointNames[i])
                {
                    joints[i].motor_id = static_cast<uint16_t>(motor_id);
                    joints[i].feedback_id = static_cast<uint16_t>(feedback_id);
                    joints[i].p_max = model_limits(model).p_max;
                    joints[i].sign = sign < 0.0 ? -1.0 : 1.0;
                    joints[i].offset_rad = offset_rad;
                    break;
                }
            }
        }
    }

    // Per-cycle status line, shared by both backends.
    const auto print_cycle = [&joints](int cycle)
    {
        if (cycle % 10 != 0)
        {
            return;
        }
        std::cout << "probe:";
        for (int i = 0; i < kNumJoints; ++i)
        {
            std::cout << "  " << kJointNames[i] << "=";
            if (joints[i].seen)
            {
                std::cout << joints[i].pos;
            }
            else
            {
                std::cout << "---";
            }
        }
        std::cout << std::endl;
    };

    const auto t_end = std::chrono::steady_clock::now() + std::chrono::seconds(seconds);
    if (is_robstride_path(device_path))
    {
        RobStrideBus bus(device_path);
        for (const auto& j : joints)
        {
            bus.disable(static_cast<uint8_t>(j.motor_id)); // back-drive; RS motors answer reads while stopped
        }
        RobStrideSample scratch;
        while (bus.read_sample(scratch, kCollectTimeoutMs))
        {
        }

        int cycle = 0;
        while (std::chrono::steady_clock::now() < t_end)
        {
            for (const auto& j : joints)
            {
                bus.request_feedback(static_cast<uint8_t>(j.motor_id));
            }
            const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(kCollectTimeoutMs);
            RobStrideSample sample;
            while (std::chrono::steady_clock::now() < deadline)
            {
                if (!bus.read_sample(sample, 1))
                {
                    continue;
                }
                for (auto& j : joints)
                {
                    if (sample.motor_id == j.motor_id && !sample.is_velocity)
                    {
                        j.pos = j.sign * (sample.value - j.offset_rad);
                        j.seen = true;
                        break;
                    }
                }
            }
            print_cycle(cycle);
            ++cycle;
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
    }
    else
    {
        DamiaoBus bus(device_path);
        for (const auto& j : joints)
        {
            bus.disable(j.motor_id); // back-drive mode; Damiao motors reply to 0xCC while disabled
        }
        CanFrame scratch;
        while (bus.read_frame(scratch, kCollectTimeoutMs))
        {
        }

        int cycle = 0;
        while (std::chrono::steady_clock::now() < t_end)
        {
            for (const auto& j : joints)
            {
                bus.request_feedback(j.motor_id);
            }
            const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(kCollectTimeoutMs);
            CanFrame frame;
            while (std::chrono::steady_clock::now() < deadline)
            {
                if (!bus.read_frame(frame, 1))
                {
                    continue;
                }
                for (auto& j : joints)
                {
                    if (frame.arbitration_id == j.feedback_id && frame.dlc >= 8)
                    {
                        const uint32_t pos_u = (static_cast<uint32_t>(frame.data[1]) << 8) | frame.data[2];
                        j.pos = j.sign * (uint_to_float(pos_u, j.p_max, kPositionBits) - j.offset_rad);
                        j.seen = true;
                        break;
                    }
                }
            }
            print_cycle(cycle);
            ++cycle;
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
    }

    bool all_ok = true;
    for (int i = 0; i < kNumJoints; ++i)
    {
        if (!joints[i].seen)
        {
            all_ok = false;
            std::cerr << "probe: no feedback from motor 0x" << std::hex << joints[i].motor_id << std::dec << " ("
                      << kJointNames[i] << ")" << std::endl;
        }
    }
    if (!all_ok)
    {
        std::cout << "probe: some motors missing" << std::endl;
        return 1;
    }

    // Sanity-check the gripper against its physical travel: a reading outside the window
    // means the multi-turn encoder wrapped by 2*pi after a power cycle (turn count is
    // volatile; only the single-turn zero survives). Teleoperating in this state slams the
    // follower gripper at t=0 and grinds the mechanism into its stop.
    const ProbeJoint& gripper = joints[kGripperJointIndex];
    if (gripper.pos < kGripperTravelMinRad || gripper.pos > kGripperTravelMaxRad)
    {
        std::cerr << "probe: WARNING: gripper reads " << gripper.pos << " rad, outside its physical travel ["
                  << kGripperTravelMinRad << ", " << kGripperTravelMaxRad
                  << "]: the multi-turn encoder wrapped after a power cycle. Re-home the gripper "
                  << "(close against the stop and re-zero) before teleoperating." << std::endl;
        std::cout << "probe: all motors replied (gripper out of travel)" << std::endl;
        return 3;
    }

    std::cout << "probe: all motors replied" << std::endl;
    return 0;
}

} // namespace rebot_devarm_leader
} // namespace plugins
