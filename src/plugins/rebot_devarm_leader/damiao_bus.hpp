// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstdint>
#include <string>

namespace plugins
{
namespace rebot_devarm_leader
{

//! One CAN frame as carried over the Damiao USB-CDC serial adapter (classic CAN, DLC <= 8).
struct CanFrame
{
    uint32_t arbitration_id = 0;
    uint8_t data[8] = { 0 };
    uint8_t dlc = 0;
};

/*!
 * @brief Minimal serial client for the Damiao USB-to-CAN adapter (dm-serial) driving DM-series
 *        MIT-protocol motors (e.g. the DM4340P/DM4310 in the Seeed reBot DevArm).
 *
 * Implements the adapter's USB-CDC framing and the subset of the Damiao motor CAN protocol a
 * *leader* arm needs:
 *   - request a feedback frame (command ``0xCC`` addressed via arbitration id ``0x7FF``), and
 *   - disable torque (control frame ``FF .. FF FD``) so the arm can be back-driven by hand.
 *
 * Wire format (adapter, both directions are fixed-size binary frames):
 *   - TX (30 bytes): ``55 AA 1E 03 | sendTimes(u32 LE)=1 | timeInterval(u32 LE)=10 | idType(u8)
 *     | canId(u32 LE) | frameType(u8)=0 | dlc(u8) | idAcc(u8)=0 | dataAcc(u8)=0 | data[8] | crc(u8)=0``
 *   - RX (16 bytes): ``AA 11 | flags(u8: dlc & 0x3F, ext 0x40, rtr 0x80) | canId(u32 LE) | data[8] | 55``
 *
 * Feedback frames arrive on the motor's **MST (feedback) id** with the payload
 * ``[status<<4 | canId_low, pos_hi, pos_lo, vel_hi, vel_lo<<4 | torq_hi, torq_lo, t_mos, t_rotor]``
 * where position is 16-bit and velocity/torque are 12-bit fixed-point over the model's limits.
 *
 * POSIX only (Linux/macOS); constructing on Windows throws.
 */
class DamiaoBus
{
public:
    //! Open and configure @p port (e.g. ``/dev/ttyACM0``) at @p baud. Throws ``std::runtime_error``
    //! on failure (or always, on Windows).
    explicit DamiaoBus(const std::string& port, int baud = 921600);
    ~DamiaoBus();

    DamiaoBus(const DamiaoBus&) = delete;
    DamiaoBus& operator=(const DamiaoBus&) = delete;
    DamiaoBus(DamiaoBus&&) = delete;
    DamiaoBus& operator=(DamiaoBus&&) = delete;

    //! Send one classic CAN frame through the adapter. Returns false on a short/failed write.
    bool send_frame(uint32_t arbitration_id, const uint8_t data[8], uint8_t dlc = 8);

    //! Ask motor @p motor_id for one feedback frame (Damiao command ``0xCC`` via id ``0x7FF``).
    //! The reply arrives asynchronously on the motor's MST id; collect it with read_frame().
    bool request_feedback(uint16_t motor_id);

    //! Send the Damiao disable control frame (``FF .. FF FD``) to @p motor_id so the joint goes
    //! limp and can be moved by hand. Safe to send when the motor is already disabled.
    bool disable(uint16_t motor_id);

    //! Read the next CAN frame from the adapter into @p out, waiting up to @p timeout_ms.
    //! Returns false on timeout (no frame available).
    bool read_frame(CanFrame& out, int timeout_ms);

private:
    //! Pull whatever bytes the adapter has ready into rx_buf_ (select()-bounded by @p timeout_ms).
    bool fill_rx_buffer(int timeout_ms);
    //! Try to parse one 16-byte adapter frame from rx_buf_; consumes garbage bytes on resync.
    bool parse_frame(CanFrame& out);

    int fd_ = -1;
    // Reassembly buffer for the fixed 16-byte RX frames (USB CDC reads can split them).
    uint8_t rx_buf_[512];
    int rx_len_ = 0;
};

} // namespace rebot_devarm_leader
} // namespace plugins
