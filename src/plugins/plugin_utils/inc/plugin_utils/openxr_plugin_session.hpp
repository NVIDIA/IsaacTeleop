// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <oxr_utils/oxr_session_handles.hpp>
#include <pusherio/plugin_session.hpp>

#include <memory>
#include <string>
#include <vector>

namespace core
{
class DeviceIOSession;
class ITracker;
class OpenXRSession;
}

namespace plugin_utils
{

/*!
 * @brief Local plugin session that creates OpenXR-backed operation channels.
 *
 * The adapter owns the OpenXR session. Its owner must destroy every returned
 * channel before destroying this session.
 */
class OpenXRPluginSession final : public core::IPluginSession
{
public:
    OpenXRPluginSession(std::string app_name,
                        core::PluginSessionRequirements requirements,
                        std::vector<std::shared_ptr<core::ITracker>> trackers = {});
    ~OpenXRPluginSession() override;

    OpenXRPluginSession(const OpenXRPluginSession&) = delete;
    OpenXRPluginSession& operator=(const OpenXRPluginSession&) = delete;
    OpenXRPluginSession(OpenXRPluginSession&&) = delete;
    OpenXRPluginSession& operator=(OpenXRPluginSession&&) = delete;

    std::unique_ptr<core::ISchemaPushChannel> create_schema_push_channel(const core::SchemaPusherConfig& config) override;
    std::unique_ptr<core::IHandTrackingPushChannel> create_hand_tracking_push_channel(XrHandEXT hand) override;

    //! Creates DeviceIO over the same OpenXR session using the trackers declared at construction.
    std::unique_ptr<core::DeviceIOSession> create_deviceio_session() const;

    //! Whether the runtime can provide the native optical hand-tracking input used by glove plugins.
    static bool supports_native_hand_tracking();

    //! Native access for OpenXR-specific plugin features; transport-neutral plugins must not use this.
    core::OpenXRSessionHandles get_openxr_handles() const;

private:
    core::PluginSessionRequirements requirements_;
    std::vector<std::shared_ptr<core::ITracker>> trackers_;
    std::shared_ptr<core::OpenXRSession> session_;
};

} // namespace plugin_utils
