// SPDX-FileCopyrightText: Copyright (c) 2026 Wuji Technology. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "wuji_glove_plugin.hpp"

#include <algorithm>
#include <chrono>
#include <cstring>
#include <iostream>
#include <iterator>
#include <stdexcept>

namespace plugins
{
namespace wuji_glove
{

namespace
{

// MediaPipe-21 landmark index -> OpenXR XrHandJointEXT slot.
// The 5 OpenXR slots not covered here (PALM + the four non-thumb METACARPALs)
// are left with POSITION/ORIENTATION_VALID cleared — the Wuji retargeter skips
// them, and other XR_EXT_hand_tracking consumers treat them as untracked.
constexpr XrHandJointEXT kMpToXr[21] = {
    XR_HAND_JOINT_WRIST_EXT,
    XR_HAND_JOINT_THUMB_METACARPAL_EXT,
    XR_HAND_JOINT_THUMB_PROXIMAL_EXT,
    XR_HAND_JOINT_THUMB_DISTAL_EXT,
    XR_HAND_JOINT_THUMB_TIP_EXT,
    XR_HAND_JOINT_INDEX_PROXIMAL_EXT,
    XR_HAND_JOINT_INDEX_INTERMEDIATE_EXT,
    XR_HAND_JOINT_INDEX_DISTAL_EXT,
    XR_HAND_JOINT_INDEX_TIP_EXT,
    XR_HAND_JOINT_MIDDLE_PROXIMAL_EXT,
    XR_HAND_JOINT_MIDDLE_INTERMEDIATE_EXT,
    XR_HAND_JOINT_MIDDLE_DISTAL_EXT,
    XR_HAND_JOINT_MIDDLE_TIP_EXT,
    XR_HAND_JOINT_RING_PROXIMAL_EXT,
    XR_HAND_JOINT_RING_INTERMEDIATE_EXT,
    XR_HAND_JOINT_RING_DISTAL_EXT,
    XR_HAND_JOINT_RING_TIP_EXT,
    XR_HAND_JOINT_LITTLE_PROXIMAL_EXT,
    XR_HAND_JOINT_LITTLE_INTERMEDIATE_EXT,
    XR_HAND_JOINT_LITTLE_DISTAL_EXT,
    XR_HAND_JOINT_LITTLE_TIP_EXT,
};

constexpr XrSpaceLocationFlags kValidFlags =
    XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_POSITION_TRACKED_BIT |
    XR_SPACE_LOCATION_ORIENTATION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_TRACKED_BIT;

constexpr float kDefaultJointRadius = 0.01f; // meters; SDK does not provide radius.
constexpr auto kShutdownPollInterval = std::chrono::milliseconds(100);

// Convert a 21-joint Wuji skeleton into a 26-joint XrHandJointLocationEXT set.
// Returns false if the skeleton does not carry the expected 21 joints.
//
// Glove positions are wrist-relative; this conversion preserves that frame.
bool convert_skeleton(const WujiHandSkeleton* frame, std::array<XrHandJointLocationEXT, XR_HAND_JOINT_COUNT_EXT>& out)
{
    if (frame == nullptr || frame->joints == nullptr || frame->joints_len < 21)
    {
        return false;
    }

    // Start fully untracked, then fill the 21 mapped joints.
    for (auto& j : out)
    {
        j = XrHandJointLocationEXT{};
        j.locationFlags = 0;
        j.radius = kDefaultJointRadius;
        j.pose.orientation = XrQuaternionf{ 0.0f, 0.0f, 0.0f, 1.0f };
    }

    for (int mp = 0; mp < 21; ++mp)
    {
        const WujiSkeletonJoint& src = frame->joints[mp];
        XrHandJointLocationEXT& dst = out[kMpToXr[mp]];
        dst.pose.position = XrVector3f{ src.pose.position[0], src.pose.position[1], src.pose.position[2] };
        dst.pose.orientation = XrQuaternionf{ src.pose.orientation.x, src.pose.orientation.y, src.pose.orientation.z,
                                              src.pose.orientation.w };
        dst.radius = kDefaultJointRadius;
        dst.locationFlags = kValidFlags;
    }
    return true;
}

// Resolve the glove's hand side explicitly via the device's "hand_side" GET
// (a NUL-terminated "left"/"right" string) — never inferred from frame contents.
std::optional<bool> query_is_left(WujiDevice* dev)
{
    char buf[16] = { 0 };
    size_t needed = 0;
    if (wuji_glove_get_hand_side(dev, buf, sizeof(buf), &needed) != WUJI_STATUS_OK)
    {
        return std::nullopt;
    }
    if (std::strcmp(buf, "left") == 0)
    {
        return true;
    }
    if (std::strcmp(buf, "right") == 0)
    {
        return false;
    }
    return std::nullopt;
}

const char* safe_err()
{
    const char* e = wuji_last_error();
    return e ? e : "(no error message)";
}

} // namespace

WujiGlovePlugin::WujiGlovePlugin(const std::string& plugin_root_id) noexcept(false) : m_root_id(plugin_root_id)
{
    std::cout << "Initializing WujiGlovePlugin with root: " << m_root_id << std::endl;

    // The glove is not an OpenXR upstream tracker — it is read out-of-band via
    // wuji_sdk. We still need an OpenXR session for the push-device (injection)
    // extension. No upstream trackers are required.
    std::vector<std::shared_ptr<core::ITracker>> trackers; // empty
    auto extensions = core::DeviceIOSession::get_required_extensions(trackers);
    extensions.push_back(XR_NVX1_DEVICE_INTERFACE_BASE_EXTENSION_NAME);

    m_session = std::make_shared<core::OpenXRSession>("WujiGlove", extensions);
    const auto handles = m_session->get_handles();

    // No upstream OpenXR trackers to run, so the DeviceIOSession takes an empty
    // tracker list. It exists only to pump the OpenXR frame loop, keeping the
    // session and time domain live so injection has a valid XrTime base.
    m_deviceio_session = core::DeviceIOSession::run(trackers, handles);
    m_time_converter.emplace(handles);

    WujiInitOptions init_opts{};
    init_opts.log_level = 2; // warn only; the plugin reports connection and errors itself
    if (wuji_init(&init_opts) != WUJI_STATUS_OK)
    {
        throw std::runtime_error(std::string("WujiGlovePlugin: wuji_init failed: ") + safe_err());
    }

    m_running = true;
    try
    {
        m_thread = std::thread(&WujiGlovePlugin::worker_thread, this);
        m_connection_thread = std::thread(&WujiGlovePlugin::connection_thread, this);
    }
    catch (...)
    {
        m_running = false;
        if (m_thread.joinable())
        {
            m_thread.join();
        }
        if (m_connection_thread.joinable())
        {
            m_connection_thread.join();
        }
        wuji_shutdown();
        throw;
    }
    std::cout << "WujiGlovePlugin initialized and running" << std::endl;
}

WujiGlovePlugin::~WujiGlovePlugin()
{
    std::cout << "Shutting down WujiGlovePlugin..." << std::endl;
    m_running = false;
    if (m_connection_thread.joinable())
    {
        m_connection_thread.join();
    }
    if (m_thread.joinable())
    {
        m_thread.join();
    }
    wuji_shutdown();
}

bool WujiGlovePlugin::is_running() const noexcept
{
    return m_running.load(std::memory_order_acquire);
}

bool WujiGlovePlugin::has_failed() const noexcept
{
    return m_failed.load(std::memory_order_acquire);
}

bool WujiGlovePlugin::connect_glove(GloveConnection& connection)
{
    WujiConnectTarget target{};
    target.kind = WUJI_CONNECT_TARGET_KIND_SN;
    target.value = connection.serial.c_str();

    WujiDevice* device = nullptr;
    if (wuji_connect(&target, connection.serial.c_str(), nullptr, &device) != WUJI_STATUS_OK)
    {
        std::cerr << "WujiGlovePlugin: wuji_connect(" << connection.serial << ") failed: " << safe_err() << std::endl;
        return false;
    }

    const std::optional<bool> is_left = query_is_left(device);
    if (!is_left.has_value())
    {
        std::cerr << "WujiGlovePlugin: could not determine hand_side for " << connection.serial << std::endl;
        wuji_dev_disconnect(device);
        wuji_dev_release(device);
        return false;
    }

    auto context = std::make_unique<SubContext>();
    context->self = this;
    context->is_left = *is_left;
    wuji_glove_set_emf_poses_rate_divider(device, 2);

    WujiSub* subscription = nullptr;
    if (wuji_glove_subscribe_hand_skeleton(device, &WujiGlovePlugin::skeleton_callback, context.get(), &subscription) !=
        WUJI_STATUS_OK)
    {
        std::cerr << "WujiGlovePlugin: subscribe hand_skeleton failed for " << connection.serial << ": " << safe_err()
                  << std::endl;
        wuji_dev_disconnect(device);
        wuji_dev_release(device);
        return false;
    }

    connection.device = device;
    connection.subscription = subscription;
    connection.context = std::move(context);
    std::cout << "WujiGlovePlugin: connected " << connection.serial << " ("
              << (connection.context->is_left ? "left" : "right") << ")" << std::endl;
    return true;
}

void WujiGlovePlugin::disconnect_glove(GloveConnection& connection)
{
    if (connection.context)
    {
        invalidate_hand(connection.context->is_left);
    }
    if (connection.subscription != nullptr)
    {
        // Closing joins the SDK callback thread; the callback context must stay
        // alive until this returns.
        wuji_sub_close(connection.subscription);
        connection.subscription = nullptr;
    }
    connection.context.reset();
    if (connection.device != nullptr)
    {
        wuji_dev_disconnect(connection.device);
        wuji_dev_release(connection.device);
        connection.device = nullptr;
    }
}

void WujiGlovePlugin::discover_gloves()
{
    WujiDiscovered* list = nullptr;
    size_t count = 0;
    if (wuji_scan(&list, &count) != WUJI_STATUS_OK)
    {
        std::cerr << "WujiGlovePlugin: wuji_scan failed: " << safe_err() << std::endl;
        wuji_discovered_free(list, count);
        return;
    }

    for (size_t i = 0; i < count && m_running; ++i)
    {
        if (list[i].device_id != WUJI_DEVICE_TYPE_WUJI_GLOVE || list[i].serial_number[0] == '\0')
        {
            continue;
        }

        const std::string serial = list[i].serial_number;
        auto found = std::find_if(m_connections.begin(), m_connections.end(),
                                  [&serial](const auto& connection) { return connection->serial == serial; });
        if (found == m_connections.end())
        {
            auto connection = std::make_unique<GloveConnection>();
            connection->serial = serial;
            m_connections.push_back(std::move(connection));
            found = std::prev(m_connections.end());
        }

        GloveConnection& connection = **found;
        if (connection.subscription == nullptr)
        {
            connect_glove(connection);
        }
    }
    wuji_discovered_free(list, count);
}

void WujiGlovePlugin::connection_thread()
{
    while (m_running)
    {
        for (auto& connection : m_connections)
        {
            if (connection->context && connection->context->terminal.load(std::memory_order_acquire))
            {
                std::cout << "WujiGlovePlugin: disconnected " << connection->serial << std::endl;
                disconnect_glove(*connection);
            }
        }

        discover_gloves();

        for (int i = 0; i < 10 && m_running; ++i)
        {
            std::this_thread::sleep_for(kShutdownPollInterval);
        }
    }

    for (auto& connection : m_connections)
    {
        disconnect_glove(*connection);
    }
    m_connections.clear();
}

// Runs on the wuji_sdk subscription worker thread. `frame` is valid only for the
// duration of this call.
void WujiGlovePlugin::skeleton_callback(WujiFrameKind kind, const WujiHandSkeleton* frame, void* user_data)
{
    if (user_data == nullptr)
    {
        return;
    }
    auto* ctx = static_cast<SubContext*>(user_data);
    if (kind == WUJI_FRAME_KIND_OK && frame != nullptr)
    {
        ctx->self->on_skeleton(frame, ctx->is_left);
    }
    else if (kind == WUJI_FRAME_KIND_END || kind == WUJI_FRAME_KIND_ERROR)
    {
        // Closing from this SDK callback thread would self-deadlock. Signal the
        // connection thread to own cleanup and resubscription instead.
        ctx->self->invalidate_hand(ctx->is_left);
        ctx->terminal.store(true, std::memory_order_release);
    }
}

void WujiGlovePlugin::on_skeleton(const WujiHandSkeleton* frame, bool is_left)
{
    std::array<XrHandJointLocationEXT, XR_HAND_JOINT_COUNT_EXT> joints{};
    if (!convert_skeleton(frame, joints))
    {
        return;
    }

    std::lock_guard<std::mutex> lock(m_frame_mutex);
    HandFrame& slot = is_left ? m_left : m_right;
    slot.joints = joints;
    slot.valid = true;
    slot.stamp = std::chrono::steady_clock::now();
}

void WujiGlovePlugin::invalidate_hand(bool is_left)
{
    std::lock_guard<std::mutex> lock(m_frame_mutex);
    HandFrame& slot = is_left ? m_left : m_right;
    slot.valid = false;
}

void WujiGlovePlugin::pump_hand(std::unique_ptr<plugin_utils::HandInjector>& injector,
                                XrHandEXT hand,
                                const HandFrame& frame,
                                XrTime time)
{
    // Treat data older than 200 ms as "hand absent": drop the injector so the
    // runtime reports isActive=false rather than a frozen pose.
    using namespace std::chrono;
    const bool fresh = frame.valid && (steady_clock::now() - frame.stamp) < milliseconds(200);
    if (!fresh)
    {
        injector.reset();
        return;
    }
    if (!injector)
    {
        const auto handles = m_session->get_handles();
        injector = std::make_unique<plugin_utils::HandInjector>(handles.instance, handles.session, hand, handles.space);
    }
    injector->push(frame.joints.data(), time);
}

void WujiGlovePlugin::worker_thread()
{
    while (m_running)
    {
        try
        {
            m_deviceio_session->update();
        }
        catch (const std::exception& e)
        {
            std::cerr << "WujiGlovePlugin update error: " << e.what() << std::endl;
            m_left_injector.reset();
            m_right_injector.reset();
            m_failed.store(true, std::memory_order_release);
            m_running.store(false, std::memory_order_release);
            return;
        }

        const XrTime time = m_time_converter->os_monotonic_now();

        HandFrame left_copy;
        HandFrame right_copy;
        {
            std::lock_guard<std::mutex> lock(m_frame_mutex);
            left_copy = m_left;
            right_copy = m_right;
        }

        pump_hand(m_left_injector, XR_HAND_LEFT_EXT, left_copy, time);
        pump_hand(m_right_injector, XR_HAND_RIGHT_EXT, right_copy, time);

        std::this_thread::sleep_for(std::chrono::milliseconds(16));
    }
}

} // namespace wuji_glove
} // namespace plugins
