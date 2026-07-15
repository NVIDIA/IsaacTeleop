// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <map>
#include <string>

namespace core
{

// Per-tracker vendor selection for a live session.
//
// A vendored tracker (e.g. full body) can be sourced from more than one backend
// (native XR hardware, an external pushed-tensor plugin, ...). The vendor is
// chosen at live-session construction, not baked into the tracker marker, so a
// single tracker type stays vendor-agnostic.
//
// `id` is a string so new pre-built plugin vendors can be selected without
// recompiling core (e.g. "body.pico-xr"). `params` carries vendor-specific
// settings as free-form strings, mirroring plugin CLI arguments
// (e.g. {"max_flatbuffer_size": "16384"}).
struct TrackerVendor
{
    std::string id;
    std::map<std::string, std::string> params;
};

} // namespace core
