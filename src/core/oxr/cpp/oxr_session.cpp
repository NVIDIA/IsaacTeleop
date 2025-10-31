#include "inc/oxr/oxr_session.hpp"

#include <iostream>
#include <cstring>
#include <time.h>

namespace oxr {

OpenXRSession::OpenXRSession()
    : instance_(XR_NULL_HANDLE),
      system_id_(XR_NULL_SYSTEM_ID),
      session_(XR_NULL_HANDLE),
      space_(XR_NULL_HANDLE),
      session_state_(XR_SESSION_STATE_UNKNOWN),
      predicted_time_(0),
      session_running_(false),
      pfn_convert_timespec_(nullptr) {
}

OpenXRSession::~OpenXRSession() {
    shutdown();
}

bool OpenXRSession::initialize(const std::string& app_name, const std::vector<std::string>& extensions) {
    if (!create_instance(app_name, extensions)) {
        return false;
    }
    
    if (!create_system()) {
        return false;
    }
    
    if (!create_session()) {
        return false;
    }
    
    if (!create_reference_space()) {
        return false;
    }
    
    return true;
}

void OpenXRSession::shutdown() {
    if (space_ != XR_NULL_HANDLE) {
        xrDestroySpace(space_);
        space_ = XR_NULL_HANDLE;
    }
    
    if (session_ != XR_NULL_HANDLE) {
        xrDestroySession(session_);
        session_ = XR_NULL_HANDLE;
    }
    
    if (instance_ != XR_NULL_HANDLE) {
        xrDestroyInstance(instance_);
        instance_ = XR_NULL_HANDLE;
    }
}

bool OpenXRSession::create_instance(const std::string& app_name, const std::vector<std::string>& extensions) {
    XrInstanceCreateInfo create_info{XR_TYPE_INSTANCE_CREATE_INFO};
    create_info.applicationInfo.apiVersion = XR_CURRENT_API_VERSION;
    strncpy(create_info.applicationInfo.applicationName, app_name.c_str(), XR_MAX_APPLICATION_NAME_SIZE - 1);
    strncpy(create_info.applicationInfo.engineName, "OXR_Tracking", XR_MAX_ENGINE_NAME_SIZE - 1);
    
    // Convert vector<string> to array of const char* for OpenXR API
    std::vector<const char*> extension_ptrs;
    for (const auto& ext : extensions) {
        extension_ptrs.push_back(ext.c_str());
    }
    
    create_info.enabledExtensionCount = static_cast<uint32_t>(extension_ptrs.size());
    create_info.enabledExtensionNames = extension_ptrs.empty() ? nullptr : extension_ptrs.data();
    
    XrResult result = xrCreateInstance(&create_info, &instance_);
    if (XR_FAILED(result)) {
        std::cerr << "Failed to create OpenXR instance: " << result << std::endl;
        return false;
    }
    
    // Get extension function pointers
    xrGetInstanceProcAddr(
        instance_,
        "xrConvertTimespecTimeToTimeKHR",
        reinterpret_cast<PFN_xrVoidFunction*>(&pfn_convert_timespec_)
    );
    
    if (!pfn_convert_timespec_) {
        std::cerr << "Warning: xrConvertTimespecTimeToTimeKHR not available" << std::endl;
    } else {
        std::cout << "✓ xrConvertTimespecTimeToTimeKHR available" << std::endl;
    }
    
    std::cout << "Created OpenXR instance" << std::endl;
    return true;
}

bool OpenXRSession::create_system() {
    XrSystemGetInfo system_info{XR_TYPE_SYSTEM_GET_INFO};
    system_info.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;
    
    XrResult result = xrGetSystem(instance_, &system_info, &system_id_);
    if (XR_FAILED(result)) {
        std::cerr << "Failed to get OpenXR system: " << result << std::endl;
        return false;
    }
    
    std::cout << "Created OpenXR system" << std::endl;
    return true;
}

bool OpenXRSession::create_session() {
    // XrSessionCreateInfoOverlayEXTX structure for overlay/headless mode
    // This is a custom extension structure - defining it inline since it may not be in headers
    struct XrSessionCreateInfoOverlayEXTX {
        XrStructureType type;
        const void* next;
        uint32_t createFlags;
        uint32_t sessionLayersPlacement;
    };
    
    XrSessionCreateInfoOverlayEXTX overlay_info{};
    overlay_info.type = (XrStructureType)1000033000;  // XR_TYPE_SESSION_CREATE_INFO_OVERLAY_EXTX
    overlay_info.next = nullptr;
    overlay_info.createFlags = 0;
    overlay_info.sessionLayersPlacement = 0;
    
    XrSessionCreateInfo create_info{XR_TYPE_SESSION_CREATE_INFO};
    create_info.next = &overlay_info;  // Chain overlay info for headless mode
    create_info.systemId = system_id_;
    
    XrResult result = xrCreateSession(instance_, &create_info, &session_);
    if (XR_FAILED(result)) {
        std::cerr << "Failed to create OpenXR session: " << result << std::endl;
        return false;
    }
    
    std::cout << "Created OpenXR session (headless mode)" << std::endl;
    return true;
}

bool OpenXRSession::create_reference_space() {
    XrReferenceSpaceCreateInfo create_info{XR_TYPE_REFERENCE_SPACE_CREATE_INFO};
    create_info.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_STAGE;
    create_info.poseInReferenceSpace.orientation.w = 1.0f;
    
    XrResult result = xrCreateReferenceSpace(session_, &create_info, &space_);
    if (XR_FAILED(result)) {
        std::cerr << "Failed to create reference space: " << result << std::endl;
        return false;
    }
    
    std::cout << "Created reference space" << std::endl;
    return true;
}

bool OpenXRSession::poll_events() {
    XrEventDataBuffer event{XR_TYPE_EVENT_DATA_BUFFER};
    
    while (xrPollEvent(instance_, &event) == XR_SUCCESS) {
        switch (event.type) {
            case XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED: {
                auto* state_event = reinterpret_cast<XrEventDataSessionStateChanged*>(&event);
                session_state_ = state_event->state;
                
                std::cout << "Session state changed to: " << session_state_ << std::endl;
                
                switch (session_state_) {
                    case XR_SESSION_STATE_READY: {
                        XrSessionBeginInfo begin_info{XR_TYPE_SESSION_BEGIN_INFO};
                        begin_info.primaryViewConfigurationType = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
                        xrBeginSession(session_, &begin_info);
                        session_running_ = true;
                        break;
                    }
                    case XR_SESSION_STATE_STOPPING:
                        xrEndSession(session_);
                        session_running_ = false;
                        break;
                    case XR_SESSION_STATE_EXITING:
                    case XR_SESSION_STATE_LOSS_PENDING:
                        return false;
                    default:
                        break;
                }
                break;
            }
            case XR_TYPE_EVENT_DATA_INSTANCE_LOSS_PENDING:
                return false;
            default:
                break;
        }
        
        event.type = XR_TYPE_EVENT_DATA_BUFFER;
    }
    
    return true;
}

bool OpenXRSession::update_time() {
    // Get current time using system clock and convert to XR time
    if (!pfn_convert_timespec_) {
        std::cerr << "xrConvertTimespecTimeToTimeKHR not available" << std::endl;
        return false;
    }
    
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    
    XrResult result = pfn_convert_timespec_(instance_, &ts, &predicted_time_);
    if (XR_FAILED(result)) {
        std::cerr << "xrConvertTimespecTimeToTimeKHR failed: " << result << std::endl;
        return false;
    }
    
    return true;
}

} // namespace oxr
