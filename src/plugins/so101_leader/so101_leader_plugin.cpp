// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "so101_leader_plugin.hpp"

#include "feetech_bus.hpp"

#include <flatbuffers/flatbuffers.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/os_time.hpp>
#include <schema/joint_state_generated.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cctype>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <numbers>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

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
    // Defaults: servo ids 1..6 in DOF order, no sign flip, centered at the servo midpoint (2048),
    // full tick range (so the clamp is a no-op until a calibration file narrows it).
    for (int i = 0; i < kNumJoints; ++i)
    {
        calibration_[i] = JointCalibration{ static_cast<uint8_t>(i + 1), 1.0, 2048, 0, 4095 };
    }
    if (!calibration_path.empty())
    {
        load_calibration(calibration_path);
    }

    // Servo id list (DOF order) and reusable scratch for the per-frame sync read.
    for (int i = 0; i < kNumJoints; ++i)
    {
        servo_ids_.push_back(calibration_[i].servo_id);
    }
    read_ticks_.assign(kNumJoints, 0);
    read_ok_.assign(kNumJoints, 0);

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

        // A LeRobot calibration's homing offsets live in the servo EEPROM; reconcile now that the
        // bus is up so our reads land in the same frame LeRobot uses.
        compensate_homing();
    }
    else
    {
        std::cout << "So101LeaderPlugin: using synthetic joint backend (no device path)" << std::endl;
    }
}

So101LeaderPlugin::~So101LeaderPlugin() = default;

void So101LeaderPlugin::load_calibration(const std::string& path)
{
    if (path.ends_with(".json"))
    {
        load_lerobot_calibration(path);
        return;
    }

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

        // Optional range_min range_max columns (from the calibrate sweep); else full range.
        int range_min = 0;
        int range_max = 4095;
        if (int a = 0, b = 0; (iss >> a >> b) && a >= 0 && b <= 4095 && a < b)
        {
            range_min = a;
            range_max = b;
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
        calibration_[idx] = JointCalibration{ static_cast<uint8_t>(servo_id), (sign < 0.0 ? -1.0 : 1.0), home_ticks,
                                              range_min, range_max };
    }
}

void So101LeaderPlugin::load_lerobot_calibration(const std::string& path)
{
    std::ifstream file(path);
    if (!file)
    {
        std::cerr << "So101LeaderPlugin: warning: cannot open LeRobot calibration '" << path << "'; using defaults"
                  << std::endl;
        return;
    }
    std::stringstream buffer;
    buffer << file.rdbuf();
    const auto motors = parse_lerobot_calibration(buffer.str());
    if (motors.empty())
    {
        std::cerr << "So101LeaderPlugin: warning: could not parse LeRobot calibration '" << path << "'; using defaults"
                  << std::endl;
        return;
    }

    lerobot_homing_.assign(kNumJoints, 0);
    for (const auto& [name, fields] : motors)
    {
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
            std::cerr << "So101LeaderPlugin: warning: unknown joint '" << name << "' in " << path << std::endl;
            continue;
        }

        const auto get = [&fields](const char* key, long fallback) -> long
        {
            const auto it = fields.find(key);
            return it != fields.end() ? it->second : fallback;
        };
        const int servo_id = static_cast<int>(get("id", idx + 1));
        const bool inverted = get("drive_mode", 0) != 0;
        const int range_min = static_cast<int>(get("range_min", 0));
        const int range_max = static_cast<int>(get("range_max", 4095));
        // LeRobot's zero is the range midpoint (its DEGREES normalization centers on it); homing_offset
        // lives in the servo and is reconciled in compensate_homing().
        const int home = (range_min + range_max) / 2;
        calibration_[idx] =
            JointCalibration{ static_cast<uint8_t>(servo_id), inverted ? -1.0 : 1.0, home, range_min, range_max };
        lerobot_homing_[idx] = static_cast<int>(get("homing_offset", 0));
    }
}

