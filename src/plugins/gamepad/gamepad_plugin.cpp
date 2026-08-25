// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "gamepad_plugin.hpp"

#include <flatbuffers/flatbuffers.h>
#include <linux/joystick.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/os_time.hpp>
#include <schema/gamepad_generated.h>
#include <sys/ioctl.h>
#include <sys/select.h>

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <unistd.h>

namespace plugins
{
namespace gamepad
{

namespace
{

constexpr size_t kJsEventSize = sizeof(js_event);
constexpr double kMaxAxisValue = 32767.0;
constexpr size_t kMaxFlatbufferSize = 512;
// Fallback axis count when JSIOCGAXES is unavailable -- covers the common
// left/right-stick + trigger + dpad layout (8 axes) reported by most
// Xbox-style gamepads under the xpad driver.
constexpr uint8_t kDefaultAxisCount = 8;

double normalize_axis(int16_t raw_value)
{
    return std::max(-1.0, std::min(1.0, static_cast<double>(raw_value) / kMaxAxisValue));
}

} // namespace

GamepadPlugin::GamepadPlugin(const std::string& device_path, const std::string& collection_id)
    : device_path_(device_path),
      session_(std::make_shared<core::OpenXRSession>("GamepadPlugin", core::SchemaPusher::get_required_extensions())),
      pusher_(session_->get_handles(),
              core::SchemaPusherConfig{ .collection_id = collection_id,
                                        .max_flatbuffer_size = kMaxFlatbufferSize,
                                        .tensor_identifier = "gamepad",
                                        .localized_name = "Gamepad",
                                        .app_name = "GamepadPlugin" })
{
    if (!open_device())
        throw std::runtime_error("GamepadPlugin: Failed to open " + device_path + " (" + strerror(errno) + ")");
}

GamepadPlugin::~GamepadPlugin()
{
    close_device();
}

void GamepadPlugin::update()
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

        js_event event;
        ssize_t n = read(device_fd_, &event, kJsEventSize);
        if (n != static_cast<ssize_t>(kJsEventSize))
        {
            if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK))
                break;
            close_device();
            push_current_state();
            return;
        }

        const auto type = static_cast<uint8_t>(event.type & ~JS_EVENT_INIT);
        if (type == JS_EVENT_AXIS && event.number < axes_.size())
        {
            axes_[event.number] = static_cast<float>(normalize_axis(event.value));
        }
        else if (type == JS_EVENT_BUTTON)
        {
            if (event.value != 0)
                pressed_buttons_.insert(event.number);
            else
                pressed_buttons_.erase(event.number);
        }
    }

    push_current_state();
}

bool GamepadPlugin::open_device()
{
    assert(device_fd_ < 0);

    int fd = open(device_path_.c_str(), O_RDONLY | O_NONBLOCK);
    if (fd < 0)
        return false;

    uint8_t axis_count = kDefaultAxisCount;
    ioctl(fd, JSIOCGAXES, &axis_count);
    axes_.assign(axis_count, 0.0f);

    device_fd_ = fd;
    std::cout << "GamepadPlugin: Opened " << device_path_ << " (" << static_cast<int>(axis_count) << " axes)"
              << std::endl;
    return true;
}

void GamepadPlugin::close_device()
{
    assert(device_fd_ >= 0);

    close(device_fd_);
    device_fd_ = -1;
    // A closed device can no longer report releases -- forget everything it
    // last reported as held so a stale button doesn't stick "pressed" forever.
    pressed_buttons_.clear();
}

void GamepadPlugin::push_current_state()
{
    core::GamepadOutputT out;
    out.pressed_buttons.assign(pressed_buttons_.begin(), pressed_buttons_.end());
    out.axes = axes_;
    out.is_valid = true;

    auto sample_time_ns = core::os_monotonic_now_ns();

    flatbuffers::FlatBufferBuilder builder(kMaxFlatbufferSize);
    auto offset = core::GamepadOutput::Pack(builder, &out);
    builder.Finish(offset);
    pusher_.push_buffer(builder.GetBufferPointer(), builder.GetSize(), sample_time_ns, sample_time_ns);
}

} // namespace gamepad
} // namespace plugins
