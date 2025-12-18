// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// Define XR_NO_PROTOTYPES to prevent OpenXR headers from declaring function prototypes
// This forces us to use xrGetInstanceProcAddr for all OpenXR functions
#define XR_NO_PROTOTYPES

#include <openxr/openxr.h>

#include <cassert>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>

// When XR_NO_PROTOTYPES is defined, even xrGetInstanceProcAddr is not declared
// We need to manually declare it here so we can bootstrap the dynamic loading
// This will use whatever OpenXR loader is already loaded in the process
extern "C"
{
    XRAPI_ATTR XrResult XRAPI_CALL xrGetInstanceProcAddr(XrInstance instance,
                                                         const char* name,
                                                         PFN_xrVoidFunction* function);
}

namespace core
{

// Helper structure to hold dynamically loaded core OpenXR function pointers
// These are the core functions used by the trackers (not extensions)
struct OpenXRCoreFunctions
{
    // Core functions needed by trackers
    PFN_xrGetSystem xrGetSystem;
    PFN_xrGetSystemProperties xrGetSystemProperties;
    PFN_xrCreateReferenceSpace xrCreateReferenceSpace;
    PFN_xrDestroySpace xrDestroySpace;
    PFN_xrLocateSpace xrLocateSpace;

    // Action system functions (for controller tracking)
    PFN_xrStringToPath xrStringToPath;
    PFN_xrCreateActionSet xrCreateActionSet;
    PFN_xrDestroyActionSet xrDestroyActionSet;
    PFN_xrCreateAction xrCreateAction;
    PFN_xrSuggestInteractionProfileBindings xrSuggestInteractionProfileBindings;
    PFN_xrAttachSessionActionSets xrAttachSessionActionSets;
    PFN_xrCreateActionSpace xrCreateActionSpace;
    PFN_xrSyncActions xrSyncActions;
    PFN_xrGetActionStateBoolean xrGetActionStateBoolean;
    PFN_xrGetActionStateFloat xrGetActionStateFloat;
    PFN_xrGetActionStateVector2f xrGetActionStateVector2f;

    // Load all core functions from an instance using the provided xrGetInstanceProcAddr
    static OpenXRCoreFunctions load(XrInstance instance, PFN_xrGetInstanceProcAddr getProcAddr)
    {
        assert(getProcAddr);

        OpenXRCoreFunctions results{};
        bool success = true;

        success &=
            XR_SUCCEEDED(getProcAddr(instance, "xrGetSystem", reinterpret_cast<PFN_xrVoidFunction*>(&results.xrGetSystem)));
        success &= XR_SUCCEEDED(getProcAddr(
            instance, "xrGetSystemProperties", reinterpret_cast<PFN_xrVoidFunction*>(&results.xrGetSystemProperties)));
        success &= XR_SUCCEEDED(getProcAddr(
            instance, "xrCreateReferenceSpace", reinterpret_cast<PFN_xrVoidFunction*>(&results.xrCreateReferenceSpace)));
        success &=
            XR_SUCCEEDED(getProcAddr(instance, "xrDestroySpace", reinterpret_cast<PFN_xrVoidFunction*>(&results.xrDestroySpace)));
        success &=
            XR_SUCCEEDED(getProcAddr(instance, "xrLocateSpace", reinterpret_cast<PFN_xrVoidFunction*>(&results.xrLocateSpace)));

        if (!success)
        {
            throw std::runtime_error("Failed to load core OpenXR functions");
        }

        // Action system functions (optional, for controller tracking)
        // Note: These don't fail the load if not available, as they're only needed by controller tracker
        getProcAddr(instance, "xrStringToPath", reinterpret_cast<PFN_xrVoidFunction*>(&results.xrStringToPath));
        getProcAddr(instance, "xrCreateActionSet", reinterpret_cast<PFN_xrVoidFunction*>(&results.xrCreateActionSet));
        getProcAddr(instance, "xrDestroyActionSet", reinterpret_cast<PFN_xrVoidFunction*>(&results.xrDestroyActionSet));
        getProcAddr(instance, "xrCreateAction", reinterpret_cast<PFN_xrVoidFunction*>(&results.xrCreateAction));
        getProcAddr(instance, "xrSuggestInteractionProfileBindings",
                    reinterpret_cast<PFN_xrVoidFunction*>(&results.xrSuggestInteractionProfileBindings));
        getProcAddr(
            instance, "xrAttachSessionActionSets", reinterpret_cast<PFN_xrVoidFunction*>(&results.xrAttachSessionActionSets));
        getProcAddr(instance, "xrCreateActionSpace", reinterpret_cast<PFN_xrVoidFunction*>(&results.xrCreateActionSpace));
        getProcAddr(instance, "xrSyncActions", reinterpret_cast<PFN_xrVoidFunction*>(&results.xrSyncActions));
        getProcAddr(instance, "xrGetActionStateBoolean", reinterpret_cast<PFN_xrVoidFunction*>(&results.xrGetActionStateBoolean));
        getProcAddr(instance, "xrGetActionStateFloat", reinterpret_cast<PFN_xrVoidFunction*>(&results.xrGetActionStateFloat));
        getProcAddr(
            instance, "xrGetActionStateVector2f", reinterpret_cast<PFN_xrVoidFunction*>(&results.xrGetActionStateVector2f));

        return results;
    }
};

// Smart pointer type aliases for OpenXR resources
using XrActionSetPtr = std::unique_ptr<std::remove_pointer_t<XrActionSet>, PFN_xrDestroyActionSet>;
using XrSpacePtr = std::unique_ptr<std::remove_pointer_t<XrSpace>, PFN_xrDestroySpace>;

// Create an action set with automatic cleanup - throws on failure
inline XrActionSetPtr createActionSet(const OpenXRCoreFunctions& funcs,
                                      XrInstance instance,
                                      const XrActionSetCreateInfo& createInfo)
{
    assert(funcs.xrDestroyActionSet);

    XrActionSet actionSet = XR_NULL_HANDLE;
    XrResult result = funcs.xrCreateActionSet(instance, &createInfo, &actionSet);

    if (XR_FAILED(result))
    {
        throw std::runtime_error("Failed to create action set: " + std::to_string(result));
    }

    return XrActionSetPtr(actionSet, funcs.xrDestroyActionSet);
}

// Create a reference space with automatic cleanup - throws on failure
inline XrSpacePtr createReferenceSpace(const OpenXRCoreFunctions& funcs,
                                       XrSession session,
                                       const XrReferenceSpaceCreateInfo& createInfo)
{
    assert(funcs.xrDestroySpace);

    XrSpace space = XR_NULL_HANDLE;
    XrResult result = funcs.xrCreateReferenceSpace(session, &createInfo, &space);

    if (XR_FAILED(result))
    {
        throw std::runtime_error("Failed to create reference space: " + std::to_string(result));
    }

    return XrSpacePtr(space, funcs.xrDestroySpace);
}

// Create an action space with automatic cleanup - throws on failure
inline XrSpacePtr createActionSpace(const OpenXRCoreFunctions& funcs,
                                    XrSession session,
                                    const XrActionSpaceCreateInfo* createInfo)
{
    assert(funcs.xrDestroySpace);

    XrSpace space = XR_NULL_HANDLE;
    XrResult result = funcs.xrCreateActionSpace(session, createInfo, &space);

    if (XR_FAILED(result))
    {
        throw std::runtime_error("Failed to create action space: " + std::to_string(result));
    }

    return XrSpacePtr(space, funcs.xrDestroySpace);
}

} // namespace core
