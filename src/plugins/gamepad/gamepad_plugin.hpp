// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <pusherio/schema_pusher.hpp>

#include <cstdint>
#include <memory>
#include <set>
#include <string>
#include <vector>

namespace core
{
class OpenXRSession;
}

namespace plugins
{
namespace gamepad
{

/*!
 * @brief Reads a Linux joystick-API gamepad device (e.g. /dev/input/js0), tracks
 *        the set of currently-held button indices and every reported axis value,
 *        and pushes GamepadOutput via OpenXR SchemaPusher. Carries no semantic
 *        mapping -- buttons/axes are reported as-is (Linux joystick API indices).
 */
class GamepadPlugin
{
public:
    GamepadPlugin(const std::string& device_path, const std::string& collection_id);
    ~GamepadPlugin();

    void update();

private:
    bool open_device();
    void close_device();
    void push_current_state();

    std::string device_path_;
    int device_fd_ = -1;

    std::set<uint16_t> pressed_buttons_;
    std::vector<float> axes_;

    std::shared_ptr<core::OpenXRSession> session_;
    core::SchemaPusher pusher_;
};

} // namespace gamepad
} // namespace plugins
