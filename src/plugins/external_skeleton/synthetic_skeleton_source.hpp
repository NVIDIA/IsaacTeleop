// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "external_skeleton_source.hpp"

#include <chrono>

namespace plugins
{
namespace external_skeleton
{

/*!
 * @brief Synthetic data source for end-to-end testing without hardware.
 *
 * Produces a slowly-waving upper-body skeleton (a stylized "arm wave" gesture)
 * so that the plugin → tracker → retargeter pipeline can be exercised with no
 * external mocap suit attached. Replace this with a vendor-specific source
 * (e.g. ``RokokoSkeletonSource`` reading the Custom Streaming JSON over UDP)
 * for a real device.
 */
class SyntheticSkeletonSource : public IExternalSkeletonSource
{
public:
    SyntheticSkeletonSource();
    ~SyntheticSkeletonSource() override = default;

    std::string source_id() const override
    {
        return "synthetic";
    }

    bool poll(core::ExternalSkeletonPoseT& out, int64_t& raw_device_clock_ns) override;

private:
    std::chrono::steady_clock::time_point start_;
};

} // namespace external_skeleton
} // namespace plugins
