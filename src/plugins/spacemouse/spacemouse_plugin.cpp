// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "spacemouse_plugin.hpp"

#include <flatbuffers/flatbuffers.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/os_time.hpp>
#include <schema/spacemouse_generated.h>
#include <sys/select.h>

#include <algorithm>
#include <cassert>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <unistd.h>

namespace plugins
{
namespace spacemouse
{

namespace
{

// Combined (Universal Receiver) reports are 13 bytes: report ID + 6 translation bytes +
// 6 rotation bytes. Separate reports are 7 bytes: report ID + 6 axis bytes.
constexpr size_t kCombinedReportSize = 13;
constexpr size_t kSeparateReportSize = 7;
constexpr double kAxisScale = 350.0;
constexpr size_t kMaxFlatbufferSize = 512;

// Two bytes, little-endian, to a signed 16-bit integer -- matches Isaac Lab's
// isaaclab.devices.spacemouse.utils._to_int16.
int16_t to_int16(uint8_t low, uint8_t high)
{
    return static_cast<int16_t>(static_cast<uint16_t>(low) | (static_cast<uint16_t>(high) << 8));
}

// Matches isaaclab.devices.spacemouse.utils.convert_buffer: normalize and clamp to [-1, 1].
float convert_axis(uint8_t low, uint8_t high)
{
    double value = static_cast<double>(to_int16(low, high)) / kAxisScale;
    return static_cast<float>(std::max(-1.0, std::min(1.0, value)));
}

} // namespace

SpaceMousePlugin::SpaceMousePlugin(const std::string& device_path, const std::string& collection_id, bool combined_report)
    : device_path_(device_path),
      combined_report_(combined_report),
      session_(std::make_shared<core::OpenXRSession>("SpaceMousePlugin", core::SchemaPusher::get_required_extensions())),
      pusher_(session_->get_handles(),
              core::SchemaPusherConfig{ .collection_id = collection_id,
                                        .max_flatbuffer_size = kMaxFlatbufferSize,
                                        .tensor_identifier = "spacemouse",
                                        .localized_name = "SpaceMouse",
                                        .app_name = "SpaceMousePlugin" })
{
    if (!open_device())
        throw std::runtime_error("SpaceMousePlugin: Failed to open " + device_path + " (" + strerror(errno) + ")");
}

SpaceMousePlugin::~SpaceMousePlugin()
{
    if (device_fd_ >= 0)
        close_device();
}

void SpaceMousePlugin::update()
{
    if (device_fd_ < 0)
    {
        open_device();
        if (device_fd_ < 0)
        {
            push_current_state();
            return;
        }
    }

    const size_t report_size = combined_report_ ? kCombinedReportSize : kSeparateReportSize;

    fd_set read_fds;
    struct timeval timeout = { 0, 0 };

    while (true)
    {
        FD_ZERO(&read_fds);
        FD_SET(device_fd_, &read_fds);
        timeout = { 0, 0 };

        int ret = select(device_fd_ + 1, &read_fds, nullptr, nullptr, &timeout);
        if (ret < 0)
        {
            if (errno == EINTR)
                return;
            close_device();
            push_current_state();
            return;
        }
        if (ret == 0 || !FD_ISSET(device_fd_, &read_fds))
        {
            // If there is no data to read (ret == 0) or the device file descriptor is not set in
            // the read set, break out of the loop; this means there's no new event available.
            break;
        }

        uint8_t buffer[kCombinedReportSize];
        ssize_t n = read(device_fd_, buffer, report_size);
        if (n <= 0)
        {
            if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK))
                break;
            close_device();
            push_current_state();
            return;
        }

        const uint8_t report_id = buffer[0];
        if (report_id == 1 && static_cast<size_t>(n) >= 7)
        {
            translation_[0] = convert_axis(buffer[1], buffer[2]);
            translation_[1] = convert_axis(buffer[3], buffer[4]);
            translation_[2] = convert_axis(buffer[5], buffer[6]);
            if (combined_report_ && static_cast<size_t>(n) >= 13)
            {
                rotation_[0] = convert_axis(buffer[7], buffer[8]);
                rotation_[1] = convert_axis(buffer[9], buffer[10]);
                rotation_[2] = convert_axis(buffer[11], buffer[12]);
            }
        }
        else if (report_id == 2 && !combined_report_ && static_cast<size_t>(n) >= 7)
        {
            rotation_[0] = convert_axis(buffer[1], buffer[2]);
            rotation_[1] = convert_axis(buffer[3], buffer[4]);
            rotation_[2] = convert_axis(buffer[5], buffer[6]);
        }
        else if (report_id == 3 && static_cast<size_t>(n) >= 2)
        {
            // Button report: buffer[1] is a bitmask (bit i = button i currently held).
            pressed_buttons_.clear();
            for (uint16_t bit = 0; bit < 8; ++bit)
            {
                if ((buffer[1] & (1u << bit)) != 0u)
                    pressed_buttons_.insert(bit);
            }
        }
    }

    push_current_state();
}

bool SpaceMousePlugin::open_device()
{
    assert(device_fd_ < 0);

    int fd = open(device_path_.c_str(), O_RDONLY | O_NONBLOCK);
    if (fd < 0)
        return false;

    device_fd_ = fd;
    std::cout << "SpaceMousePlugin: Opened " << device_path_ << (combined_report_ ? " (combined report)" : "")
              << std::endl;
    return true;
}

void SpaceMousePlugin::close_device()
{
    assert(device_fd_ >= 0);

    close(device_fd_);
    device_fd_ = -1;
    // A closed device can no longer report releases -- forget everything it last
    // reported as held so a stale button doesn't stick "pressed" forever, and zero
    // the motion state so a disconnected device can't keep commanding stale motion.
    pressed_buttons_.clear();
    translation_.fill(0.0f);
    rotation_.fill(0.0f);
}

void SpaceMousePlugin::push_current_state()
{
    core::SpaceMouseOutputT out;
    out.translation.assign(translation_.begin(), translation_.end());
    out.rotation.assign(rotation_.begin(), rotation_.end());
    out.pressed_buttons.assign(pressed_buttons_.begin(), pressed_buttons_.end());
    out.is_valid = true;

    auto sample_time_ns = core::os_monotonic_now_ns();

    flatbuffers::FlatBufferBuilder builder(kMaxFlatbufferSize);
    auto offset = core::SpaceMouseOutput::Pack(builder, &out);
    builder.Finish(offset);
    pusher_.push_buffer(builder.GetBufferPointer(), builder.GetSize(), sample_time_ns, sample_time_ns);
}

} // namespace spacemouse
} // namespace plugins
