// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>

#include <cstdint>
#include <vector>

namespace viz::detail
{

// Human-readable name for logging / error messages.
const char* view_configuration_type_name(XrViewConfigurationType type) noexcept;

// Pick the primary view configuration from what the runtime advertises.
// When prefer_foveated_inset is true, prefers PRIMARY_STEREO_WITH_FOVEATED_INSET,
// then PRIMARY_STEREO, then the first entry. Throws if advertised is empty.
XrViewConfigurationType select_view_configuration(const std::vector<XrViewConfigurationType>& advertised,
                                                  bool prefer_foveated_inset);

} // namespace viz::detail
