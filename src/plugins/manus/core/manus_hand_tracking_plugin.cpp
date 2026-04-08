// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <core/manus_hand_tracking_plugin.hpp>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/math.hpp>
#include <oxr_utils/pose_conversions.hpp>
#include <plugin_utils/hand_injector.hpp>

#include <ManusSDK.h>
#include <ManusSDKTypeInitializers.h>
#include <algorithm>
#include <chrono>
#include <iostream>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <vector>


namespace plugins
{
namespace manus
{

namespace
{

// Returns true if the OpenXR loader/runtime advertises the given extension.
// xrEnumerateInstanceExtensionProperties is a loader-level function that can be
// called before any XrInstance exists, so this is safe to use at init time.
bool is_openxr_extension_supported(const char* ext_name)
{
    uint32_t count = 0;
    if (XR_FAILED(xrEnumerateInstanceExtensionProperties(nullptr, 0, &count, nullptr)))
    {
        return false;
    }
    std::vector<XrExtensionProperties> props(count, XrExtensionProperties{ XR_TYPE_EXTENSION_PROPERTIES });
    if (XR_FAILED(xrEnumerateInstanceExtensionProperties(nullptr, count, &count, props.data())))
    {
        return false;
    }
    return std::any_of(props.begin(), props.end(), [ext_name](const XrExtensionProperties& p)
    {
        return std::string(p.extensionName) == ext_name;
    });
}

} // anonymous namespace

static constexpr XrPosef kLeftHandOffset = { { -0.70710678f, -0.5f, 0.0f, 0.5f }, { -0.1f, 0.02f, -0.02f } };
static constexpr XrPosef kRightHandOffset = { { -0.70710678f, 0.5f, 0.0f, 0.5f }, { 0.1f, 0.02f, -0.02f } };

ManusTracker& ManusTracker::instance(const std::string& app_name) noexcept(false)
{
    static ManusTracker s(app_name);
    return s;
}

void ManusTracker::update()
{
    if (!m_deviceio_session)
    {
        // OpenXR unavailable — nothing to update for positioning/injection
        return;
    }

    // Update DeviceIOSession which handles time conversion and tracker updates internally
    m_deviceio_session->update();

    inject_hand_data();
}

std::vector<SkeletonNode> ManusTracker::get_left_hand_nodes() const
{
    std::lock_guard<std::mutex> lock(m_skeleton_mutex);
    return m_left_hand_nodes;
}

std::vector<SkeletonNode> ManusTracker::get_right_hand_nodes() const
{
    std::lock_guard<std::mutex> lock(m_skeleton_mutex);
    return m_right_hand_nodes;
}

std::vector<NodeInfo> ManusTracker::get_left_node_info() const
{
    std::lock_guard<std::mutex> lock(m_skeleton_mutex);
    return m_left_node_info;
}

std::vector<NodeInfo> ManusTracker::get_right_node_info() const
{
    std::lock_guard<std::mutex> lock(m_skeleton_mutex);
    return m_right_node_info;
}

ManusTracker::ManusTracker(const std::string& app_name) noexcept(false)
{
    initialize(app_name);
}

ManusTracker::~ManusTracker()
{
    {
        std::lock_guard<std::mutex> lock(m_lifecycle_mutex);
        if (!m_initialized)
        {
            return;
        }
        m_initialized = false;
    }

    shutdown_sdk();
}

void ManusTracker::initialize(const std::string& app_name) noexcept(false)
{
    std::cout << "[Manus] Initializing SDK..." << std::endl;
    const SDKReturnCode t_InitializeResult = CoreSdk_InitializeIntegrated();
    if (t_InitializeResult != SDKReturnCode::SDKReturnCode_Success)
    {
        throw std::runtime_error("Failed to initialize Manus SDK, error code: " +
                                 std::to_string(static_cast<int>(t_InitializeResult)));
    }
    std::cout << "[Manus] SDK initialized successfully" << std::endl;

    RegisterCallbacks();

    CoordinateSystemVUH t_VUH;
    CoordinateSystemVUH_Init(&t_VUH);
    t_VUH.handedness = Side::Side_Right;
    t_VUH.up = AxisPolarity::AxisPolarity_PositiveY;
    t_VUH.view = AxisView::AxisView_ZToViewer;
    t_VUH.unitScale = 1.0f;

    std::cout << "[Manus] Setting up coordinate system (Y-up, right-handed, meters)..." << std::endl;
    const SDKReturnCode t_CoordinateResult = CoreSdk_InitializeCoordinateSystemWithVUH(t_VUH, true);

    if (t_CoordinateResult != SDKReturnCode::SDKReturnCode_Success)
    {
        throw std::runtime_error("Failed to initialize Manus SDK coordinate system, error code: " +
                                 std::to_string(static_cast<int>(t_CoordinateResult)));
    }
    std::cout << "[Manus] Coordinate system initialized successfully" << std::endl;

    ConnectToGloves();

    std::string error_msg = "Unknown error";
    bool success = false;

    try
    {
        // Create ControllerTracker unconditionally; HandTracker requires
        // XR_EXT_hand_tracking which is optional — only add it when the runtime
        // advertises support so xrCreateInstance does not fail with
        // XR_ERROR_EXTENSION_NOT_PRESENT on runtimes that lack the extension.
        m_controller_tracker = std::make_shared<core::ControllerTracker>();
        std::vector<std::shared_ptr<core::ITracker>> trackers = { m_controller_tracker };

        const bool hand_tracking_supported = is_openxr_extension_supported(XR_EXT_HAND_TRACKING_EXTENSION_NAME);
        if (hand_tracking_supported)
        {
            m_hand_tracker = std::make_shared<core::HandTracker>();
            trackers.push_back(m_hand_tracker);
        }
        else
        {
            std::cout << "[Manus] " << XR_EXT_HAND_TRACKING_EXTENSION_NAME
                      << " is not supported by the current runtime; HandTracker will not be created."
                      << std::endl;
        }

        // Get required extensions from trackers
        auto extensions = core::DeviceIOSession::get_required_extensions(trackers);
        extensions.push_back(XR_NVX1_DEVICE_INTERFACE_BASE_EXTENSION_NAME);

        // XR_MNDX_XDEV_SPACE_EXTENSION_NAME is optional: it enables optical (HMD) hand
        // tracking as a higher-quality wrist source. If the runtime does not advertise
        // it we fall back to controller-based tracking instead of crashing.
        const bool xdev_extension_supported = is_openxr_extension_supported(XR_MNDX_XDEV_SPACE_EXTENSION_NAME);
        if (xdev_extension_supported)
        {
            extensions.push_back(XR_MNDX_XDEV_SPACE_EXTENSION_NAME);
        }
        else
        {
            std::cout << "[Manus] " << XR_MNDX_XDEV_SPACE_EXTENSION_NAME
                      << " is not supported by the current runtime; optical hand tracking"
                      << " will not be available and controller fallback will be used."
                      << std::endl;
        }

        // Create session with required extensions - constructor automatically begins the session
        m_session = std::make_shared<core::OpenXRSession>(app_name, extensions);
        m_handles = m_session->get_handles();

        // Initialize time converter now that handles are ready
        m_time_converter.emplace(m_handles);

        // Initialize hand injectors (one per hand)
        m_left_injector = std::make_unique<plugin_utils::HandInjector>(m_handles.instance, m_handles.session, XR_HAND_LEFT_EXT, m_handles.space);
        m_right_injector = std::make_unique<plugin_utils::HandInjector>(m_handles.instance, m_handles.session, XR_HAND_RIGHT_EXT, m_handles.space);

        m_deviceio_session = core::DeviceIOSession::run(trackers, m_handles);

        // Only attempt XDev hand tracker setup when the extension was actually enabled.
        // Skipping here avoids calling xrGetInstanceProcAddr for MNDX entry points that
        // the runtime would not have loaded.
        if (xdev_extension_supported)
        {
            initialize_xdev_hand_trackers();
        }

        std::cout << "[Manus] Initialized with wrist source: "
                  << (m_xdev_available ? "HandTracking" : "Controllers")
                  << std::endl;

        success = true;
    }
    catch (const std::exception& e)
    {
        error_msg = e.what();
    }

    if (!success)
    {
        std::cerr << "[Manus] Warning: OpenXR initialization failed: " << error_msg << std::endl;
        std::cerr << "[Manus] Continuing in Manus-only mode (no hand injection or OpenXR positioning)." << std::endl;
    }

    std::lock_guard<std::mutex> lock(m_lifecycle_mutex);
    m_initialized = true;
}


void ManusTracker::shutdown_sdk()
{
    // Cleanup XDev hand trackers first
    cleanup_xdev_hand_trackers();

    CoreSdk_RegisterCallbackForRawSkeletonStream(nullptr);
    CoreSdk_RegisterCallbackForLandscapeStream(nullptr);
    CoreSdk_RegisterCallbackForErgonomicsStream(nullptr);
    DisconnectFromGloves();
    CoreSdk_ShutDown();
}

void ManusTracker::RegisterCallbacks()
{
    CoreSdk_RegisterCallbackForRawSkeletonStream(OnSkeletonStream);
    CoreSdk_RegisterCallbackForLandscapeStream(OnLandscapeStream);
}

void ManusTracker::ConnectToGloves() noexcept(false)
{
    bool connected = false;
    const int max_attempts = 30; // Maximum connection attempts
    const auto retry_delay = std::chrono::milliseconds(1000); // 1 second delay between attempts
    int attempts = 0;

    std::cout << "Looking for Manus gloves..." << std::endl;

    while (!connected && attempts < max_attempts)
    {
        attempts++;

        if (const auto start_result = CoreSdk_LookForHosts(1, false); start_result != SDKReturnCode::SDKReturnCode_Success)
        {
            std::cerr << "Failed to look for hosts (attempt " << attempts << "/" << max_attempts << ")" << std::endl;
            std::this_thread::sleep_for(retry_delay);
            continue;
        }

        uint32_t number_of_hosts_found{};
        if (const auto number_result = CoreSdk_GetNumberOfAvailableHostsFound(&number_of_hosts_found);
            number_result != SDKReturnCode::SDKReturnCode_Success)
        {
            std::cerr << "Failed to get number of available hosts (attempt " << attempts << "/" << max_attempts << ")"
                      << std::endl;
            std::this_thread::sleep_for(retry_delay);
            continue;
        }

        if (number_of_hosts_found == 0)
        {
            std::cerr << "Failed to find hosts (attempt " << attempts << "/" << max_attempts << ")" << std::endl;
            std::this_thread::sleep_for(retry_delay);
            continue;
        }

        std::vector<ManusHost> available_hosts(number_of_hosts_found);

        if (const auto hosts_result = CoreSdk_GetAvailableHostsFound(available_hosts.data(), number_of_hosts_found);
            hosts_result != SDKReturnCode::SDKReturnCode_Success)
        {
            std::cerr << "Failed to get available hosts (attempt " << attempts << "/" << max_attempts << ")" << std::endl;
            std::this_thread::sleep_for(retry_delay);
            continue;
        }

        if (const auto connect_result = CoreSdk_ConnectToHost(available_hosts[0]);
            connect_result == SDKReturnCode::SDKReturnCode_NotConnected)
        {
            std::cerr << "Failed to connect to host (attempt " << attempts << "/" << max_attempts << ")" << std::endl;
            std::this_thread::sleep_for(retry_delay);
            continue;
        }

        connected = true;
        is_connected = true;
        std::cout << "Successfully connected to Manus host after " << attempts << " attempts" << std::endl;
    }

    if (!connected)
    {
        std::cerr << "Failed to connect to Manus gloves after " << max_attempts << " attempts" << std::endl;
        throw std::runtime_error("Failed to connect to Manus gloves");
    }
}

void ManusTracker::DisconnectFromGloves()
{
    if (is_connected)
    {
        CoreSdk_Disconnect();
        is_connected = false;
        std::cout << "Disconnected from Manus gloves" << std::endl;
    }
}

void ManusTracker::OnSkeletonStream(const SkeletonStreamInfo* skeleton_stream_info)
{
    auto& tracker = instance();
    std::lock_guard<std::mutex> instance_lock(tracker.m_lifecycle_mutex);
    if (!tracker.m_initialized)
    {
        return;
    }

    for (uint32_t i = 0; i < skeleton_stream_info->skeletonsCount; i++)
    {
        RawSkeletonInfo skeleton_info;
        CoreSdk_GetRawSkeletonInfo(i, &skeleton_info);

        std::vector<SkeletonNode> nodes(skeleton_info.nodesCount);
        skeleton_info.publishTime = skeleton_stream_info->publishTime;
        CoreSdk_GetRawSkeletonData(i, nodes.data(), skeleton_info.nodesCount);

        uint32_t glove_id = skeleton_info.gloveId;

        // Check if glove ID matches any known glove
        bool is_left_glove, is_right_glove;
        {
            std::lock_guard<std::mutex> landscape_lock(tracker.landscape_mutex);
            is_left_glove = tracker.left_glove_id && glove_id == *tracker.left_glove_id;
            is_right_glove = tracker.right_glove_id && glove_id == *tracker.right_glove_id;
        }

        if (!is_left_glove && !is_right_glove)
        {
            std::cerr << "Skipping data from unknown glove ID: " << glove_id << std::endl;
            continue;
        }

        std::string prefix = is_left_glove ? "left" : "right";

        // Save data for OpenXR Injection
        {
            std::lock_guard<std::mutex> lock(tracker.m_skeleton_mutex);
            if (is_left_glove)
            {
                tracker.m_left_hand_nodes = nodes;
            }
            else if (is_right_glove)
            {
                tracker.m_right_hand_nodes = nodes;
            }
        }
    }
}

void ManusTracker::OnLandscapeStream(const Landscape* landscape)
{
    auto& tracker = instance();
    std::lock_guard<std::mutex> instance_lock(tracker.m_lifecycle_mutex);
    if (!tracker.m_initialized)
    {
        return;
    }

    const auto& gloves = landscape->gloveDevices;

    std::lock_guard<std::mutex> landscape_lock(tracker.landscape_mutex);

    // We only support one left and one right glove
    if (gloves.gloveCount > 2)
    {
        std::cerr << "Invalid number of gloves detected: " << gloves.gloveCount << std::endl;
        return;
    }

    // Extract glove IDs from landscape data
    bool left_present = false;
    bool right_present = false;
    for (uint32_t i = 0; i < gloves.gloveCount; i++)
    {
        const GloveLandscapeData& glove = gloves.gloves[i];
        if (glove.side == Side::Side_Left)
            {
                tracker.left_glove_id = glove.id;
                left_present = true;
                // Fetch bone topology once on connect
                uint32_t nc = 0;
                if (CoreSdk_GetRawSkeletonNodeCount(glove.id, nc) == SDKReturnCode::SDKReturnCode_Success && nc > 0)
                {
                    std::lock_guard<std::mutex> sk(tracker.m_skeleton_mutex);
                    tracker.m_left_node_info.resize(nc);
                    if (CoreSdk_GetRawSkeletonNodeInfoArray(glove.id, tracker.m_left_node_info.data(), nc) != SDKReturnCode::SDKReturnCode_Success)
                        tracker.m_left_node_info.clear();
                }
            }
            else if (glove.side == Side::Side_Right)
            {
                tracker.right_glove_id = glove.id;
                right_present = true;
                uint32_t nc = 0;
                if (CoreSdk_GetRawSkeletonNodeCount(glove.id, nc) == SDKReturnCode::SDKReturnCode_Success && nc > 0)
                {
                    std::lock_guard<std::mutex> sk(tracker.m_skeleton_mutex);
                    tracker.m_right_node_info.resize(nc);
                    if (CoreSdk_GetRawSkeletonNodeInfoArray(glove.id, tracker.m_right_node_info.data(), nc) != SDKReturnCode::SDKReturnCode_Success)
                        tracker.m_right_node_info.clear();
                }
            }
    }

    // Clear stale state for any glove that is no longer present in this landscape
    // update (i.e., disconnected). Resetting the IDs prevents OnSkeletonStream from
    // matching future packets to a dead glove, and clearing the node cache prevents
    // inject_hand_data() from replaying the last known stale pose indefinitely.
    {
        std::lock_guard<std::mutex> skeleton_lock(tracker.m_skeleton_mutex);
        if (!left_present && tracker.left_glove_id.has_value())
        {
            std::cout << "[Manus] Left glove disconnected (ID " << *tracker.left_glove_id << ")" << std::endl;
            tracker.left_glove_id.reset();
            tracker.m_left_hand_nodes.clear();
            tracker.m_left_node_info.clear();
        }
        if (!right_present && tracker.right_glove_id.has_value())
        {
            std::cout << "[Manus] Right glove disconnected (ID " << *tracker.right_glove_id << ")" << std::endl;
            tracker.right_glove_id.reset();
            tracker.m_right_hand_nodes.clear();
            tracker.m_right_node_info.clear();
        }
    }
}

void ManusTracker::initialize_xdev_hand_trackers()
{
    // Load XDev extension function pointers
    auto load_func = [this](const char* name, PFN_xrVoidFunction* ptr) -> bool {
        XrResult result = m_handles.xrGetInstanceProcAddr(m_handles.instance, name, ptr);
        return XR_SUCCEEDED(result) && *ptr != nullptr;
    };

    // Load XDev extension functions
    if (!load_func("xrCreateXDevListMNDX", reinterpret_cast<PFN_xrVoidFunction*>(&m_pfn_create_xdev_list)) ||
        !load_func("xrDestroyXDevListMNDX", reinterpret_cast<PFN_xrVoidFunction*>(&m_pfn_destroy_xdev_list)) ||
        !load_func("xrEnumerateXDevsMNDX", reinterpret_cast<PFN_xrVoidFunction*>(&m_pfn_enumerate_xdevs)) ||
        !load_func("xrGetXDevPropertiesMNDX", reinterpret_cast<PFN_xrVoidFunction*>(&m_pfn_get_xdev_properties)))
    {
        std::cerr << "[Manus] XR_MNDX_xdev_space extension not available, falling back to controllers" << std::endl;
        return;
    }

    // Load hand tracking extension functions
    if (!load_func("xrCreateHandTrackerEXT", reinterpret_cast<PFN_xrVoidFunction*>(&m_pfn_create_hand_tracker)) ||
        !load_func("xrDestroyHandTrackerEXT", reinterpret_cast<PFN_xrVoidFunction*>(&m_pfn_destroy_hand_tracker)) ||
        !load_func("xrLocateHandJointsEXT", reinterpret_cast<PFN_xrVoidFunction*>(&m_pfn_locate_hand_joints)))
    {
        std::cerr << "[Manus] Hand tracking extension not available, falling back to controllers" << std::endl;
        return;
    }

    // Create XDev list
    XrCreateXDevListInfoMNDX create_info{ XR_TYPE_CREATE_XDEV_LIST_INFO_MNDX };
    XrResult result = m_pfn_create_xdev_list(m_handles.session, &create_info, &m_xdev_list);
    if (XR_FAILED(result))
    {
        std::cerr << "[Manus] Failed to create XDevList, falling back to controllers" << std::endl;
        return;
    }

    // Enumerate XDevs
    uint32_t xdev_count = 0;
    result = m_pfn_enumerate_xdevs(m_xdev_list, 0, &xdev_count, nullptr);
    if (XR_FAILED(result) || xdev_count == 0)
    {
        std::cerr << "[Manus] No XDevs found, falling back to controllers" << std::endl;
        return;
    }

    std::vector<XrXDevIdMNDX> xdev_ids(xdev_count);
    result = m_pfn_enumerate_xdevs(m_xdev_list, xdev_count, &xdev_count, xdev_ids.data());
    if (XR_FAILED(result))
    {
        return;
    }

    // Find native hand tracking devices by matching against their serial strings.
    //
    // NOTE: The serial values "Head Device (0)" (left) and "Head Device (1)" (right) are
    // NOT defined by the XR_MNDX_xdev_space specification. They are an observed runtime-
    // specific naming convention (e.g. Monado). If a runtime changes these display names
    // across firmware or software updates the match below will silently fail.
    // See: https://registry.khronos.org/OpenXR/specs/1.0/html/xrspec.html (XR_MNDX_xdev_space)
    XrXDevIdMNDX left_xdev_id = 0;
    XrXDevIdMNDX right_xdev_id = 0;
    std::vector<std::string> seen_serials;

    for (const auto& xdev_id : xdev_ids)
    {
        XrGetXDevInfoMNDX get_info{ XR_TYPE_GET_XDEV_INFO_MNDX };
        get_info.id = xdev_id;

        XrXDevPropertiesMNDX properties{ XR_TYPE_XDEV_PROPERTIES_MNDX };
        result = m_pfn_get_xdev_properties(m_xdev_list, &get_info, &properties);
        if (XR_FAILED(result))
        {
            continue;
        }

        std::string serial_str = properties.serial ? properties.serial : "";
        seen_serials.push_back(serial_str);

        if (serial_str == "Head Device (0)")
        {
            left_xdev_id = xdev_id;
        }
        else if (serial_str == "Head Device (1)")
        {
            right_xdev_id = xdev_id;
        }
    }

    if (left_xdev_id == 0 || right_xdev_id == 0)
    {
        std::string serials_list;
        for (const auto& s : seen_serials)
        {
            if (!serials_list.empty()) serials_list += ", ";
            serials_list += '"';
            serials_list += s;
            serials_list += '"';
        }
        std::cerr << "[Manus] Could not match optical hand-tracking XDevs by serial. "
                  << "Expected \"Head Device (0)\" (left) and \"Head Device (1)\" (right), "
                  << "but found: [" << serials_list << "]. "
                  << "These serial strings are runtime-specific and may have changed."
                  << std::endl;
    }

    // Create hand trackers from XDevs
    auto create_tracker = [this](XrXDevIdMNDX xdev_id, XrHandEXT hand, XrHandTrackerEXT& out_tracker) -> bool {
        if (xdev_id == 0)
        {
            return false;
        }

        XrCreateHandTrackerXDevMNDX xdev_create_info{ XR_TYPE_CREATE_HAND_TRACKER_XDEV_MNDX };
        xdev_create_info.xdevList = m_xdev_list;
        xdev_create_info.id = xdev_id;

        XrHandTrackerCreateInfoEXT create_info{ XR_TYPE_HAND_TRACKER_CREATE_INFO_EXT };
        create_info.next = &xdev_create_info;
        create_info.hand = hand;
        create_info.handJointSet = XR_HAND_JOINT_SET_DEFAULT_EXT;

        return XR_SUCCEEDED(m_pfn_create_hand_tracker(m_handles.session, &create_info, &out_tracker));
    };

    bool left_ok = create_tracker(left_xdev_id, XR_HAND_LEFT_EXT, m_native_left_hand_tracker);
    bool right_ok = create_tracker(right_xdev_id, XR_HAND_RIGHT_EXT, m_native_right_hand_tracker);

    if (left_ok && right_ok)
    {
        m_xdev_available = true;
    }
    else
    {
        std::cerr << "[Manus] Failed to create native hand trackers, falling back to controllers" << std::endl;
        cleanup_xdev_hand_trackers();
    }
}

void ManusTracker::cleanup_xdev_hand_trackers()
{
    if (m_native_left_hand_tracker != XR_NULL_HANDLE && m_pfn_destroy_hand_tracker)
    {
        m_pfn_destroy_hand_tracker(m_native_left_hand_tracker);
        m_native_left_hand_tracker = XR_NULL_HANDLE;
    }
    if (m_native_right_hand_tracker != XR_NULL_HANDLE && m_pfn_destroy_hand_tracker)
    {
        m_pfn_destroy_hand_tracker(m_native_right_hand_tracker);
        m_native_right_hand_tracker = XR_NULL_HANDLE;
    }
    if (m_xdev_list != XR_NULL_HANDLE && m_pfn_destroy_xdev_list)
    {
        m_pfn_destroy_xdev_list(m_xdev_list);
        m_xdev_list = XR_NULL_HANDLE;
    }
    m_xdev_available = false;
}

bool ManusTracker::update_xdev_hand(XrHandTrackerEXT tracker, XrTime time, XrPosef& out_wrist_pose, bool& out_is_tracked)
{
    out_is_tracked = false;

    if (tracker == XR_NULL_HANDLE || !m_pfn_locate_hand_joints || time == 0)
    {
        return false;
    }

    XrHandJointsLocateInfoEXT locate_info{ XR_TYPE_HAND_JOINTS_LOCATE_INFO_EXT };
    locate_info.baseSpace = m_handles.space;
    locate_info.time = time;

    XrHandJointLocationEXT joint_locations[XR_HAND_JOINT_COUNT_EXT];

    XrHandJointLocationsEXT locations{ XR_TYPE_HAND_JOINT_LOCATIONS_EXT };
    locations.jointCount = XR_HAND_JOINT_COUNT_EXT;
    locations.jointLocations = joint_locations;

    XrResult result = m_pfn_locate_hand_joints(tracker, &locate_info, &locations);
    if (XR_FAILED(result) || !locations.isActive)
    {
        return false;
    }

    const auto& wrist = joint_locations[XR_HAND_JOINT_WRIST_EXT];
    const bool is_valid = (wrist.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT) &&
                          (wrist.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT);

    if (is_valid)
    {
        out_wrist_pose = wrist.pose;
        // Distinguish actively tracked from valid-but-predicted/stale poses so
        // callers can advertise TRACKED bits only when the runtime confirms it.
        out_is_tracked = (wrist.locationFlags & XR_SPACE_LOCATION_POSITION_TRACKED_BIT) &&
                         (wrist.locationFlags & XR_SPACE_LOCATION_ORIENTATION_TRACKED_BIT);
        return true;
    }

    return false;
}

bool ManusTracker::get_controller_wrist_pose(bool is_left, XrPosef& out_wrist_pose)
{
    const auto& tracked = is_left ? m_controller_tracker->get_left_controller(*m_deviceio_session)
                                  : m_controller_tracker->get_right_controller(*m_deviceio_session);

    if (!tracked.data)
    {
        return false;
    }

    bool aim_valid = false;
    XrPosef raw_pose = oxr_utils::get_aim_pose(*tracked.data, aim_valid);

    if (!aim_valid)
    {
        return false;
    }

    XrPosef offset_pose = is_left ? kLeftHandOffset : kRightHandOffset;
    out_wrist_pose = oxr_utils::multiply_poses(raw_pose, offset_pose);
    return true;
}

void ManusTracker::inject_hand_data()
{
    std::vector<SkeletonNode> left_nodes;
    std::vector<SkeletonNode> right_nodes;

    {
        std::lock_guard<std::mutex> lock(m_skeleton_mutex);
        left_nodes = m_left_hand_nodes;
        right_nodes = m_right_hand_nodes;
    }

    // Get current XrTime from the system monotonic clock
    XrTime time = m_time_converter->os_monotonic_now();

    auto process_hand = [&](const std::vector<SkeletonNode>& nodes, bool is_left)
    {
        if (nodes.empty())
        {
            return;
        }

        XrHandJointLocationEXT joints[XR_HAND_JOINT_COUNT_EXT];
        XrPosef root_pose = { { 0.0f, 0.0f, 0.0f, 1.0f }, { 0.0f, 0.0f, 0.0f } };
        bool is_root_tracked = false;

        // Get wrist pose - auto-select hand tracking or controllers
        XrPosef wrist_pose;
        bool xdev_pose_valid = false;
        if (m_xdev_available)
        {
            XrHandTrackerEXT tracker = is_left ? m_native_left_hand_tracker : m_native_right_hand_tracker;
            bool xdev_tracked = false;
            if (update_xdev_hand(tracker, time, wrist_pose, xdev_tracked))
            {
                // Cache the pose (valid even when only predicted/stale) so the
                // last good pose is available if tracking is briefly interrupted.
                if (is_left)
                {
                    m_left_root_pose = wrist_pose;
                }
                else
                {
                    m_right_root_pose = wrist_pose;
                }
                // Only mark as tracked when the runtime confirms active tracking;
                // a valid-but-untracked pose must not have TRACKED bits set.
                is_root_tracked = xdev_tracked;
                xdev_pose_valid = true;
            }
        }

        // Fall back to controllers only when xdev provided no valid pose at all.
        // If xdev gave a valid-but-untracked pose we keep it rather than
        // overwriting it with a controller pose that would be falsely marked tracked.
        if (!xdev_pose_valid && get_controller_wrist_pose(is_left, wrist_pose))
        {
            if (is_left)
            {
                m_left_root_pose = wrist_pose;
            }
            else
            {
                m_right_root_pose = wrist_pose;
            }
            is_root_tracked = true;
        }

        root_pose = is_left ? m_left_root_pose : m_right_root_pose;
        uint32_t nodes_count = static_cast<uint32_t>(nodes.size());

        for (uint32_t j = 0; j < XR_HAND_JOINT_COUNT_EXT; j++)
        {
            // Determine source index in Manus array
            int manus_index = -1;

            if (j == XR_HAND_JOINT_PALM_EXT)
            {
                // OpenXR Palm -> Use Manus Palm (Last Index)
                if (nodes_count > 0)
                {
                    manus_index = nodes_count - 1;
                }
            }
            else if (j == XR_HAND_JOINT_WRIST_EXT)
            {
                // OpenXR Wrist -> Manus Wrist (Index 0)
                manus_index = 0;
            }
            else
            {
                // OpenXR Finger Joints (Indices 2..25) -> Manus Finger Joints (Indices 1..24)
                manus_index = j - 1;
            }

            if (manus_index >= 0 && manus_index < (int)nodes_count)
            {
                const auto& pos = nodes[manus_index].transform.position;
                const auto& rot = nodes[manus_index].transform.rotation;

                XrPosef local_pose;
                local_pose.position.x = pos.x;
                local_pose.position.y = pos.y;
                local_pose.position.z = pos.z;
                local_pose.orientation.x = rot.x;
                local_pose.orientation.y = rot.y;
                local_pose.orientation.z = rot.z;
                local_pose.orientation.w = rot.w;

                joints[j].pose = oxr_utils::multiply_poses(root_pose, local_pose);

                joints[j].radius = 0.01f;
                joints[j].locationFlags = XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT;

                if (is_root_tracked)
                {
                    joints[j].locationFlags |=
                        XR_SPACE_LOCATION_POSITION_TRACKED_BIT | XR_SPACE_LOCATION_ORIENTATION_TRACKED_BIT;
                }
            }
            else
            {
                // Invalid joint if index out of bounds
                joints[j] = { 0 };
            }
        }

        if (is_left)
        {
            m_left_injector->push(joints, time);
        }
        else
        {
            m_right_injector->push(joints, time);
        }
    };

    process_hand(left_nodes, true);
    process_hand(right_nodes, false);
}

} // namespace manus
} // namespace plugins
