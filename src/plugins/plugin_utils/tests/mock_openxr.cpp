// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <openxr/XR_NVX1_device_interface.h>
#include <openxr/openxr.h>

#include <cstring>
#include <iostream>
#include <string>

// --- Mock Extension Functions ---

XRAPI_ATTR XrResult XRAPI_CALL mock_xrCreatePushDeviceNV(XrSession session,
                                                         const XrPushDeviceCreateInfoNV* createInfo,
                                                         const void* next,
                                                         XrPushDeviceNV* pushDevice)
{
    // Return a dummy handle (casted pointer)
    *pushDevice = (XrPushDeviceNV)0x100;
    return XR_SUCCESS;
}

XRAPI_ATTR XrResult XRAPI_CALL mock_xrDestroyPushDeviceNV(XrPushDeviceNV pushDevice)
{
    return XR_SUCCESS;
}

XRAPI_ATTR XrResult XRAPI_CALL mock_xrPushDevicePushHandTrackingNV(XrPushDeviceNV pushDevice,
                                                                   const XrPushDeviceHandTrackingDataNV* data)
{
    return XR_SUCCESS;
}

// --- Core Functions ---

extern "C"
{

    XRAPI_ATTR XrResult XRAPI_CALL xrCreateInstance(const XrInstanceCreateInfo* createInfo, XrInstance* instance)
    {
        *instance = (XrInstance)0x1;
        return XR_SUCCESS;
    }

    XRAPI_ATTR XrResult XRAPI_CALL xrDestroyInstance(XrInstance instance)
    {
        return XR_SUCCESS;
    }

    XRAPI_ATTR XrResult XRAPI_CALL xrGetSystem(XrInstance instance, const XrSystemGetInfo* getInfo, XrSystemId* systemId)
    {
        *systemId = 1;
        return XR_SUCCESS;
    }

    XRAPI_ATTR XrResult XRAPI_CALL xrCreateSession(XrInstance instance,
                                                   const XrSessionCreateInfo* createInfo,
                                                   XrSession* session)
    {
        *session = (XrSession)0x2;
        return XR_SUCCESS;
    }

    XRAPI_ATTR XrResult XRAPI_CALL xrDestroySession(XrSession session)
    {
        return XR_SUCCESS;
    }

    XRAPI_ATTR XrResult XRAPI_CALL xrCreateReferenceSpace(XrSession session,
                                                          const XrReferenceSpaceCreateInfo* createInfo,
                                                          XrSpace* space)
    {
        *space = (XrSpace)0x3;
        return XR_SUCCESS;
    }

    XRAPI_ATTR XrResult XRAPI_CALL xrBeginSession(XrSession session, const XrSessionBeginInfo* beginInfo)
    {
        return XR_SUCCESS;
    }

    // Actions
    XRAPI_ATTR XrResult XRAPI_CALL xrCreateActionSet(XrInstance instance,
                                                     const XrActionSetCreateInfo* createInfo,
                                                     XrActionSet* actionSet)
    {
        *actionSet = (XrActionSet)0x4;
        return XR_SUCCESS;
    }

    XRAPI_ATTR XrResult XRAPI_CALL xrDestroyActionSet(XrActionSet actionSet)
    {
        return XR_SUCCESS;
    }

    XRAPI_ATTR XrResult XRAPI_CALL xrStringToPath(XrInstance instance, const char* pathString, XrPath* path)
    {
        *path = (XrPath)1; // Just return constant
        return XR_SUCCESS;
    }

    XRAPI_ATTR XrResult XRAPI_CALL xrCreateAction(XrActionSet actionSet,
                                                  const XrActionCreateInfo* createInfo,
                                                  XrAction* action)
    {
        *action = (XrAction)0x5;
        return XR_SUCCESS;
    }

    XRAPI_ATTR XrResult XRAPI_CALL xrSuggestInteractionProfileBindings(
        XrInstance instance, const XrInteractionProfileSuggestedBinding* suggestedBindings)
    {
        return XR_SUCCESS;
    }

    XRAPI_ATTR XrResult XRAPI_CALL xrAttachSessionActionSets(XrSession session,
                                                             const XrSessionActionSetsAttachInfo* attachInfo)
    {
        return XR_SUCCESS;
    }

    XRAPI_ATTR XrResult XRAPI_CALL xrCreateActionSpace(XrSession session,
                                                       const XrActionSpaceCreateInfo* createInfo,
                                                       XrSpace* space)
    {
        *space = (XrSpace)0x6;
        return XR_SUCCESS;
    }

    XRAPI_ATTR XrResult XRAPI_CALL xrDestroySpace(XrSpace space)
    {
        return XR_SUCCESS;
    }

    XRAPI_ATTR XrResult XRAPI_CALL xrSyncActions(XrSession session, const XrActionsSyncInfo* syncInfo)
    {
        return XR_SUCCESS;
    }

    XRAPI_ATTR XrResult XRAPI_CALL xrLocateSpace(XrSpace space, XrSpace baseSpace, XrTime time, XrSpaceLocation* location)
    {
        location->locationFlags = XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT;
        location->pose.position = { 0.0f, 0.0f, 0.0f };
        location->pose.orientation = { 0.0f, 0.0f, 0.0f, 1.0f };
        return XR_SUCCESS;
    }

    XRAPI_ATTR XrResult XRAPI_CALL xrGetActionStateBoolean(XrSession session,
                                                           const XrActionStateGetInfo* getInfo,
                                                           XrActionStateBoolean* state)
    {
        state->isActive = XR_TRUE;
        state->currentState = XR_FALSE;
        return XR_SUCCESS;
    }

    // Extension loading
    XRAPI_ATTR XrResult XRAPI_CALL xrGetInstanceProcAddr(XrInstance instance, const char* name, PFN_xrVoidFunction* function)
    {
        std::string s_name(name);
        if (s_name == "xrCreatePushDeviceNV")
        {
            *function = (PFN_xrVoidFunction)mock_xrCreatePushDeviceNV;
            return XR_SUCCESS;
        }
        if (s_name == "xrDestroyPushDeviceNV")
        {
            *function = (PFN_xrVoidFunction)mock_xrDestroyPushDeviceNV;
            return XR_SUCCESS;
        }
        if (s_name == "xrPushDevicePushHandTrackingNV")
        {
            *function = (PFN_xrVoidFunction)mock_xrPushDevicePushHandTrackingNV;
            return XR_SUCCESS;
        }

        return XR_ERROR_FUNCTION_UNSUPPORTED;
    }

} // extern "C"
