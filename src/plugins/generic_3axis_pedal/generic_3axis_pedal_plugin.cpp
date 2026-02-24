// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "generic_3axis_pedal_plugin.hpp"

#include <flatbuffers/flatbuffers.h>
#include <linux/joystick.h>
#include <oxr/oxr_session.hpp>
#include <schema/pedals_generated.h>
#include <sys/select.h>

#include <cerrno>
#include <chrono>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <unistd.h>

namespace plugins
{
namespace generic_3axis_pedal
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

Generic3AxisPedalPlugin::Generic3AxisPedalPlugin(const std::string& device_path, const std::string& collection_id)
    : device_path_(device_path),
      session_(std::make_shared<core::OpenXRSession>(
          "Generic3AxisPedalPlugin", core::SchemaPusher::get_required_extensions())),
      pusher_(session_->get_handles(),
              core::SchemaPusherConfig{ .collection_id = collection_id,
                                        .max_flatbuffer_size = kMaxFlatbufferSize,
                                        .tensor_identifier = "generic_3axis_pedal",
                                        .localized_name = "Generic 3-Axis Pedal",
                                        .app_name = "Generic3AxisPedalPlugin" })
{
    if (!open_device())
        throw std::runtime_error("Generic3AxisPedalPlugin: Failed to open " + device_path + " (" + strerror(errno) + ")");
}

Generic3AxisPedalPlugin::~Generic3AxisPedalPlugin()
{
    close_device();
}


void Generic3AxisPedalPlugin::update()
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

        if ((event.type & JS_EVENT_AXIS) != 0u && event.number < 3)
        {
            axes_[event.number] = normalize_axis(event.value);
        }
    }

    push_current_state();
}

bool Generic3AxisPedalPlugin::open_device()
{
    assert(device_fd_ < 0);

    int fd = open(device_path_.c_str(), O_RDONLY | O_NONBLOCK);
    if (fd < 0)
        return false;

    device_fd_ = fd;
    std::cout << "Generic3AxisPedalPlugin: Opened " << device_path_ << std::endl;
    return true;
}

void Generic3AxisPedalPlugin::close_device()
{
    assert(device_fd_ >= 0);

    close(device_fd_);
    device_fd_ = -1;
}

void Generic3AxisPedalPlugin::push_current_state()
{
    core::Generic3AxisPedalOutput out;
    out.mutate_is_active(device_fd_ >= 0);
    out.mutate_left_pedal(static_cast<float>(axes_[0]));
    out.mutate_right_pedal(static_cast<float>(axes_[1]));
    out.mutate_rudder(static_cast<float>(axes_[2]));
    auto now = std::chrono::steady_clock::now();
    auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count();
    out.mutable_timestamp() = core::Timestamp(ns, ns);

    flatbuffers::FlatBufferBuilder builder(kMaxFlatbufferSize);
    core::Generic3AxisPedalOutputRecordBuilder record_builder(builder);
    record_builder.add_data(&out);
    builder.Finish(record_builder.Finish());
    pusher_.push_buffer(builder.GetBufferPointer(), builder.GetSize());
}

} // namespace generic_3axis_pedal
} // namespace plugins
