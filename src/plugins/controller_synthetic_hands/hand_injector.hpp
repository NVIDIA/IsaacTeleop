// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Hand tracking data injection via push devices
#pragma once

#include "XR_NVX1_device_interface.h"

#include <openxr/openxr.h>

class HandInjector
{
public:
    HandInjector(XrInstance instance, XrSession session, XrSpace left_controller_space, XrSpace right_controller_space);

    HandInjector(XrInstance instance, XrSession session, XrSpace reference_space);

    ~HandInjector();

    HandInjector(const HandInjector&) = delete;
    HandInjector& operator=(const HandInjector&) = delete;

    bool push_left(const XrHandJointLocationEXT* joints, XrTime timestamp);
    bool push_right(const XrHandJointLocationEXT* joints, XrTime timestamp);

private:
    void initialize(XrInstance instance, XrSession session, XrSpace left_space, XrSpace right_space);
    void load_functions(XrInstance instance);
    void create_device(XrSession session, XrSpace base_space, XrHandEXT hand, XrPushDeviceNV& device);
    void cleanup();

    XrPushDeviceNV left_device_ = XR_NULL_HANDLE;
    XrPushDeviceNV right_device_ = XR_NULL_HANDLE;

    PFN_xrCreatePushDeviceNV pfn_create_ = nullptr;
    PFN_xrDestroyPushDeviceNV pfn_destroy_ = nullptr;
    PFN_xrPushDevicePushHandTrackingNV pfn_push_ = nullptr;
};
