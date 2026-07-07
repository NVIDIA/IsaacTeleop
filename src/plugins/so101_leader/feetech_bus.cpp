// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "feetech_bus.hpp"

#include <stdexcept>
#include <string>

#ifndef _WIN32

#    include <sys/select.h>

#    include <cerrno>
#    include <cstring>
#    include <fcntl.h>
#    include <termios.h>
#    include <unistd.h>
#    include <vector>

namespace plugins
{
namespace so101_leader
{

namespace
{

// FEETECH SMS/STS protocol constants.
constexpr uint8_t kHeader = 0xFF;
constexpr uint8_t kBroadcastId = 0xFE;
constexpr uint8_t kInstRead = 0x02;
constexpr uint8_t kInstWrite = 0x03;
constexpr uint8_t kInstSyncRead = 0x82;
constexpr uint8_t kRegTorqueEnable = 40; // 1 byte
constexpr uint8_t kRegPresentPosition = 56; // 2 bytes, little-endian (SMS/STS)
constexpr uint8_t kRegHomingOffset = 31; // 2 bytes, sign-magnitude (sign bit 11) on SMS/STS
constexpr int kHomingOffsetSignBit = 11;
constexpr int kReadTimeoutMs = 20;

// Map a numeric baud rate to the matching termios speed constant. Only the rates a FEETECH bus
// realistically uses are supported; anything else throws (rather than silently mis-configuring).
speed_t to_speed(int baud)
{
    switch (baud)
    {
#    ifdef B1000000
    case 1000000:
        return B1000000;
#    endif
#    ifdef B500000
    case 500000:
        return B500000;
#    endif
    case 115200:
        return B115200;
    case 57600:
        return B57600;
    case 38400:
        return B38400;
    default:
        throw std::runtime_error("FeetechBus: unsupported baud rate " + std::to_string(baud) +
                                 " (STS servos default to 1000000)");
    }
}

} // namespace

FeetechBus::FeetechBus(const std::string& port, int baud)
{
    fd_ = ::open(port.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (fd_ < 0)
    {
        throw std::runtime_error("FeetechBus: cannot open '" + port + "': " + std::strerror(errno));
    }

    termios tty{};
    if (::tcgetattr(fd_, &tty) != 0)
    {
        const std::string msg = std::strerror(errno);
        ::close(fd_);
        fd_ = -1;
        throw std::runtime_error("FeetechBus: tcgetattr failed on '" + port + "': " + msg);
    }

    ::cfmakeraw(&tty);
    const speed_t spd = to_speed(baud);
    ::cfsetispeed(&tty, spd);
    ::cfsetospeed(&tty, spd);

    // 8N1, local, receiver enabled, no flow control. select()-driven reads (VMIN/VTIME = 0).
    tty.c_cflag |= (CLOCAL | CREAD);
    tty.c_cflag &= ~CSTOPB;
    tty.c_cflag &= ~PARENB;
    tty.c_cflag &= ~CSIZE;
    tty.c_cflag |= CS8;
#    ifdef CRTSCTS
    tty.c_cflag &= ~CRTSCTS;
#    endif
    tty.c_cc[VMIN] = 0;
    tty.c_cc[VTIME] = 0;

    if (::tcsetattr(fd_, TCSANOW, &tty) != 0)
    {
        const std::string msg = std::strerror(errno);
        ::close(fd_);
        fd_ = -1;
        throw std::runtime_error("FeetechBus: tcsetattr failed on '" + port + "': " + msg);
    }

    ::tcflush(fd_, TCIOFLUSH);
}

FeetechBus::~FeetechBus()
{
    if (fd_ >= 0)
    {
        ::close(fd_);
    }
}

bool FeetechBus::write_packet(uint8_t id, uint8_t instruction, const uint8_t* params, uint8_t param_count)
{
    const uint8_t length = static_cast<uint8_t>(param_count + 2);
    std::vector<uint8_t> pkt;
    pkt.reserve(static_cast<size_t>(param_count) + 6);
    pkt.push_back(kHeader);
    pkt.push_back(kHeader);
    pkt.push_back(id);
    pkt.push_back(length);
    pkt.push_back(instruction);

    uint32_t checksum = id + length + instruction;
    for (uint8_t i = 0; i < param_count; ++i)
    {
        pkt.push_back(params[i]);
        checksum += params[i];
    }
    pkt.push_back(static_cast<uint8_t>(~checksum & 0xFF));

    // Drop any stale/echoed bytes from a previous transaction before issuing this one.
    ::tcflush(fd_, TCIFLUSH);

    size_t written = 0;
    while (written < pkt.size())
    {
        const ssize_t n = ::write(fd_, pkt.data() + written, pkt.size() - written);
        if (n < 0)
        {
            if (errno == EAGAIN || errno == EINTR)
            {
                continue;
            }
            return false;
        }
        written += static_cast<size_t>(n);
    }
    ::tcdrain(fd_);
    return true;
}

bool FeetechBus::read_byte(uint8_t& out, int timeout_ms)
{
    fd_set rfds;
    FD_ZERO(&rfds);
    FD_SET(fd_, &rfds);
    timeval tv{};
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;

    const int ready = ::select(fd_ + 1, &rfds, nullptr, nullptr, &tv);
    if (ready <= 0)
    {
        return false; // timeout or error
    }
    const ssize_t n = ::read(fd_, &out, 1);
    return n == 1;
}

bool FeetechBus::read_status_any(uint8_t* data_out, uint8_t expected_data_len, uint8_t& id_out)
{
    // Sync to the 0xFF 0xFF header (tolerates leading noise from bus turnaround).
    int prev = -1;
    bool synced = false;
    for (int i = 0; i < 64 && !synced; ++i)
    {
        uint8_t b = 0;
        if (!read_byte(b, kReadTimeoutMs))
        {
            return false;
        }
        if (prev == kHeader && b == kHeader)
        {
            synced = true;
        }
        prev = b;
    }
    if (!synced)
    {
        return false;
    }

    uint8_t id = 0;
    uint8_t length = 0;
    if (!read_byte(id, kReadTimeoutMs) || !read_byte(length, kReadTimeoutMs))
    {
        return false;
    }
    // length = error(1) + data(length-2) + checksum(1); guard against malformed lengths.
    if (length < 2 || length > 16)
    {
        return false;
    }

    std::vector<uint8_t> rest(length); // error + data... + checksum
    for (uint8_t i = 0; i < length; ++i)
    {
        if (!read_byte(rest[i], kReadTimeoutMs))
        {
            return false;
        }
    }

    uint32_t checksum = id + length;
    for (uint8_t i = 0; i + 1 < length; ++i)
    {
        checksum += rest[i];
    }
    const uint8_t expected_checksum = static_cast<uint8_t>(~checksum & 0xFF);
    if (expected_checksum != rest[length - 1])
    {
        return false;
    }

    const uint8_t data_len = static_cast<uint8_t>(length - 2);
    if (data_len != expected_data_len)
    {
        return false;
    }
    for (uint8_t i = 0; i < expected_data_len; ++i)
    {
        data_out[i] = rest[i + 1]; // skip the error byte at rest[0]
    }
    id_out = id;
    return true;
}

bool FeetechBus::read_status(uint8_t expected_id, uint8_t* data_out, uint8_t expected_data_len)
{
    uint8_t id = 0;
    return read_status_any(data_out, expected_data_len, id) && id == expected_id;
}

bool FeetechBus::read_position(uint8_t id, uint16_t& ticks_out)
{
    const uint8_t params[2] = { kRegPresentPosition, 0x02 };
    if (!write_packet(id, kInstRead, params, 2))
    {
        return false;
    }
    uint8_t data[2] = { 0, 0 };
    if (!read_status(id, data, 2))
    {
        return false;
    }
    ticks_out = static_cast<uint16_t>(data[0]) | static_cast<uint16_t>(data[1] << 8);
    return true;
}

bool FeetechBus::sync_read_positions(const std::vector<uint8_t>& ids,
                                     std::vector<uint16_t>& positions,
                                     std::vector<uint8_t>& ok)
{
    positions.assign(ids.size(), 0);
    ok.assign(ids.size(), 0);
    if (ids.empty())
    {
        return true;
    }

    // SYNC READ (0x82) to the broadcast id: params are [reg, read_len, id0, id1, ...]. Each
    // addressed servo then replies with its own status packet in list order.
    std::vector<uint8_t> params;
    params.reserve(ids.size() + 2);
    params.push_back(kRegPresentPosition);
    params.push_back(0x02);
    params.insert(params.end(), ids.begin(), ids.end());
    if (!write_packet(kBroadcastId, kInstSyncRead, params.data(), static_cast<uint8_t>(params.size())))
    {
        return false;
    }

    // Read up to one reply per requested servo, matching by id so a non-responding servo doesn't
    // misalign the rest (the first missing reply just ends the burst).
    for (size_t k = 0; k < ids.size(); ++k)
    {
        uint8_t data[2] = { 0, 0 };
        uint8_t resp_id = 0;
        if (!read_status_any(data, 2, resp_id))
        {
            break;
        }
        for (size_t i = 0; i < ids.size(); ++i)
        {
            if (ids[i] == resp_id && !ok[i])
            {
                positions[i] = static_cast<uint16_t>(data[0]) | static_cast<uint16_t>(data[1] << 8);
                ok[i] = 1;
                break;
            }
        }
    }
    return true;
}

bool FeetechBus::read_homing_offset(uint8_t id, int& offset_out)
{
    const uint8_t params[2] = { kRegHomingOffset, 0x02 };
    if (!write_packet(id, kInstRead, params, 2))
    {
        return false;
    }
    uint8_t data[2] = { 0, 0 };
    if (!read_status(id, data, 2))
    {
        return false;
    }
    const uint16_t raw = static_cast<uint16_t>(data[0]) | static_cast<uint16_t>(data[1] << 8);
    // Sign-magnitude: bits [0, sign_bit) are the magnitude, bit sign_bit is the sign.
    const uint16_t magnitude = raw & ((1u << kHomingOffsetSignBit) - 1u);
    const bool negative = (raw >> kHomingOffsetSignBit) & 1u;
    offset_out = negative ? -static_cast<int>(magnitude) : static_cast<int>(magnitude);
    return true;
}

bool FeetechBus::disable_torque(uint8_t id)
{
    const uint8_t params[2] = { kRegTorqueEnable, 0x00 };
    if (!write_packet(id, kInstWrite, params, 2))
    {
        return false;
    }
    return read_status(id, nullptr, 0);
}

} // namespace so101_leader
} // namespace plugins

#else // _WIN32

namespace plugins
{
namespace so101_leader
{

FeetechBus::FeetechBus(const std::string& /*port*/, int /*baud*/)
{
    throw std::runtime_error(
        "FeetechBus: the serial backend is only implemented on POSIX "
        "(Linux/macOS); run the SO-101 leader on Linux, or omit the device "
        "path to use the synthetic backend");
}

FeetechBus::~FeetechBus() = default;

bool FeetechBus::write_packet(uint8_t, uint8_t, const uint8_t*, uint8_t)
{
    return false;
}
bool FeetechBus::read_status_any(uint8_t*, uint8_t, uint8_t&)
{
    return false;
}
bool FeetechBus::read_status(uint8_t, uint8_t*, uint8_t)
{
    return false;
}
bool FeetechBus::read_byte(uint8_t&, int)
{
    return false;
}
bool FeetechBus::read_position(uint8_t, uint16_t&)
{
    return false;
}
bool FeetechBus::sync_read_positions(const std::vector<uint8_t>&, std::vector<uint16_t>&, std::vector<uint8_t>&)
{
    return false;
}
bool FeetechBus::read_homing_offset(uint8_t, int&)
{
    return false;
}
bool FeetechBus::disable_torque(uint8_t)
{
    return false;
}

} // namespace so101_leader
} // namespace plugins

#endif // _WIN32
