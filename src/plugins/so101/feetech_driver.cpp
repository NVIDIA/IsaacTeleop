// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "feetech_driver.hpp"

#include <sys/select.h>

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <termios.h>
#include <unistd.h>

namespace plugins
{
namespace so101
{

namespace
{

// Feetech protocol constants
constexpr uint8_t kHeader0 = 0xFF;
constexpr uint8_t kHeader1 = 0xFF;
constexpr uint8_t kInstRead = 0x02;

// STS3215 register addresses
constexpr uint8_t kRegPresentPosition = 56;
constexpr uint8_t kRegPresentPositionLen = 2;

// Packet size constants
constexpr size_t kReadPacketLen = 8; // 0xFF 0xFF ID LEN INST ADDR LEN CHK
constexpr size_t kStatusPacketLen = 8; // 0xFF 0xFF ID LEN ERR DATA_L DATA_H CHK
constexpr size_t kMaxStatusPacketLen = 16; // generous upper bound for recv

// Timeout for reading response (microseconds)
constexpr int kRecvTimeoutUs = 5000; // 5ms — plenty for 1Mbaud single-servo read

/*!
 * @brief Map a standard baudrate to the corresponding termios speed constant.
 */
speed_t baudrate_to_speed(int baudrate)
{
    switch (baudrate)
    {
    case 9600:
        return B9600;
    case 19200:
        return B19200;
    case 38400:
        return B38400;
    case 57600:
        return B57600;
    case 115200:
        return B115200;
    case 230400:
        return B230400;
    case 460800:
        return B460800;
    case 500000:
        return B500000;
    case 576000:
        return B576000;
    case 921600:
        return B921600;
    case 1000000:
        return B1000000;
    case 1152000:
        return B1152000;
    case 1500000:
        return B1500000;
    case 2000000:
        return B2000000;
    default:
        return B0; // unsupported
    }
}

} // namespace

FeetechDriver::FeetechDriver() = default;

FeetechDriver::~FeetechDriver()
{
    if (fd_ >= 0)
    {
        close();
    }
}

bool FeetechDriver::open(const std::string& port, int baudrate)
{
    if (fd_ >= 0)
    {
        close();
    }

    speed_t speed = baudrate_to_speed(baudrate);
    if (speed == B0)
    {
        std::cerr << "FeetechDriver: Unsupported baudrate " << baudrate << std::endl;
        return false;
    }

    int fd = ::open(port.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (fd < 0)
    {
        std::cerr << "FeetechDriver: Failed to open " << port << ": " << strerror(errno) << std::endl;
        return false;
    }

    // Configure serial port: raw mode, 8N1, no flow control
    struct termios tty;
    memset(&tty, 0, sizeof(tty));

    if (tcgetattr(fd, &tty) != 0)
    {
        std::cerr << "FeetechDriver: tcgetattr failed: " << strerror(errno) << std::endl;
        ::close(fd);
        return false;
    }

    // Input flags: no parity check, no software flow control, no special handling
    tty.c_iflag &= ~(IGNBRK | BRKINT | PARMRK | ISTRIP | INLCR | IGNCR | ICRNL | IXON | IXOFF | IXANY);

    // Output flags: no output processing
    tty.c_oflag &= ~OPOST;

    // Control flags: 8-bit chars, no parity, 1 stop bit, enable receiver, local mode
    tty.c_cflag &= ~(CSIZE | PARENB | CSTOPB | CRTSCTS);
    tty.c_cflag |= CS8 | CREAD | CLOCAL;

    // Local flags: raw input, no echo, no signals
    tty.c_lflag &= ~(ECHO | ECHONL | ICANON | ISIG | IEXTEN);

    // Non-blocking read: return immediately with whatever is available
    tty.c_cc[VMIN] = 0;
    tty.c_cc[VTIME] = 0;

    // Set baudrate
    cfsetispeed(&tty, speed);
    cfsetospeed(&tty, speed);

    if (tcsetattr(fd, TCSANOW, &tty) != 0)
    {
        std::cerr << "FeetechDriver: tcsetattr failed: " << strerror(errno) << std::endl;
        ::close(fd);
        return false;
    }

    // Flush any stale data
    tcflush(fd, TCIOFLUSH);

    fd_ = fd;
    std::cout << "FeetechDriver: Opened " << port << " at " << baudrate << " baud" << std::endl;
    return true;
}

void FeetechDriver::close()
{
    if (fd_ >= 0)
    {
        ::close(fd_);
        fd_ = -1;
    }
}

bool FeetechDriver::is_open() const
{
    return fd_ >= 0;
}

int FeetechDriver::read_position(uint8_t id)
{
    if (fd_ < 0)
    {
        return -1;
    }

    // Flush any stale data before sending a new request
    flush_input();

    // Send READ instruction for Present Position register
    // Parameters: start_address (56), data_length (2)
    uint8_t params[2] = { kRegPresentPosition, kRegPresentPositionLen };
    if (!send_packet(id, kInstRead, params, sizeof(params)))
    {
        return -1;
    }

    // Receive status packet
    // Expected: [0xFF, 0xFF, ID, 0x04, ERROR, POS_L, POS_H, CHECKSUM]
    uint8_t buf[kMaxStatusPacketLen];
    size_t len = 0;
    if (!recv_packet(buf, sizeof(buf), len))
    {
        return -1;
    }

    // Validate: minimum length for a 2-byte data response
    // Packet: [0xFF, 0xFF, ID, LEN, ERR, DATA_L, DATA_H, CHK] = 8 bytes
    if (len < kStatusPacketLen)
    {
        return -1;
    }

    // Check that the response ID matches
    if (buf[2] != id)
    {
        return -1;
    }

    // Check error byte
    uint8_t error = buf[4];
    if (error != 0)
    {
        std::cerr << "FeetechDriver: Servo " << static_cast<int>(id) << " error: 0x" << std::hex
                  << static_cast<int>(error) << std::dec << std::endl;
        return -1;
    }

    // Extract position: 2 bytes little-endian at buf[5] and buf[6]
    int position = static_cast<int>(buf[5]) | (static_cast<int>(buf[6]) << 8);

    // Sanity check range
    if (position < 0 || position > 4095)
    {
        return -1;
    }

    return position;
}

bool FeetechDriver::read_all_positions(int positions[6])
{
    for (uint8_t i = 0; i < 6; ++i)
    {
        int pos = read_position(i + 1); // Servo IDs are 1-based
        if (pos < 0)
        {
            return false;
        }
        positions[i] = pos;
    }
    return true;
}

bool FeetechDriver::send_packet(uint8_t id, uint8_t instruction, const uint8_t* params, size_t param_len)
{
    // Packet format: [0xFF, 0xFF, ID, LENGTH, INSTRUCTION, PARAM..., CHECKSUM]
    // Feetech/Dynamixel Protocol v1: LENGTH = Number of Parameters + 2
    // (the "+2" counts the Instruction byte and Checksum byte).
    uint8_t length = static_cast<uint8_t>(param_len + 2);
    // Total packet size: header(2) + id(1) + length(1) + instruction(1) + params(N) + checksum(1)
    size_t packet_len = 6 + param_len;

    uint8_t packet[16]; // max packet we ever send is small
    if (packet_len > sizeof(packet))
    {
        return false;
    }

    packet[0] = kHeader0;
    packet[1] = kHeader1;
    packet[2] = id;
    packet[3] = length;
    packet[4] = instruction;
    for (size_t i = 0; i < param_len; ++i)
    {
        packet[5 + i] = params[i];
    }

    // Checksum is computed over: ID, Length, Instruction, Params
    // checksum_data starts at packet[2], length = 1(id) + 1(length) + 1(instruction) + param_len
    packet[5 + param_len] = checksum(&packet[2], 1 + 1 + 1 + param_len);

    ssize_t written = write(fd_, packet, packet_len);
    if (written != static_cast<ssize_t>(packet_len))
    {
        return false;
    }

    // On half-duplex, we may read back our own transmitted bytes.
    // Drain the echo by reading back exactly packet_len bytes.
    // Use a short timeout so we don't block forever if there's no echo.
    uint8_t echo_buf[16];
    size_t echo_read = 0;
    fd_set read_fds;
    struct timeval tv;

    while (echo_read < packet_len)
    {
        FD_ZERO(&read_fds);
        FD_SET(fd_, &read_fds);
        tv.tv_sec = 0;
        tv.tv_usec = kRecvTimeoutUs;

        int ret = select(fd_ + 1, &read_fds, nullptr, nullptr, &tv);
        if (ret <= 0)
        {
            break; // timeout or error — no echo (full-duplex adapter)
        }

        ssize_t n = read(fd_, echo_buf + echo_read, packet_len - echo_read);
        if (n <= 0)
        {
            break;
        }
        echo_read += static_cast<size_t>(n);
    }

    return true;
}

bool FeetechDriver::recv_packet(uint8_t* data, size_t max_len, size_t& out_len)
{
    out_len = 0;
    if (max_len < 6)
    {
        return false; // minimum valid packet: header(2) + id(1) + len(1) + err(1) + chk(1)
    }

    // Wait for data with timeout
    fd_set read_fds;
    struct timeval tv;
    size_t total_read = 0;

    // Phase 1: Read the header bytes (find 0xFF 0xFF)
    auto read_bytes = [&](size_t count) -> bool
    {
        while (total_read < count)
        {
            FD_ZERO(&read_fds);
            FD_SET(fd_, &read_fds);
            tv.tv_sec = 0;
            tv.tv_usec = kRecvTimeoutUs;

            int ret = select(fd_ + 1, &read_fds, nullptr, nullptr, &tv);
            if (ret <= 0)
            {
                return false;
            }

            ssize_t n = read(fd_, data + total_read, count - total_read);
            if (n <= 0)
            {
                return false;
            }
            total_read += static_cast<size_t>(n);
        }
        return true;
    };

    // Scan for the header 0xFF 0xFF
    int sync_attempts = 0;
    constexpr int kMaxSyncAttempts = 32;

    while (sync_attempts < kMaxSyncAttempts)
    {
        total_read = 0;
        if (!read_bytes(1))
        {
            return false;
        }
        if (data[0] != kHeader0)
        {
            sync_attempts++;
            continue;
        }

        total_read = 1;
        if (!read_bytes(2))
        {
            return false;
        }
        if (data[1] == kHeader1)
        {
            break; // found header
        }
        sync_attempts++;
    }

    if (sync_attempts >= kMaxSyncAttempts)
    {
        return false;
    }

    // Read ID and Length (bytes 2 and 3)
    if (!read_bytes(4))
    {
        return false;
    }

    uint8_t pkt_length = data[3]; // number of bytes following length field (instruction/error + params + checksum)
    if (pkt_length < 2 || pkt_length > 250)
    {
        return false; // sanity check
    }

    size_t total_packet_len = 4 + pkt_length; // header(2) + id(1) + length(1) + pkt_length
    if (total_packet_len > max_len)
    {
        return false;
    }

    // Read the rest of the packet
    if (!read_bytes(total_packet_len))
    {
        return false;
    }

    // Verify checksum: computed over bytes [2] through [total_packet_len - 2]
    // (ID, Length, Error/Instruction, Params)
    size_t chk_data_len = total_packet_len - 3; // everything from ID to the byte before checksum
    uint8_t expected_chk = checksum(&data[2], chk_data_len);
    uint8_t received_chk = data[total_packet_len - 1];

    if (expected_chk != received_chk)
    {
        std::cerr << "FeetechDriver: Checksum mismatch (expected 0x" << std::hex << static_cast<int>(expected_chk)
                  << ", got 0x" << static_cast<int>(received_chk) << std::dec << ")" << std::endl;
        return false;
    }

    out_len = total_packet_len;
    return true;
}

uint8_t FeetechDriver::checksum(const uint8_t* data, size_t len)
{
    // Feetech/Dynamixel v1 checksum: ~(sum of bytes) & 0xFF
    uint8_t sum = 0;
    for (size_t i = 0; i < len; ++i)
    {
        sum += data[i];
    }
    return ~sum;
}

void FeetechDriver::flush_input()
{
    if (fd_ < 0)
    {
        return;
    }
    tcflush(fd_, TCIFLUSH);
}

} // namespace so101
} // namespace plugins
