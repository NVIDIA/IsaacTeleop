// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace plugins
{
namespace so101_leader
{

/*!
 * @brief Minimal half-duplex serial client for FEETECH SMS/STS bus servos (e.g. the STS3215 used
 *        by the SO-101 / SO-ARM100).
 *
 * Implements the same wire protocol as the FEETECH SCServo SDK / LeRobot's ``FeetechMotorsBus``,
 * but only the subset a *leader* arm needs:
 *   - read ``Present_Position`` (register 56, 2 bytes, little-endian for the SMS/STS series), and
 *   - disable torque (register 40) so the arm can be back-driven by hand.
 *
 * Wire format (Dynamixel-like): ``FF FF ID LEN INST PARAM... CHK``, with
 * ``LEN = param_count + 2`` and ``CHK = ~(ID + LEN + INST + PARAMS) & 0xFF``. Default bus speed is
 * 1,000,000 bps, 8N1 (the STS factory default). Assumes an auto-direction USB-TTL adapter
 * (e.g. FE-URT-1 / Waveshare bus-servo adapter) that does not echo transmitted bytes.
 *
 * POSIX only (Linux/macOS); constructing on Windows throws.
 */
class FeetechBus
{
public:
    //! Open and configure @p port (e.g. ``/dev/ttyACM0``) at @p baud. Throws ``std::runtime_error``
    //! on failure (or always, on Windows).
    explicit FeetechBus(const std::string& port, int baud = 1000000);
    ~FeetechBus();

    FeetechBus(const FeetechBus&) = delete;
    FeetechBus& operator=(const FeetechBus&) = delete;
    FeetechBus(FeetechBus&&) = delete;
    FeetechBus& operator=(FeetechBus&&) = delete;

    //! Read ``Present_Position`` [ticks, 0..4095 over 360 deg] for servo @p id. Returns false on
    //! timeout / malformed response so the caller can hold the last value instead of faulting.
    bool read_position(uint8_t id, uint16_t& ticks_out);

    //! Read ``Present_Position`` for all @p ids in a single SYNC READ (one bus round-trip instead
    //! of one request/response per servo -- the low-latency path). @p positions and @p ok are
    //! resized to ``ids.size()`` and filled in parallel; ``ok[i] == 0`` means servo ``ids[i]`` did
    //! not reply (its position is left 0 and the caller should hold its last value). Returns false
    //! only if the request itself could not be sent.
    bool sync_read_positions(const std::vector<uint8_t>& ids, std::vector<uint16_t>& positions, std::vector<uint8_t>& ok);

    //! Write ``Torque_Enable = 0`` (register 40) so servo @p id goes limp and can be moved by hand.
    bool disable_torque(uint8_t id);

private:
    bool write_packet(uint8_t id, uint8_t instruction, const uint8_t* params, uint8_t param_count);
    //! Read one status packet; copies @p expected_data_len data bytes (after the error byte) into
    //! @p data_out (may be null when @p expected_data_len is 0), validates header/length/checksum,
    //! and reports the responder id in @p id_out.
    bool read_status_any(uint8_t* data_out, uint8_t expected_data_len, uint8_t& id_out);
    //! As read_status_any(), but also requires the responder id to equal @p expected_id.
    bool read_status(uint8_t expected_id, uint8_t* data_out, uint8_t expected_data_len);
    bool read_byte(uint8_t& out, int timeout_ms);

    int fd_ = -1;
};

} // namespace so101_leader
} // namespace plugins
