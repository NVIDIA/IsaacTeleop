// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <schema/external_skeleton_generated.h>

#include <cstdint>
#include <string>

namespace plugins
{
namespace external_skeleton
{

/*!
 * @brief Vendor-neutral interface for an external skeleton data source.
 *
 * Concrete implementations adapt a third-party motion capture device (Rokoko
 * Smartsuit, Xsens / Movella MVN, Sony mocopi, Noitom Perception Neuron,
 * OptiTrack NatNet, ...) onto the ``ExternalSkeletonPose`` schema.
 *
 * The plugin process owns one source instance and calls ``poll()`` from its
 * push loop. Sources are expected to be non-blocking; when no new sample is
 * available, return ``false`` and leave ``out`` untouched.
 */
class IExternalSkeletonSource
{
public:
    virtual ~IExternalSkeletonSource() = default;

    /*!
     * @brief Free-form vendor / device identifier copied into
     *        ``ExternalSkeletonPose.source_id`` on every push (e.g.
     *        ``"rokoko-smartsuit-pro"``, ``"xsens-awinda"``, ``"synthetic"``).
     */
    virtual std::string source_id() const = 0;

    /*!
     * @brief Try to read the latest skeleton sample from the device.
     *
     * @param out                Filled with the latest pose on success.
     * @param raw_device_clock_ns Filled with the device-clock timestamp of the
     *                            sample if available, otherwise left as 0
     *                            (the caller substitutes the local monotonic
     *                            clock).
     * @return ``true`` if a fresh sample was written into ``out``,
     *         ``false`` if no new data is available since the last call.
     */
    virtual bool poll(core::ExternalSkeletonPoseT& out, int64_t& raw_device_clock_ns) = 0;
};

} // namespace external_skeleton
} // namespace plugins
