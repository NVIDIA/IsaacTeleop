// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <string>
#include <vector>

namespace viz
{

// OpenXR loader probes — no XrInstance required.
std::vector<std::string> enumerate_openxr_instance_extensions() noexcept;
bool openxr_loader_available() noexcept;

} // namespace viz
