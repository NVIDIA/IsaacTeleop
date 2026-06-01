// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/viz/xr/xr_runtime.hpp"

#include <openxr/openxr.h>

#include <vector>

namespace viz
{

std::vector<std::string> enumerate_openxr_instance_extensions() noexcept
{
    uint32_t count = 0;
    if (xrEnumerateInstanceExtensionProperties(nullptr, 0, &count, nullptr) != XR_SUCCESS || count == 0)
    {
        return {};
    }
    std::vector<XrExtensionProperties> props(count);
    for (auto& p : props)
    {
        p.type = XR_TYPE_EXTENSION_PROPERTIES;
        p.next = nullptr;
    }
    uint32_t written = 0;
    if (xrEnumerateInstanceExtensionProperties(nullptr, count, &written, props.data()) != XR_SUCCESS)
    {
        return {};
    }
    std::vector<std::string> names;
    names.reserve(written);
    for (uint32_t i = 0; i < written; ++i)
    {
        names.emplace_back(props[i].extensionName);
    }
    return names;
}

bool openxr_loader_available() noexcept
{
    return !enumerate_openxr_instance_extensions().empty();
}

} // namespace viz
