// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <string>
#include <vector>

namespace viz
{

// Phase-1 minimal surface: query the OpenXR loader for what's
// available before we commit to a graphics-bound session. Useful as
// a sanity check that the loader links and the runtime is reachable.
//
// XrInstance / XrSession / XrSpace creation lives in a separate
// XrSession class added in Phase 2 alongside Vulkan device negotiation.

// Returns the names of every instance extension the OpenXR loader
// advertises (across all visible API layers). Always queryable —
// requires no XrInstance and no runtime contact. Returns an empty
// vector if the loader itself is missing.
std::vector<std::string> enumerate_openxr_instance_extensions() noexcept;

// True if at least one OpenXR extension is advertised by the loader.
// A handy "is OpenXR linked at all?" check for tests.
bool openxr_loader_available() noexcept;

} // namespace viz
