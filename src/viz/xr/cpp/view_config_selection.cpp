// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/viz/xr/view_config_selection.hpp"

#include <algorithm>
#include <stdexcept>

namespace viz::detail
{

const char* view_configuration_type_name(XrViewConfigurationType type) noexcept
{
    switch (type)
    {
    case XR_VIEW_CONFIGURATION_TYPE_PRIMARY_MONO:
        return "PRIMARY_MONO";
    case XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO:
        return "PRIMARY_STEREO";
    case XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO_WITH_FOVEATED_INSET:
        return "PRIMARY_STEREO_WITH_FOVEATED_INSET";
    default:
        return "UNKNOWN";
    }
}

XrViewConfigurationType select_view_configuration(const std::vector<XrViewConfigurationType>& advertised,
                                                  bool prefer_foveated_inset)
{
    if (advertised.empty())
    {
        throw std::runtime_error("OpenXrSession: runtime advertises zero view configurations");
    }

    const auto has = [&](XrViewConfigurationType t)
    { return std::find(advertised.begin(), advertised.end(), t) != advertised.end(); };

    if (prefer_foveated_inset && has(XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO_WITH_FOVEATED_INSET))
    {
        return XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO_WITH_FOVEATED_INSET;
    }
    if (has(XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO))
    {
        return XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
    }
    return advertised.front();
}

} // namespace viz::detail
