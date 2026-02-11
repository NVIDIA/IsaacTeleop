// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>

/*!
 * Container for OpenXR instance, system, and session used by this example.
 */
class OpenXRBundle
{
public:
    XrInstance instance{ XR_NULL_HANDLE };
    XrSystemId system_id{ XR_NULL_SYSTEM_ID };
    XrSession session{ XR_NULL_HANDLE };

protected:
    virtual ~OpenXRBundle() = default;
};
