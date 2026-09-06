// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/plugin_utils/openxr_plugin_session.hpp"

#include "openxr_hand_tracking_push_channel.hpp"

#include <deviceio_session/deviceio_session.hpp>
#include <openxr/openxr.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/oxr_time.hpp>
#include <pusherio/openxr_schema_push_channel.hpp>

#include <XR_MNDX_xdev_space.h>
#include <XR_NVX1_device_interface.h>
#include <algorithm>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace plugin_utils
{

namespace
{

void append_unique(std::vector<std::string>& extensions, const std::vector<std::string>& additions)
{
    for (const auto& extension : additions)
    {
        if (std::find(extensions.begin(), extensions.end(), extension) == extensions.end())
        {
            extensions.push_back(extension);
        }
    }
}

std::vector<std::string> make_required_extensions(
    const core::PluginSessionRequirements& requirements,
    const std::vector<std::shared_ptr<core::ITracker>>& trackers)
{
    auto extensions = core::DeviceIOSession::get_required_extensions(trackers);

    if (requirements.schema_push)
    {
        append_unique(extensions, core::OpenXRSchemaPushChannel::get_required_extensions());
    }

    if (requirements.hand_tracking_push)
    {
        append_unique(extensions, { XR_NVX1_DEVICE_INTERFACE_BASE_EXTENSION_NAME });
        append_unique(extensions, core::XrTimeConverter::get_required_extensions());
    }

    return extensions;
}

bool is_extension_supported(const char* extension_name)
{
    uint32_t count = 0;
    if (XR_FAILED(xrEnumerateInstanceExtensionProperties(nullptr, 0, &count, nullptr)))
    {
        return false;
    }

    std::vector<XrExtensionProperties> properties(count, XrExtensionProperties{ XR_TYPE_EXTENSION_PROPERTIES });
    if (XR_FAILED(xrEnumerateInstanceExtensionProperties(nullptr, count, &count, properties.data())))
    {
        return false;
    }

    return std::any_of(properties.begin(), properties.end(), [extension_name](const XrExtensionProperties& property)
                       { return std::string(property.extensionName) == extension_name; });
}

} // anonymous namespace

OpenXRPluginSession::OpenXRPluginSession(std::string app_name,
                                         core::PluginSessionRequirements requirements,
                                         std::vector<std::shared_ptr<core::ITracker>> trackers)
    : requirements_(requirements),
      trackers_(std::move(trackers)),
      session_(std::make_shared<core::OpenXRSession>(app_name, make_required_extensions(requirements_, trackers_)))
{
}

OpenXRPluginSession::~OpenXRPluginSession() = default;

std::unique_ptr<core::ISchemaPushChannel> OpenXRPluginSession::create_schema_push_channel(
    const core::SchemaPusherConfig& config)
{
    if (!requirements_.schema_push)
    {
        throw std::logic_error("OpenXRPluginSession: schema push was not declared in PluginSessionRequirements");
    }
    return core::make_openxr_schema_push_channel(session_->get_handles(), config);
}

std::unique_ptr<core::IHandTrackingPushChannel> OpenXRPluginSession::create_hand_tracking_push_channel(XrHandEXT hand)
{
    if (!requirements_.hand_tracking_push)
    {
        throw std::logic_error(
            "OpenXRPluginSession: hand-tracking push was not declared in PluginSessionRequirements");
    }
    return make_openxr_hand_tracking_push_channel(session_->get_handles(), hand);
}

std::unique_ptr<core::DeviceIOSession> OpenXRPluginSession::create_deviceio_session() const
{
    return core::DeviceIOSession::run(trackers_, session_->get_handles());
}

bool OpenXRPluginSession::supports_native_hand_tracking()
{
    return is_extension_supported(XR_EXT_HAND_TRACKING_EXTENSION_NAME) &&
           is_extension_supported(XR_MNDX_XDEV_SPACE_EXTENSION_NAME);
}

core::OpenXRSessionHandles OpenXRPluginSession::get_openxr_handles() const
{
    return session_->get_handles();
}

} // namespace plugin_utils
