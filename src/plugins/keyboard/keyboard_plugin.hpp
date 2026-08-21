// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
namespace keyboard
{

/*!
 * @brief Reads a Linux evdev keyboard device (e.g. /dev/input/event3), tracks
 *        the current press state of a fixed key set, and pushes KeyboardOutput
 *        via OpenXR SchemaPusher. Carries no semantic mapping -- keys are
 *        reported as-is.
 */
class KeyboardPlugin
{
public:
    KeyboardPlugin(const std::string& device_path, const std::string& collection_id);
    ~KeyboardPlugin();

    void update();

private:
    bool open_device();
    void close_device();
    void push_current_state();
    void apply_key_event(unsigned short code, bool pressed);

    std::string device_path_;
    int device_fd_ = -1;

    bool key_w_ = false;
    bool key_a_ = false;
    bool key_s_ = false;
    bool key_d_ = false;
    bool key_q_ = false;
    bool key_e_ = false;
    bool key_z_ = false;
    bool key_x_ = false;
    bool key_t_ = false;
    bool key_g_ = false;
    bool key_c_ = false;
    bool key_v_ = false;
    bool key_k_ = false;

    std::shared_ptr<core::OpenXRSession> session_;
    core::SchemaPusher pusher_;
};

} // namespace keyboard
} // namespace plugins
