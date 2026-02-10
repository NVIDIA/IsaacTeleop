// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Hand tracking data injection via push devices

#include <oxr_utils/oxr_funcs.hpp>
#include <plugin_utils/hand_injector.hpp>

#include <cstring>
#include <stdexcept>
#include <string>

namespace plugin_utils
{

namespace
{
void CheckXrResult(XrResult result, const char* message)
{
    if (XR_FAILED(result))
    {
        throw std::runtime_error(std::string(message) + " failed with XrResult: " + std::to_string(result));
    }
}
}

HandInjector::HandInjector(XrInstance instance,
                           XrSession session,
                           XrSpace left_controller_space,
                           XrSpace right_controller_space)
{
    try
    {
        initialize(instance, session, left_controller_space, right_controller_space);
    }
    catch (...)
    {
        cleanup();
        throw;
    }
}

HandInjector::HandInjector(XrInstance instance, XrSession session, XrSpace reference_space)
{
    try
    {
        initialize(instance, session, reference_space, reference_space);
    }
    catch (...)
    {
        cleanup();
        throw;
    }
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
    core::loadExtensionFunction(
        instance, xrGetInstanceProcAddr, "xrCreatePushDeviceNV", reinterpret_cast<PFN_xrVoidFunction*>(&pfn_create_));
    core::loadExtensionFunction(
        instance, xrGetInstanceProcAddr, "xrDestroyPushDeviceNV", reinterpret_cast<PFN_xrVoidFunction*>(&pfn_destroy_));
    core::loadExtensionFunction(instance, xrGetInstanceProcAddr, "xrPushDevicePushHandTrackingNV",
                                reinterpret_cast<PFN_xrVoidFunction*>(&pfn_push_));
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

    CheckXrResult(pfn_create_(session, &create_info, nullptr, &device),
                  (std::string("xrCreatePushDeviceNV(") + (hand == XR_HAND_LEFT_EXT ? "left" : "right") + ")").c_str());
}

void HandInjector::push_left(const XrHandJointLocationEXT* joints, XrTime timestamp)
{
    if (left_device_ == XR_NULL_HANDLE)
    {
        throw std::runtime_error("Left push device not initialized");
    }

    XrPushDeviceHandTrackingDataNV data{ XR_TYPE_PUSH_DEVICE_HAND_TRACKING_DATA_NV };
    data.timestamp = timestamp;
    data.jointCount = XR_HAND_JOINT_COUNT_EXT;
    data.jointLocations = joints;

    CheckXrResult(pfn_push_(left_device_, &data), "xrPushDevicePushHandTrackingNV(left)");
}

void HandInjector::push_right(const XrHandJointLocationEXT* joints, XrTime timestamp)
{
    if (right_device_ == XR_NULL_HANDLE)
    {
        throw std::runtime_error("Right push device not initialized");
    }

    XrPushDeviceHandTrackingDataNV data{ XR_TYPE_PUSH_DEVICE_HAND_TRACKING_DATA_NV };
    data.timestamp = timestamp;
    data.jointCount = XR_HAND_JOINT_COUNT_EXT;
    data.jointLocations = joints;

    CheckXrResult(pfn_push_(right_device_, &data), "xrPushDevicePushHandTrackingNV(right)");
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

} // namespace plugin_utils
