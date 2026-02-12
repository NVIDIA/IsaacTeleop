// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <pusherio/schema_pusher.hpp>

#include <memory>
#include <string>

namespace core
{
class OpenXRSession;
}

namespace plugins
{
namespace generic_3axis_pedal
{

/*!
 * @brief Reads a Linux joystick (e.g. /dev/input/js0), maps axes to
 *        left_pedal, right_pedal, rudder, and pushes Generic3AxisPedalOutput
 *        via OpenXR SchemaPusher.
 */
class Generic3AxisPedalPlugin
{
public:
    Generic3AxisPedalPlugin(const std::string& device_path, const std::string& collection_id);
    ~Generic3AxisPedalPlugin();

    void update();

private:
    bool open_device();
    void close_device();
    void push_current_state();

    std::string device_path_;
    int device_fd_ = -1;
    double axes_[3] = { 0.0, 0.0, 0.0 };

    std::shared_ptr<core::OpenXRSession> session_;
    core::SchemaPusher pusher_;
};

} // namespace generic_3axis_pedal
} // namespace plugins
