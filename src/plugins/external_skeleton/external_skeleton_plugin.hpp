// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "external_skeleton_source.hpp"

#include <pusherio/schema_pusher.hpp>

#include <memory>
#include <string>

namespace core
{
class OpenXRSession;
}

namespace plugins
{
namespace external_skeleton
{

/*!
 * @brief Owns an ``OpenXRSession`` + ``SchemaPusher`` and forwards skeleton
 *        samples produced by an injected ``IExternalSkeletonSource`` onto the
 *        ``ExternalSkeletonPose`` schema.
 *
 * This class is intentionally device-agnostic: vendor-specific I/O (UDP
 * sockets, BLE, native SDK callbacks) lives entirely behind
 * ``IExternalSkeletonSource``. To add support for a new mocap suit, write a
 * new ``IExternalSkeletonSource`` implementation; the pusher loop here does
 * not change.
 */
class ExternalSkeletonPlugin
{
public:
    ExternalSkeletonPlugin(std::unique_ptr<IExternalSkeletonSource> source, const std::string& collection_id);

    ExternalSkeletonPlugin(const ExternalSkeletonPlugin&) = delete;
    ExternalSkeletonPlugin& operator=(const ExternalSkeletonPlugin&) = delete;

    /*!
     * @brief Polls the source once and pushes the resulting sample (if any).
     *
     * Safe to call at the chosen frame rate from a tight loop. When the source
     * has no new sample, no push is performed for this tick.
     */
    void update();

private:
    void push(const core::ExternalSkeletonPoseT& pose, int64_t raw_device_clock_ns);

    std::unique_ptr<IExternalSkeletonSource> source_;
    std::shared_ptr<core::OpenXRSession> session_;
    core::SchemaPusher pusher_;
    size_t max_flatbuffer_size_;
};

} // namespace external_skeleton
} // namespace plugins
