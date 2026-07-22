// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Backend-independent OgloBleClient helpers (always compiled, no BLE deps).

#include "oglo_ble_client.hpp"

namespace plugins
{
namespace oglo_tactile
{

std::string advertised_name_for(Side side)
{
    switch (side)
    {
    case Side::Left:
        return "OGLO LEFT";
    case Side::Right:
        return "OGLO RIGHT";
    case Side::Unknown:
    default:
        return "OGLO";
    }
}

} // namespace oglo_tactile
} // namespace plugins
