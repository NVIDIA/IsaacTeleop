// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/viz_types.hpp>

namespace viz::detail
{

// Eye-driven stereo sampling for composited QuadLayer record(). View index
// is not an eye id in quad-view (insets are views 2/3).
inline bool quad_layer_sample_right(bool xr_mode, bool stereo, Eye eye) noexcept
{
    return xr_mode && stereo && eye == Eye::kRight;
}

inline float quad_layer_baseline_sign(Eye eye) noexcept
{
    return (eye == Eye::kRight) ? +1.0f : -1.0f;
}

} // namespace viz::detail
