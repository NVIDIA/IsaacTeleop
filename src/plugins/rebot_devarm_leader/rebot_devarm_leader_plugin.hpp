// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <pusherio/schema_pusher.hpp>

#include <cstdint>
#include <memory>
#include <string>

namespace core
{
class OpenXRSession;
}

namespace plugins
{
namespace rebot_devarm_leader
{

class DamiaoBus;
class RobStrideBus;

//! Number of reBot DevArm DOFs: 6-DOF arm + gripper.
inline constexpr int kNumJoints = 7;

/*!
 * @brief Streams Seeed reBot DevArm (6-DOF + gripper) leader-arm joint angles as
 *        ``JointStateOutput`` via OpenXR ``SchemaPusher``, on the generic joint-space device path.
 *
 * Two motor builds of the arm are supported, selected by the shape of @p device_path:
 *
 * - **Damiao** (7 DM-series MIT-protocol motors: DM4340P on joints 1-3, DM4310 on joints 4-6
 *   and the gripper) behind a Damiao USB-to-CAN serial adapter. A path containing ``/`` (e.g.
 *   ``/dev/ttyACM0``) selects this backend (:class:`DamiaoBus`, the same dm-serial wire protocol
 *   the vendor's DM_Control / motorbridge stacks use): it sends the disable control frame so the
 *   arm can be back-driven by hand, then requests one feedback frame per motor per cycle
 *   (command ``0xCC``) and decodes position/velocity from the replies. Damiao feedback is
 *   already in SI units (fixed-point over the model's ``[-pmax, pmax]`` / ``[-vmax, vmax]``
 *   limits), so no tick conversion is needed -- only an optional per-joint sign and zero-offset
 *   from a calibration file.
 *
 * - **RobStride** (7 RS-series motors) on a SocketCAN interface. A bare interface name (e.g.
 *   ``can0``) selects this backend (:class:`RobStrideBus`): it sends the RobStride stop frame
 *   (back-drive), then alternates parameter reads of ``mechPos`` / ``mechVel`` per motor per
 *   cycle, whose replies carry exact IEEE f32 radians / rad/s -- model-independent, so the
 *   calibration file's model column is ignored on this backend.
 *
 * With no device path it falls back to a **synthetic** trajectory so the device -> tracker ->
 * retargeter pipeline can run with no hardware (used by CI and headless bring-up).
 */
class RebotDevarmLeaderPlugin
{
public:
    /*!
     * @param device_path Serial device path (e.g. /dev/ttyACM0) for the Damiao dm-serial
     *        backend, or a SocketCAN interface name (e.g. can0) for the RobStride backend.
     *        Empty selects the synthetic backend.
     * @param collection_id Tensor collection id; must match the consumer's JointStateTracker.
     *        Also used as the JointStateOutput.device_id.
     * @param calibration_path Optional calibration file (see load_calibration()); empty uses
     *        defaults (motor ids 1..7, feedback ids 0x11..0x17, sign +1, zero offset 0).
     */
    RebotDevarmLeaderPlugin(const std::string& device_path,
                            const std::string& collection_id,
                            const std::string& calibration_path = "");
    ~RebotDevarmLeaderPlugin();

    void update();

private:
    //! Per-joint mapping from a Damiao motor to a joint angle:
    //! ``angle [rad] = sign * (feedback_pos - offset_rad)`` (feedback is already in radians).
    struct JointCalibration
    {
        uint16_t motor_id; // command CAN id (ESC id)
        uint16_t feedback_id; // MST id the motor replies on
        double p_max; // model position limit [rad]; feedback pos is 16-bit over [-p_max, p_max]
        double v_max; // model velocity limit [rad/s]; feedback vel is 12-bit over [-v_max, v_max]
        double sign; // +1 / -1 if the joint moves opposite the URDF convention
        double offset_rad; // feedback position at the joint's URDF zero pose
    };

    //! Request + collect one feedback frame per motor (held last on a missed reply). SEAM for
    //! other backends.
    void read_hardware();
    //! RobStride flavor of read_hardware(): parameter-read replies instead of feedback frames.
    void read_hardware_robstride();
    //! Synthetic smooth trajectory used when no serial device is attached.
    void read_synthetic();
    //! Latch gripper_out_of_travel_ from the current gripper position (warns on a rising edge).
    void check_gripper_travel();
    void push_current_state();
    //! Load calibration from @p path: ``name motor_id feedback_id model sign offset_rad`` per
    //! line (``#`` comments allowed). Unknown joint names are ignored; missing joints keep
    //! defaults. ``model`` is a Damiao model name (4310, 4310P, 4340, 4340P) selecting the
    //! feedback fixed-point limits.
    void load_calibration(const std::string& path);

    std::string device_path_;
    std::string collection_id_;
    int64_t frame_ = 0;
    double positions_[kNumJoints] = { 0.0 };
    double velocities_[kNumJoints] = { 0.0 };
    JointCalibration calibration_[kNumJoints];
    //! True while the gripper reads outside its physical travel (2*pi-wrapped multi-turn
    //! encoder after a power cycle); the gripper joint is streamed with ``valid = false``.
    bool gripper_out_of_travel_ = false;

    // At most one backend is non-null; both null => synthetic backend.
    std::unique_ptr<DamiaoBus> bus_;
    std::unique_ptr<RobStrideBus> rs_bus_;

    std::shared_ptr<core::OpenXRSession> session_;
    core::SchemaPusher pusher_;
};

//! Hardware probe helper: open @p device_path (serial path => Damiao, SocketCAN interface name
//! => RobStride), send disable (back-drive) to the default motor ids, then stream decoded joint
//! positions to stdout for @p seconds. Verifies the bus, motor ids, and feedback decoding with
//! no OpenXR runtime. Returns a process exit code (0 = every motor replied at least once, 3 =
//! motors replied but the gripper reads outside its physical travel — 2*pi-wrapped multi-turn
//! encoder, re-home before teleoperating).
int run_probe(const std::string& device_path, const std::string& calibration_path, int seconds);

} // namespace rebot_devarm_leader
} // namespace plugins
