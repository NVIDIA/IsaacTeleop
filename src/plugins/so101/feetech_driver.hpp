// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace plugins
{
namespace so101
{

/*!
 * @brief Minimal Feetech STS3215 serial bus servo driver.
 *
 * Communicates with Feetech STS3215 servos over half-duplex UART.
 * Uses the Feetech instruction packet protocol:
 *   TX: [0xFF, 0xFF, ID, LENGTH, INSTRUCTION, PARAM..., CHECKSUM]
 *   RX: [0xFF, 0xFF, ID, LENGTH, ERROR, DATA..., CHECKSUM]
 *
 * Position is read from register address 56 (Present Position), 2 bytes
 * little-endian, range 0-4095 (12-bit).
 */
class FeetechDriver
{
public:
    FeetechDriver();
    ~FeetechDriver();

    // Non-copyable
    FeetechDriver(const FeetechDriver&) = delete;
    FeetechDriver& operator=(const FeetechDriver&) = delete;

    /*!
     * @brief Open the serial port and configure for Feetech communication.
     * @param port Serial port path (e.g., "/dev/ttyACM0" or "/dev/ttyUSB0").
     * @param baudrate Communication speed (default 1000000 for STS3215).
     * @return true if the port was opened and configured successfully.
     */
    bool open(const std::string& port, int baudrate = 1000000);

    /*!
     * @brief Close the serial port.
     */
    void close();

    /*!
     * @brief Check if the serial port is open.
     */
    bool is_open() const;

    /*!
     * @brief Read the current position of a single servo.
     * @param id Servo ID (1-6 for SO-101).
     * @return Raw position value 0-4095, or -1 on communication error.
     */
    int read_position(uint8_t id);

    /*!
     * @brief Read positions of all 6 SO-101 servos (IDs 1-6).
     * @param positions Output array of 6 raw position values (0-4095).
     * @return true if all 6 reads succeeded, false if any failed.
     */
    bool read_all_positions(int positions[6]);

private:
    /*!
     * @brief Send an instruction packet to a servo.
     * @param id Servo ID.
     * @param instruction Instruction byte (e.g., 0x02 for READ).
     * @param params Parameter bytes following the instruction.
     * @param param_len Number of parameter bytes.
     * @return true if the packet was sent successfully.
     */
    bool send_packet(uint8_t id, uint8_t instruction, const uint8_t* params, size_t param_len);

    /*!
     * @brief Receive a status packet from a servo.
     * @param data Output buffer for the full packet (including header).
     * @param max_len Maximum number of bytes to read.
     * @param out_len Actual number of bytes read.
     * @return true if a valid packet was received.
     */
    bool recv_packet(uint8_t* data, size_t max_len, size_t& out_len);

    /*!
     * @brief Compute the Feetech checksum for a packet.
     *
     * Checksum = ~(ID + Length + Instruction/Error + Params...) & 0xFF
     * Computed over bytes starting from ID (index 2) to the byte before checksum.
     *
     * @param data Pointer to packet data starting at the ID byte.
     * @param len Number of bytes to include in the checksum (ID through last param).
     * @return The computed checksum byte.
     */
    uint8_t checksum(const uint8_t* data, size_t len);

    /*!
     * @brief Drain any stale data from the serial receive buffer.
     */
    void flush_input();

    int fd_ = -1;
};

} // namespace so101
} // namespace plugins
