// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstdint>
#include <string>

namespace plugins
{
namespace rebot_devarm_leader
{

//! One decoded RobStride feedback value (a type-0x11 parameter-read reply, already in SI units).
struct RobStrideSample
{
    uint8_t motor_id = 0;
    bool is_velocity = false; //!< false: position [rad] (mechPos), true: velocity [rad/s] (mechVel)
    double value = 0.0;
};

/*!
 * @brief Minimal SocketCAN client for RobStride RS-series motors (the RobStride build of the
 *        reBot DevArm), implementing the leader-arm subset of the RobStride private CAN protocol.
 *
 * RobStride motors talk classic CAN at 1 Mbps with 29-bit extended ids laid out as
 * ``comm_type[28:24] | data16[23:8] | target_id[7:0]``. Host -> motor frames carry the host id in
 * ``data16`` and the motor id in ``target_id``; replies swap them. The subset a *leader* arm
 * needs:
 *   - **stop/disable** (comm type ``0x04``) so the arm can be back-driven by hand, and
 *   - **parameter read** (comm type ``0x11``) of ``mechPos`` (``0x7019``) and ``mechVel``
 *     (``0x701A``), whose replies carry the value as little-endian IEEE f32 in payload bytes
 *     4..7 -- already radians / rad/s, with no per-model fixed-point scaling to configure.
 *
 * request_feedback() alternates between the position and velocity read per motor, so each
 * channel refreshes at half the caller's cycle rate (45 Hz at the plugin's 90 Hz loop) while
 * keeping bus load under ~20% of a 1 Mbps bus for 7 motors.
 *
 * The interface name is a SocketCAN device (e.g. ``can0``); Linux only -- constructing on any
 * other platform throws.
 */
class RobStrideBus
{
public:
    //! Open a RAW SocketCAN socket bound to @p interface (e.g. ``can0``). @p host_id is this
    //! host's id in the RobStride id scheme (replies are addressed to it; ``0xFD`` is the
    //! vendor-tools convention). Throws ``std::runtime_error`` on failure (or always, off Linux).
    explicit RobStrideBus(const std::string& interface, uint8_t host_id = 0xFD);
    ~RobStrideBus();

    RobStrideBus(const RobStrideBus&) = delete;
    RobStrideBus& operator=(const RobStrideBus&) = delete;
    RobStrideBus(RobStrideBus&&) = delete;
    RobStrideBus& operator=(RobStrideBus&&) = delete;

    //! Send the RobStride stop frame (comm type 0x04) to @p motor_id so the joint goes limp and
    //! can be moved by hand. Safe to send when the motor is already stopped.
    bool disable(uint8_t motor_id);

    //! Ask motor @p motor_id for one feedback value, alternating mechPos / mechVel reads per
    //! call. The reply arrives asynchronously; collect it with read_sample().
    bool request_feedback(uint8_t motor_id);

    //! Read the next parameter-read reply into @p out, waiting up to @p timeout_ms. Skips
    //! unrelated bus traffic (e.g. active-report feedback frames). Returns false on timeout.
    bool read_sample(RobStrideSample& out, int timeout_ms);

private:
    //! Send one extended-id frame ``comm_type | data16 | target_id`` with an 8-byte payload.
    bool send_frame(uint8_t comm_type, uint16_t data16, uint8_t target_id, const uint8_t data[8]);

    int fd_ = -1;
    uint8_t host_id_;
    bool velocity_next_[256] = { false }; // per-motor mechPos/mechVel alternation state
};

} // namespace rebot_devarm_leader
} // namespace plugins
