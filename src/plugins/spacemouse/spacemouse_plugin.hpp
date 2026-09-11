// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <pusherio/schema_pusher.hpp>

#include <array>
#include <cstdint>
#include <memory>
#include <set>
#include <string>

namespace core
{
class OpenXRSession;
}

namespace plugins
{
namespace spacemouse
{

/*!
 * @brief Reads a 3Dconnexion SpaceMouse-family HID device (e.g. /dev/hidraw0),
 *        tracks the current translation/rotation axis readings and the set of
 *        currently-held button indices, and pushes SpaceMouseOutput via OpenXR
 *        SchemaPusher. Carries no semantic mapping -- axes/buttons are reported
 *        as-is (raw HID report bytes, decoded to normalized [-1, 1] axis values).
 */
class SpaceMousePlugin
{
public:
    // combined_report: true for devices (e.g. "3Dconnexion Universal Receiver") that pack
    // translation and rotation into a single 13-byte report ID 1, rather than reporting
    // translation on ID 1 and rotation on ID 2 as separate 7-byte reports.
    SpaceMousePlugin(const std::string& device_path, const std::string& collection_id, bool combined_report);
    ~SpaceMousePlugin();

    void update();

private:
    bool open_device();
    void close_device();
    void push_current_state();

    std::string device_path_;
    int device_fd_ = -1;

    // Whether this device reports translation and rotation in a single combined
    // 13-byte report (report ID 1, translation in bytes 1-6, rotation in bytes
    // 7-12) rather than as two separate 7-byte reports (report ID 1 = translation,
    // report ID 2 = rotation). Matches the "3Dconnexion Universal Receiver"
    // quirk in Isaac Lab's Se3SpaceMouse/Se2SpaceMouse.
    bool combined_report_ = false;

    std::array<float, 3> translation_{ 0.0f, 0.0f, 0.0f };
    std::array<float, 3> rotation_{ 0.0f, 0.0f, 0.0f };
    std::set<uint16_t> pressed_buttons_;

    std::shared_ptr<core::OpenXRSession> session_;
    core::SchemaPusher pusher_;
};

} // namespace spacemouse
} // namespace plugins
