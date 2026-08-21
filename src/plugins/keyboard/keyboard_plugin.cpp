// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "keyboard_plugin.hpp"

#include <flatbuffers/flatbuffers.h>
#include <linux/input.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/os_time.hpp>
#include <schema/keyboard_generated.h>
#include <sys/select.h>

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <unistd.h>

namespace plugins
{
namespace keyboard
{

namespace
{

constexpr size_t kInputEventSize = sizeof(input_event);
constexpr size_t kMaxFlatbufferSize = 256;

} // namespace

KeyboardPlugin::KeyboardPlugin(const std::string& device_path, const std::string& collection_id)
    : device_path_(device_path),
      session_(std::make_shared<core::OpenXRSession>("KeyboardPlugin", core::SchemaPusher::get_required_extensions())),
      pusher_(session_->get_handles(),
              core::SchemaPusherConfig{ .collection_id = collection_id,
                                        .max_flatbuffer_size = kMaxFlatbufferSize,
                                        .tensor_identifier = "keyboard",
                                        .localized_name = "Keyboard",
                                        .app_name = "KeyboardPlugin" })
{
    if (!open_device())
        throw std::runtime_error("KeyboardPlugin: Failed to open " + device_path + " (" + strerror(errno) + ")");
}

KeyboardPlugin::~KeyboardPlugin()
{
    close_device();
}

void KeyboardPlugin::update()
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

        input_event event;
        ssize_t n = read(device_fd_, &event, kInputEventSize);
        if (n != static_cast<ssize_t>(kInputEventSize))
        {
            if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK))
                break;
            close_device();
            push_current_state();
            return;
        }

        // value: 0 = release, 1 = press, 2 = autorepeat (ignored -- press state is already true).
        if (event.type == EV_KEY && event.value != 2)
        {
            apply_key_event(event.code, event.value != 0);
        }
    }

    push_current_state();
}

void KeyboardPlugin::apply_key_event(unsigned short code, bool pressed)
{
    switch (code)
    {
    case KEY_W:
        key_w_ = pressed;
        break;
    case KEY_A:
        key_a_ = pressed;
        break;
    case KEY_S:
        key_s_ = pressed;
        break;
    case KEY_D:
        key_d_ = pressed;
        break;
    case KEY_Q:
        key_q_ = pressed;
        break;
    case KEY_E:
        key_e_ = pressed;
        break;
    case KEY_Z:
        key_z_ = pressed;
        break;
    case KEY_X:
        key_x_ = pressed;
        break;
    case KEY_T:
        key_t_ = pressed;
        break;
    case KEY_G:
        key_g_ = pressed;
        break;
    case KEY_C:
        key_c_ = pressed;
        break;
    case KEY_V:
        key_v_ = pressed;
        break;
    case KEY_K:
        key_k_ = pressed;
        break;
    default:
        break;
    }
}

bool KeyboardPlugin::open_device()
{
    assert(device_fd_ < 0);

    int fd = open(device_path_.c_str(), O_RDONLY | O_NONBLOCK);
    if (fd < 0)
        return false;

    device_fd_ = fd;
    std::cout << "KeyboardPlugin: Opened " << device_path_ << std::endl;
    return true;
}

void KeyboardPlugin::close_device()
{
    assert(device_fd_ >= 0);

    close(device_fd_);
    device_fd_ = -1;
}

void KeyboardPlugin::push_current_state()
{
    core::KeyboardOutputT out;
    out.key_w = key_w_;
    out.key_a = key_a_;
    out.key_s = key_s_;
    out.key_d = key_d_;
    out.key_q = key_q_;
    out.key_e = key_e_;
    out.key_z = key_z_;
    out.key_x = key_x_;
    out.key_t = key_t_;
    out.key_g = key_g_;
    out.key_c = key_c_;
    out.key_v = key_v_;
    out.key_k = key_k_;
    out.is_valid = true;

    auto sample_time_ns = core::os_monotonic_now_ns();

    flatbuffers::FlatBufferBuilder builder(kMaxFlatbufferSize);
    auto offset = core::KeyboardOutput::Pack(builder, &out);
    builder.Finish(offset);
    pusher_.push_buffer(builder.GetBufferPointer(), builder.GetSize(), sample_time_ns, sample_time_ns);
}

} // namespace keyboard
} // namespace plugins
