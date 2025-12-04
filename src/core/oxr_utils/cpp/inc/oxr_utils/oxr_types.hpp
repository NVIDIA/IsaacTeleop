// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>

namespace core
{

// Wrapper for OpenXR session handles
// This struct is used to pass OpenXR session information between modules
// without requiring them to link against the OpenXR loader library
struct OpenXRSessionHandles
{
    XrInstance instance;
    XrSession session;
    XrSpace space;
    PFN_xrGetInstanceProcAddr xrGetInstanceProcAddr;

    OpenXRSessionHandles()
        : instance(XR_NULL_HANDLE), session(XR_NULL_HANDLE), space(XR_NULL_HANDLE), xrGetInstanceProcAddr(nullptr)
    {
    }

    OpenXRSessionHandles(XrInstance inst, XrSession sess, XrSpace sp, PFN_xrGetInstanceProcAddr procAddr)
        : instance(inst), session(sess), space(sp), xrGetInstanceProcAddr(procAddr)
    {
    }
};

} // namespace core
