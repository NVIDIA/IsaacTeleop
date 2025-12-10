// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Hand tracking data injection via push devices

#include "hand_injector.hpp"

#include <cstring>
#include <stdexcept>

HandInjector::HandInjector(XrInstance instance,
                           XrSession session,
                           XrSpace left_controller_space,
                           XrSpace right_controller_space)
{
    initialize(instance, session, left_controller_space, right_controller_space);
}

HandInjector::HandInjector(XrInstance instance, XrSession session, XrSpace reference_space)
{
    initialize(instance, session, reference_space, reference_space);
}

HandInjector::~HandInjector()
{
    cleanup();
}

void HandInjector::initialize(XrInstance instance, XrSession session, XrSpace left_space, XrSpace right_space)
{
    load_functions(instance);
    create_device(session, left_space, XR_HAND_LEFT_EXT, left_device_);
    create_device(session, right_space, XR_HAND_RIGHT_EXT, right_device_);
}

void HandInjector::load_functions(XrInstance instance)
{
    if (XR_FAILED(xrGetInstanceProcAddr(
            instance, "xrCreatePushDeviceNV", reinterpret_cast<PFN_xrVoidFunction*>(&pfn_create_))) ||
        XR_FAILED(xrGetInstanceProcAddr(
            instance, "xrDestroyPushDeviceNV", reinterpret_cast<PFN_xrVoidFunction*>(&pfn_destroy_))) ||
        XR_FAILED(xrGetInstanceProcAddr(
            instance, "xrPushDevicePushHandTrackingNV", reinterpret_cast<PFN_xrVoidFunction*>(&pfn_push_))))
    {
        throw std::runtime_error("Push device extension (XR_NVX1_device_interface_base) not available");
    }
}

void HandInjector::create_device(XrSession session, XrSpace base_space, XrHandEXT hand, XrPushDeviceNV& device)
{
    XrPushDeviceHandTrackingInfoNV hand_info{ XR_TYPE_PUSH_DEVICE_HAND_TRACKING_INFO_NV };
    hand_info.hand = hand;
    hand_info.jointSet = XR_HAND_JOINT_SET_DEFAULT_EXT;

    XrPushDeviceCreateInfoNV create_info{ XR_TYPE_PUSH_DEVICE_CREATE_INFO_NV };
    create_info.next = &hand_info;
    create_info.baseSpace = base_space;
    create_info.deviceTypeUuidValid = XR_FALSE;
    create_info.deviceUuidValid = XR_FALSE;
    strcpy(create_info.localizedName, hand == XR_HAND_LEFT_EXT ? "Left Hand" : "Right Hand");
    strcpy(create_info.serial, hand == XR_HAND_LEFT_EXT ? "LEFT" : "RIGHT");

    XrResult result = pfn_create_(session, &create_info, nullptr, &device);
    if (XR_FAILED(result))
    {
        cleanup();
        throw std::runtime_error("Failed to create push device for " +
                                 std::string(hand == XR_HAND_LEFT_EXT ? "left" : "right") + " hand");
    }
}

bool HandInjector::push_left(const XrHandJointLocationEXT* joints, XrTime timestamp)
{
    if (left_device_ == XR_NULL_HANDLE)
        return false;

    XrPushDeviceHandTrackingDataNV data{ XR_TYPE_PUSH_DEVICE_HAND_TRACKING_DATA_NV };
    data.timestamp = timestamp;
    data.jointCount = XR_HAND_JOINT_COUNT_EXT;
    data.jointLocations = joints;

    return XR_SUCCEEDED(pfn_push_(left_device_, &data));
}

bool HandInjector::push_right(const XrHandJointLocationEXT* joints, XrTime timestamp)
{
    if (right_device_ == XR_NULL_HANDLE)
        return false;

    XrPushDeviceHandTrackingDataNV data{ XR_TYPE_PUSH_DEVICE_HAND_TRACKING_DATA_NV };
    data.timestamp = timestamp;
    data.jointCount = XR_HAND_JOINT_COUNT_EXT;
    data.jointLocations = joints;

    return XR_SUCCEEDED(pfn_push_(right_device_, &data));
}

void HandInjector::cleanup()
{
    if (pfn_destroy_)
    {
        if (left_device_ != XR_NULL_HANDLE)
        {
            pfn_destroy_(left_device_);
            left_device_ = XR_NULL_HANDLE;
        }
        if (right_device_ != XR_NULL_HANDLE)
        {
            pfn_destroy_(right_device_);
            right_device_ = XR_NULL_HANDLE;
        }
    }
}
