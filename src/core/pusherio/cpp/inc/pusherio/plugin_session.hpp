// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "hand_tracking_push_channel.hpp"
#include "schema_pusher.hpp"

#include <memory>

namespace core
{

/*!
 * @brief Transport-neutral capabilities a plugin may use during a session.
 *
 * Concrete sessions translate these capabilities into transport prerequisites
 * during construction and reject channel types that were not declared.
 */
struct PluginSessionRequirements
{
    bool schema_push = false;
    bool hand_tracking_push = false;
};

/*!
 * @brief Session abstraction that creates operation-specific plugin channels.
 *
 * The caller must keep the session alive until all channels created from it
 * have been destroyed.
 */
class IPluginSession
{
public:
    virtual ~IPluginSession() = default;

    virtual std::unique_ptr<ISchemaPushChannel> create_schema_push_channel(const SchemaPusherConfig& config) = 0;
    virtual std::unique_ptr<IHandTrackingPushChannel> create_hand_tracking_push_channel(XrHandEXT hand) = 0;
};

using PluginSessionHandle = std::shared_ptr<IPluginSession>;

} // namespace core
