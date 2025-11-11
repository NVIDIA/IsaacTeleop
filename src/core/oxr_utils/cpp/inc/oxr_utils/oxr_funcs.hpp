#pragma once

// Define XR_NO_PROTOTYPES to prevent OpenXR headers from declaring function prototypes
// This forces us to use xrGetInstanceProcAddr for all OpenXR functions
#define XR_NO_PROTOTYPES

#include <openxr/openxr.h>

// When XR_NO_PROTOTYPES is defined, even xrGetInstanceProcAddr is not declared
// We need to manually declare it here so we can bootstrap the dynamic loading
// This will use whatever OpenXR loader is already loaded in the process
extern "C" {
    XRAPI_ATTR XrResult XRAPI_CALL xrGetInstanceProcAddr(
        XrInstance instance,
        const char* name,
        PFN_xrVoidFunction* function);
}

namespace oxr {

// Helper structure to hold dynamically loaded core OpenXR function pointers
// These are the core functions used by the trackers (not extensions)
struct OpenXRCoreFunctions {
    // Core functions needed by trackers
    PFN_xrGetSystem xrGetSystem;
    PFN_xrGetSystemProperties xrGetSystemProperties;
    PFN_xrCreateReferenceSpace xrCreateReferenceSpace;
    PFN_xrDestroySpace xrDestroySpace;
    PFN_xrLocateSpace xrLocateSpace;
    
    OpenXRCoreFunctions()
        : xrGetSystem(nullptr)
        , xrGetSystemProperties(nullptr)
        , xrCreateReferenceSpace(nullptr)
        , xrDestroySpace(nullptr)
        , xrLocateSpace(nullptr) {}
    
    // Load all core functions from an instance using the provided xrGetInstanceProcAddr
    bool load(XrInstance instance, PFN_xrGetInstanceProcAddr getProcAddr) {
        if (!getProcAddr) {
            return false;
        }
        
        bool success = true;
        
        success &= XR_SUCCEEDED(getProcAddr(instance, "xrGetSystem",
            reinterpret_cast<PFN_xrVoidFunction*>(&xrGetSystem)));
        success &= XR_SUCCEEDED(getProcAddr(instance, "xrGetSystemProperties",
            reinterpret_cast<PFN_xrVoidFunction*>(&xrGetSystemProperties)));
        success &= XR_SUCCEEDED(getProcAddr(instance, "xrCreateReferenceSpace",
            reinterpret_cast<PFN_xrVoidFunction*>(&xrCreateReferenceSpace)));
        success &= XR_SUCCEEDED(getProcAddr(instance, "xrDestroySpace",
            reinterpret_cast<PFN_xrVoidFunction*>(&xrDestroySpace)));
        success &= XR_SUCCEEDED(getProcAddr(instance, "xrLocateSpace",
            reinterpret_cast<PFN_xrVoidFunction*>(&xrLocateSpace)));
        
        return success;
    }
};

} // namespace oxr