void So101LeaderPlugin::compensate_homing()
{
    if (lerobot_homing_.empty() || !bus_)
    {
        return; // no LeRobot calibration loaded, or no live bus to read the servo offset
    }
    for (int i = 0; i < kNumJoints; ++i)
    {
        int servo_offset = 0;
        if (!bus_->read_homing_offset(calibration_[i].servo_id, servo_offset))
        {
            std::cerr << "So101LeaderPlugin: warning: could not read Homing_Offset of servo "
                      << static_cast<int>(calibration_[i].servo_id) << "; assuming it matches the calibration file"
                      << std::endl;
            continue;
        }
        // File offsets are in the servo's homed frame; shift into this servo's current frame.
        const int delta = lerobot_homing_[i] - servo_offset;
        calibration_[i].home_ticks += delta;
        calibration_[i].range_min += delta;
        calibration_[i].range_max += delta;
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
    // One SYNC READ for all six servos (a single bus round-trip) instead of six request/response
    // pairs -- lower latency. Convert ticks -> radians with per-joint calibration; a servo that
    // doesn't reply holds its last value so a transient bus hiccup never faults.
    if (!bus_->sync_read_positions(servo_ids_, read_ticks_, read_ok_))
    {
        return; // request could not be sent; hold all
    }
    for (int i = 0; i < kNumJoints; ++i)
    {
        if (read_ok_[i])
        {
            const int ticks =
                std::clamp(static_cast<int>(read_ticks_[i]), calibration_[i].range_min, calibration_[i].range_max);
            positions_[i] = calibration_[i].sign * (ticks - calibration_[i].home_ticks) * kTicksToRadians;
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

namespace
{

//! Read the servos a few times and return the per-joint averaged tick (or 2048 if a servo never
//! replied). @p ok_out[i] reflects whether servo @p ids[i] replied at least once.
std::vector<int> averaged_positions(FeetechBus& bus, const std::vector<uint8_t>& ids, int samples, std::vector<bool>& ok_out)
{
    std::vector<long> sums(ids.size(), 0);
    std::vector<int> counts(ids.size(), 0);
    for (int s = 0; s < samples; ++s)
    {
        std::vector<uint16_t> ticks;
        std::vector<uint8_t> ok;
        if (bus.sync_read_positions(ids, ticks, ok))
        {
            for (size_t i = 0; i < ids.size(); ++i)
            {
                if (ok[i])
                {
                    sums[i] += ticks[i];
                    ++counts[i];
                }
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }

    std::vector<int> out(ids.size(), 2048);
    ok_out.assign(ids.size(), false);
    for (size_t i = 0; i < ids.size(); ++i)
    {
        if (counts[i] > 0)
        {
            out[i] = static_cast<int>((sums[i] + counts[i] / 2) / counts[i]);
            ok_out[i] = true;
        }
    }
    return out;
}

} // namespace

int run_calibration(const std::string& device_path, const std::string& output_path)
{
    if (device_path.empty())
    {
        std::cerr << "calibrate: a serial device path is required (e.g. /dev/ttyACM0)" << std::endl;
        return 2;
    }

    FeetechBus bus(device_path, kFeetechBaud);

    // Default bus ids 1..6 in DOF order; back-drive the arm by disabling torque.
    std::vector<uint8_t> ids;
    for (int i = 0; i < kNumJoints; ++i)
    {
        ids.push_back(static_cast<uint8_t>(i + 1));
        bus.disable_torque(ids.back());
    }

    // Step 1: home (zero) capture. Holding the middle of the range matches LeRobot's homing step
    // and, for the SO-101, the URDF/operating zero convention used by EE-mode forward kinematics.
    std::cout << "Step 1/2: move all joints to the MIDDLE of their range of motion, then press ENTER..." << std::flush;
    std::string line;
    std::getline(std::cin, line);
    std::vector<bool> home_ok;
    const std::vector<int> home = averaged_positions(bus, ids, 8, home_ok);

    // Step 2: range-of-motion sweep -- track per-joint min/max while the operator moves the arm,
    // until ENTER is pressed (mirrors LeRobot's record_ranges_of_motion). Seed with home so the
    // range always contains the zero pose.
    std::vector<int> range_min = home;
    std::vector<int> range_max = home;
    std::cout << "Step 2/2: move EVERY joint through its full range of motion, then press ENTER to finish..."
              << std::endl;
    std::atomic<bool> stop{ false };
    std::thread waiter(
        [&stop]()
        {
            std::string l;
            std::getline(std::cin, l);
            stop.store(true);
        });
    while (!stop.load())
    {
        std::vector<uint16_t> ticks;
        std::vector<uint8_t> ok;
        if (bus.sync_read_positions(ids, ticks, ok))
        {
            for (int i = 0; i < kNumJoints; ++i)
            {
                if (ok[i])
                {
                    range_min[i] = std::min(range_min[i], static_cast<int>(ticks[i]));
                    range_max[i] = std::max(range_max[i], static_cast<int>(ticks[i]));
                }
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    waiter.join();

    bool all_ok = true;
    std::cout << "\nMeasured calibration (ticks; angle = sign * (ticks - home) * 2pi/4096):" << std::endl;
    for (int i = 0; i < kNumJoints; ++i)
    {
        if (!home_ok[i])
        {
            all_ok = false;
            std::cerr << "  warning: no reply from servo " << static_cast<int>(ids[i]) << " (" << kJointNames[i]
                      << "); writing defaults" << std::endl;
        }
        std::cout << "  " << kJointNames[i] << "  id=" << static_cast<int>(ids[i]) << "  home=" << home[i]
                  << "  range=[" << range_min[i] << ", " << range_max[i] << "]" << std::endl;
    }

    // Gripper endpoints in radians (relative to home) for the retargeter's gripper_open/gripper_close.
    const int g = kNumJoints - 1;
    const double grip_lo = (range_min[g] - home[g]) * kTicksToRadians;
    const double grip_hi = (range_max[g] - home[g]) * kTicksToRadians;
    std::cout << "\nGripper '" << kJointNames[g] << "' range endpoints (radians, relative to home): " << grip_lo
              << " .. " << grip_hi << "\n  -> set JointStateRetargeterConfig.gripper_open / gripper_close to these "
              << "(whichever matches your open/closed convention)." << std::endl;

    if (!output_path.empty())
    {
        std::ofstream out(output_path);
        if (!out)
        {
            std::cerr << "calibrate: cannot write '" << output_path << "'" << std::endl;
            return 2;
        }
        if (output_path.ends_with(".json"))
        {
            // LeRobot calibration JSON. drive_mode 0 (the leader sweep keeps sign +1); homing_offset
            // is read back from the servo so re-applying this file is a no-op and the recorded ranges
            // stay in the servo's current frame.
            out << "{\n";
            for (int i = 0; i < kNumJoints; ++i)
            {
                int homing = 0;
                bus.read_homing_offset(ids[i], homing);
                out << "    \"" << kJointNames[i] << "\": {\n";
                out << "        \"id\": " << static_cast<int>(ids[i]) << ",\n";
                out << "        \"drive_mode\": 0,\n";
                out << "        \"homing_offset\": " << homing << ",\n";
                out << "        \"range_min\": " << range_min[i] << ",\n";
                out << "        \"range_max\": " << range_max[i] << "\n";
                out << "    }" << (i + 1 < kNumJoints ? "," : "") << "\n";
            }
            out << "}\n";
        }
        else
        {
            out << "# SO-101 leader calibration (generated by `so101_leader_plugin calibrate`)\n";
            out << "# name           id  sign  home_ticks  range_min  range_max\n";
            for (int i = 0; i < kNumJoints; ++i)
            {
                out << kJointNames[i] << " " << static_cast<int>(ids[i]) << " 1 " << home[i] << " " << range_min[i]
                    << " " << range_max[i] << "\n";
            }
        }
        std::cout << "Wrote " << (output_path.ends_with(".json") ? "LeRobot " : "") << "calibration to " << output_path
                  << std::endl;
    }
    std::cout << "Set 'sign' to -1 for any joint that moves opposite the URDF convention." << std::endl;
    return all_ok ? 0 : 1;
}

std::map<std::string, std::map<std::string, long>> parse_lerobot_calibration(const std::string& json)
{
    std::map<std::string, std::map<std::string, long>> result;
    size_t i = 0;
    const size_t n = json.size();

    const auto skip_ws = [&]()
    {
        while (i < n && std::isspace(static_cast<unsigned char>(json[i])))
        {
            ++i;
        }
    };
    const auto parse_string = [&](std::string& out) -> bool
    {
        skip_ws();
        if (i >= n || json[i] != '"')
        {
            return false;
        }
        ++i;
        out.clear();
        while (i < n && json[i] != '"')
        {
            if (json[i] == '\\' && i + 1 < n)
            {
                ++i; // take the escaped character literally (keys/fields here have no escapes)
            }
            out.push_back(json[i++]);
        }
        if (i >= n)
        {
            return false;
        }
        ++i; // closing quote
        return true;
    };
    const auto consume = [&](char c) -> bool
    {
        skip_ws();
        if (i < n && json[i] == c)
        {
            ++i;
            return true;
        }
        return false;
    };

    if (!consume('{'))
    {
        return result;
    }
    skip_ws();
    if (i < n && json[i] == '}')
    {
        return result; // empty object
    }

    while (i < n)
    {
        std::string motor;
        if (!parse_string(motor) || !consume(':') || !consume('{'))
        {
            result.clear();
            return result;
        }

        std::map<std::string, long> fields;
        skip_ws();
        if (i < n && json[i] == '}')
        {
            ++i; // empty motor object
        }
        else
        {
            while (i < n)
            {
                std::string key;
                if (!parse_string(key) || !consume(':'))
                {
                    result.clear();
                    return result;
                }
                skip_ws();
                const size_t start = i;
                if (i < n && (json[i] == '-' || json[i] == '+'))
                {
                    ++i;
                }
                bool is_int = false;
                while (i < n && std::isdigit(static_cast<unsigned char>(json[i])))
                {
                    ++i;
                    is_int = true;
                }
                if (is_int && (i >= n || (json[i] != '.' && json[i] != 'e' && json[i] != 'E')))
                {
                    fields[key] = std::strtol(json.c_str() + start, nullptr, 10);
                }
                else
                {
                    // Non-integer value (float / string / bool / null): skip it shallowly.
                    i = start;
                    if (i < n && json[i] == '"')
                    {
                        std::string tmp;
                        parse_string(tmp);
                    }
                    else
                    {
                        while (i < n && json[i] != ',' && json[i] != '}')
                        {
                            ++i;
                        }
                    }
                }
                skip_ws();
                if (i < n && json[i] == ',')
                {
                    ++i;
                    continue;
                }
                if (i < n && json[i] == '}')
                {
                    ++i;
                    break;
                }
                result.clear();
                return result;
            }
        }

        result[motor] = std::move(fields);
        skip_ws();
        if (i < n && json[i] == ',')
        {
            ++i;
            continue;
        }
        if (i < n && json[i] == '}')
        {
            ++i;
            break;
        }
        break;
    }
    return result;
}

} // namespace so101_leader
} // namespace plugins
