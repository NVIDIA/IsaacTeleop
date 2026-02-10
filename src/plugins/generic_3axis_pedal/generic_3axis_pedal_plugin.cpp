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
    : session_(std::make_shared<core::OpenXRSession>(
          "Generic3AxisPedalPlugin", core::SchemaPusher::get_required_extensions())),
      pusher_(session_->get_handles(),
              core::SchemaPusherConfig{ .collection_id = collection_id,
                                        .max_flatbuffer_size = kMaxFlatbufferSize,
                                        .tensor_identifier = "generic_3axis_pedal",
                                        .localized_name = "Generic 3-Axis Pedal",
                                        .app_name = "Generic3AxisPedalPlugin" })
{
    open_device(device_path, collection_id);
}

Generic3AxisPedalPlugin::~Generic3AxisPedalPlugin()
{
    close_device();
}


void Generic3AxisPedalPlugin::update()
{
    assert(device_fd_ >= 0);

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
            throw std::runtime_error("Generic3AxisPedalPlugin: Select error " + std::string(strerror(errno)));
        }
        if (ret == 0 || !FD_ISSET(device_fd_, &read_fds))
            break;

        js_event event;
        ssize_t n = read(device_fd_, &event, kJsEventSize);
        if (n != static_cast<ssize_t>(kJsEventSize))
        {
            if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK))
                break;
            close_device();
            push_current_state();
            throw std::runtime_error("Generic3AxisPedalPlugin: Read error " + std::string(strerror(errno)));
        }

        if ((event.type & JS_EVENT_AXIS) != 0u && event.number < 3)
        {
            axes_[event.number] = normalize_axis(event.value);
        }
    }

    push_current_state();
}

void Generic3AxisPedalPlugin::open_device(const std::string& device_path, const std::string& collection_id)
{
    assert(device_fd_ < 0);

    device_fd_ = open(device_path.c_str(), O_RDONLY | O_NONBLOCK);
    if (device_fd_ < 0)
    {
        throw std::runtime_error("Generic3AxisPedalPlugin: Failed to open " + device_path + " (" + strerror(errno) + ")");
    }

    std::cout << "Generic3AxisPedalPlugin: Opened " << device_path << " (collection: " << collection_id << ")"
              << std::endl;
}

void Generic3AxisPedalPlugin::close_device()
{
    assert(device_fd_ >= 0);

    close(device_fd_);
    device_fd_ = -1;
}

void Generic3AxisPedalPlugin::push_current_state()
{
    core::Generic3AxisPedalOutputT out;
    out.is_valid = (device_fd_ >= 0);
    out.left_pedal = static_cast<float>(axes_[0]);
    out.right_pedal = static_cast<float>(axes_[1]);
    out.rudder = static_cast<float>(axes_[2]);
    auto now = std::chrono::steady_clock::now();
    auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count();
    out.timestamp = std::make_shared<core::Timestamp>(ns, ns);

    flatbuffers::FlatBufferBuilder builder(kMaxFlatbufferSize);
    auto offset = core::Generic3AxisPedalOutput::Pack(builder, &out);
    builder.Finish(offset);
    pusher_.push_buffer(builder.GetBufferPointer(), builder.GetSize());
}

} // namespace generic_3axis_pedal
} // namespace plugins
