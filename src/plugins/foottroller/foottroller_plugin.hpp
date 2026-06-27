// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
// Adapted by X. Tian JP Tech. Initiatives Inc for Foottroller

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
namespace foottroller
{

/*!
 * @brief Reads a Linux joystick (e.g. /dev/input/js0), maps axes to
 *        stick_x, stick_y, LF_heading, LF_tilt, RF_heading, RF_tilt, TS_A, TS_B, TS_Cand TS_D pushes FoottrollerOutput
 *        via OpenXR SchemaPusher.
 */
class FoottrollerPlugin
{
public:
    FoottrollerPlugin(const std::string& device_path, const std::string& collection_id);
    ~FoottrollerPlugin();

    void update();

private:
    bool open_device();
    void close_device();
    void push_current_state();

    std::string device_path_;
    int device_fd_ = -1;
    double axes_[6] = { 0.0, 0.0, 0.0, 0.0, 0.0, 0.0 };
    bool buttons_[4];
    std::shared_ptr<core::OpenXRSession> session_;
    core::SchemaPusher pusher_;
};

} // namespace foottroller
} // namespace plugins
