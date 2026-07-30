// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_session/deviceio_session.hpp>
#include <deviceio_trackers/controller_tracker.hpp>
#include <oxr/oxr_session.hpp>
#include <pusherio/schema_pusher.hpp>

#include <memory>
#include <string>

namespace plugins
{
namespace controller_se3_tracker
{

/*!
 * @brief Logical SE3 tracker driven by an XR controller.
 *
 * Reads the configured controller's grip pose (the OpenXR rigid-attachment frame for the
 * physical device) each tick and republishes it as an ``Se3TrackerPose`` via OpenXR
 * SchemaPusher, in the same OpenXR session base reference space. Pair with an
 * ``Se3Tracker`` on the same ``collection_id``.
 *
 * Producer-only: this plugin never registers an ``Se3Tracker`` in its own session (it
 * would read back its own pushes).
 */
class ControllerSe3TrackerPlugin
{
public:
    ControllerSe3TrackerPlugin(bool use_left_hand, const std::string& collection_id);

    ControllerSe3TrackerPlugin(const ControllerSe3TrackerPlugin&) = delete;
    ControllerSe3TrackerPlugin& operator=(const ControllerSe3TrackerPlugin&) = delete;
    ControllerSe3TrackerPlugin(ControllerSe3TrackerPlugin&&) = delete;
    ControllerSe3TrackerPlugin& operator=(ControllerSe3TrackerPlugin&&) = delete;

    //! One tick: update the device session, read the controller, push one Se3TrackerPose.
    //! Pushes EVERY tick — is_valid=false (identity filler pose) when the controller is
    //! absent or its grip pose is invalid.
    void update();

private:
    bool m_use_left_hand;

    std::shared_ptr<core::ControllerTracker> m_controller_tracker;
    std::shared_ptr<core::OpenXRSession> m_session;
    std::unique_ptr<core::DeviceIOSession> m_deviceio_session;
    std::unique_ptr<core::SchemaPusher> m_pusher;
};

} // namespace controller_se3_tracker
} // namespace plugins
