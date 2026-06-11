// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <pusherio/schema_pusher.hpp>

#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace core
{
class OpenXRSession;
}

namespace plugins
{
namespace so101_leader
{

class FeetechBus;

//! Number of SO-101 DOFs: 5-DOF arm + gripper.
inline constexpr int kNumJoints = 6;

/*!
 * @brief Streams SO-101 (5-DOF + gripper) leader-arm joint angles as ``JointStateOutput`` via
 *        OpenXR ``SchemaPusher``, on the generic joint-space device path.
 *
 * The SO-101 reads 6 FEETECH STS3215 bus servos over a serial port. When a serial @p device_path
 * is given, the plugin talks to the servos directly via :class:`FeetechBus` (the same SMS/STS wire
 * protocol LeRobot's ``FeetechMotorsBus`` uses): it disables torque so the arm can be back-driven
 * and reads ``Present_Position`` each frame, converting ticks to radians with per-joint calibration.
 * With no device path it falls back to a **synthetic** trajectory so the device -> tracker ->
 * retargeter pipeline can run with no hardware (used by CI and the headless example).
 */
class So101LeaderPlugin
{
public:
    /*!
     * @param device_path Serial device path (e.g. /dev/ttyACM0) for the real FEETECH backend.
     *        Empty selects the synthetic backend.
     * @param collection_id Tensor collection id; must match the consumer's JointStateTracker.
     *        Also used as the JointStateOutput.device_id.
     * @param calibration_path Optional calibration file (see load_calibration()); empty uses
     *        defaults (servo ids 1..6 in DOF order, sign +1, home tick 2048).
     */
    So101LeaderPlugin(const std::string& device_path,
                      const std::string& collection_id,
                      const std::string& calibration_path = "");
    ~So101LeaderPlugin();

    void update();

private:
    //! Per-joint mapping from a FEETECH servo to a joint angle, mirroring LeRobot's calibration:
    //! ``angle [rad] = sign * (clamp(ticks, range_min, range_max) - home_ticks) * 2*pi / 4096``.
    struct JointCalibration
    {
        uint8_t servo_id;
        double sign; // +1 / -1 (LeRobot drive_mode)
        int home_ticks; // raw tick at the joint's zero pose (LeRobot homing reference); 2048 = servo center
        int range_min; // sweep min tick; reads are clamped to [range_min, range_max]
        int range_max; // sweep max tick; default full range 0..4095 => clamp is a no-op
    };

    //! Fill positions_ from the live servos (held last on a failed read). SEAM for other backends.
    void read_hardware();
    //! Synthetic smooth trajectory used when no serial device is attached.
    void read_synthetic();
    void push_current_state();
    //! Load calibration from @p path. A ``.json`` file is read as a LeRobot calibration (see
    //! load_lerobot_calibration()); anything else is the plain-text format: ``name servo_id sign
    //! home_ticks [range_min range_max]`` per line (``#`` comments allowed; range columns optional).
    //! Unknown joint names are ignored; missing joints keep defaults.
    void load_calibration(const std::string& path);
    //! Load a LeRobot calibration JSON. Maps ``range_min/range_max`` -> range, the range midpoint ->
    //! ``home_ticks`` (LeRobot's zero), and ``drive_mode`` -> ``sign``. The per-joint
    //! ``homing_offset`` is reconciled against the servo by compensate_homing().
    void load_lerobot_calibration(const std::string& path);
    //! Reconcile a loaded LeRobot calibration with the live servos: LeRobot's offsets live in the
    //! servo EEPROM, so shift home/range by ``homing_offset_file - homing_offset_servo`` (read live).
    //! No-op without a LeRobot calibration or a connected bus.
    void compensate_homing();

    std::string device_path_;
    std::string collection_id_;
    int64_t frame_ = 0;
    double positions_[kNumJoints] = { 0.0, 0.0, 0.0, 0.0, 0.0, 0.0 };
    JointCalibration calibration_[kNumJoints];

    std::unique_ptr<FeetechBus> bus_; // null => synthetic backend
    std::vector<uint8_t> servo_ids_; // calibration_[*].servo_id in DOF order (sync-read request)
    std::vector<uint16_t> read_ticks_; // sync-read scratch (reused each frame)
    std::vector<uint8_t> read_ok_; // sync-read scratch: per-servo reply flag
    std::vector<int> lerobot_homing_; // per-DOF homing_offset from a loaded LeRobot JSON (else empty)

    std::shared_ptr<core::OpenXRSession> session_;
    core::SchemaPusher pusher_;
};

//! Calibration/dump helper: open @p device_path, back-drive-enable the servos, then (1) capture the
//! home tick with the arm held at the middle of its range, and (2) record each joint's min/max over
//! a range-of-motion sweep (move the arm, press ENTER to finish). Prints the result and -- if
//! @p output_path is non-empty -- writes a calibration file in the format ``load_calibration()``
//! consumes (``name id sign home_ticks range_min range_max``). Also prints the gripper open/close
//! endpoints in radians for the retargeter. Does not create an OpenXR session. Returns a process
//! exit code (0 = all servos read).
int run_calibration(const std::string& device_path, const std::string& output_path);

//! Minimal reader for a LeRobot calibration JSON of the shape ``{ "joint": {"id": int,
//! "drive_mode": int, "homing_offset": int, "range_min": int, "range_max": int}, ... }``. Returns
//! ``joint -> {field -> integer}`` (non-integer values skipped). Not a general JSON parser; returns
//! an empty map on malformed input.
std::map<std::string, std::map<std::string, long>> parse_lerobot_calibration(const std::string& json);

} // namespace so101_leader
} // namespace plugins
