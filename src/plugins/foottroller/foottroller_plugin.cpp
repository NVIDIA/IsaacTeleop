// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
// Adapted By X. Tian JP Tech. Initiatives Inc for Foottroller

#include "foottroller_plugin.hpp"

#include <flatbuffers/flatbuffers.h>
#include <linux/joystick.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/os_time.hpp>
#include <schema/foottroller_generated.h>
#include <sys/select.h>

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <unistd.h>

namespace plugins
{
namespace foottroller
{

namespace
{

constexpr size_t kJsEventSize = sizeof(js_event);
constexpr double kMaxAxisValue = 32767.0;
constexpr size_t kMaxFlatbufferSize = 256;

double normalize_axis(int16_t raw_value)
{
    return std::max(-1.0, std::min(1.0, static_cast<double>(raw_value) / kMaxAxisValue));
}

} // namespace

FoottrollerPlugin::FoottrollerPlugin(const std::string& device_path, const std::string& collection_id)
    : device_path_(device_path),
      session_(std::make_shared<core::OpenXRSession>("FoottrollerPlugin", core::SchemaPusher::get_required_extensions())),
      pusher_(session_->get_handles(),
              core::SchemaPusherConfig{ .collection_id = collection_id,
                                        .max_flatbuffer_size = kMaxFlatbufferSize,
                                        .tensor_identifier = "foottroller",
                                        .localized_name = "Foottroller",
                                        .app_name = "FoottrollerPlugin" })
{
    if (!open_device())
        throw std::runtime_error("FoottrollerPlugin: Failed to open " + device_path + " (" + strerror(errno) + ")");
}

FoottrollerPlugin::~FoottrollerPlugin()
{
    close_device();
}


void FoottrollerPlugin::update()
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

        if ((event.type & JS_EVENT_AXIS) != 0u && event.number < 6)
        {
            axes_[event.number] = normalize_axis(event.value);
        }
        else if (event.type == JS_EVENT_BUTTON && event.number < 4)
        {
            if (event.value == 1)
            {
                buttons_[event.number] = true;
            }
            else if (event.value == 0)
            {
                buttons_[event.number] = false;
            }
        }
    }

    push_current_state();
}

bool FoottrollerPlugin::open_device()
{
    assert(device_fd_ < 0);

    int fd = open(device_path_.c_str(), O_RDONLY | O_NONBLOCK);
    if (fd < 0)
        return false;

    device_fd_ = fd;
    std::cout << "FoottrollerPlugin: Opened " << device_path_ << std::endl;
    return true;
}

void FoottrollerPlugin::close_device()
{
    assert(device_fd_ >= 0);

    close(device_fd_);
    device_fd_ = -1;
}

void FoottrollerPlugin::push_current_state()
{
    core::FoottrollerOutputT out;
    out.stick_x = static_cast<float>(axes_[0]);
    out.stick_y = static_cast<float>(axes_[1]);
    out.LF_heading = static_cast<float>(axes_[2]);
    out.LF_tilt = static_cast<float>(axes_[3]);
    out.RF_heading = static_cast<float>(axes_[4]);
    out.RF_tilt = static_cast<float>(axes_[5]);
    out.TS_A = buttons_[0];
    out.TS_B = buttons_[1];
    out.TS_C = buttons_[2];
    out.TS_D = buttons_[3];

    auto sample_time_ns = core::os_monotonic_now_ns();

    flatbuffers::FlatBufferBuilder builder(kMaxFlatbufferSize);
    auto offset = core::FoottrollerOutput::Pack(builder, &out);
    builder.Finish(offset);
    pusher_.push_buffer(builder.GetBufferPointer(), builder.GetSize(), sample_time_ns, sample_time_ns);
}

} // namespace foottroller
} // namespace plugins
