// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <arpa/inet.h>
#include <core/haply_hand_tracking_plugin.hpp>
#include <netinet/tcp.h>
#include <nlohmann/json.hpp>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/math.hpp>
#include <oxr_utils/pose_conversions.hpp>
#include <plugin_utils/hand_injector.hpp>
#include <sys/socket.h>

#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <netdb.h>
#include <random>
#include <stdexcept>
#include <thread>
#include <unistd.h>
#include <vector>

using json = nlohmann::json;

namespace plugins
{
namespace haply
{

// Offset applied to the controller aim pose to produce an initial hand root.
// Only right hand is supported for now; left is provided for future use.
static constexpr XrPosef kLeftHandOffset = { { -0.70710678f, -0.5f, 0.0f, 0.5f }, { -0.1f, 0.02f, -0.02f } };
static constexpr XrPosef kRightHandOffset = { { -0.70710678f, 0.5f, 0.0f, 0.5f }, { 0.1f, 0.02f, -0.02f } };

// ============================================================================
// HaplyWebSocket implementation
// ============================================================================

HaplyWebSocket::HaplyWebSocket() = default;

HaplyWebSocket::~HaplyWebSocket()
{
    close();
}

bool HaplyWebSocket::is_connected() const
{
    return fd_ >= 0;
}

bool HaplyWebSocket::send_raw(const void* data, size_t len)
{
    const uint8_t* ptr = static_cast<const uint8_t*>(data);
    size_t sent = 0;
    while (sent < len)
    {
        ssize_t n = ::send(fd_, ptr + sent, len - sent, MSG_NOSIGNAL);
        if (n <= 0)
        {
            return false;
        }
        sent += static_cast<size_t>(n);
    }
    return true;
}

bool HaplyWebSocket::recv_raw(void* data, size_t len)
{
    uint8_t* ptr = static_cast<uint8_t*>(data);
    size_t received = 0;
    while (received < len)
    {
        ssize_t n = ::recv(fd_, ptr + received, len - received, 0);
        if (n <= 0)
        {
            return false;
        }
        received += static_cast<size_t>(n);
    }
    return true;
}

bool HaplyWebSocket::connect(const std::string& host, uint16_t port, const std::string& path)
{
    close();

    // Resolve host
    struct addrinfo hints
    {
    };
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    struct addrinfo* res = nullptr;
    std::string port_str = std::to_string(port);
    if (getaddrinfo(host.c_str(), port_str.c_str(), &hints, &res) != 0 || !res)
    {
        std::cerr << "[HaplyWebSocket] Failed to resolve host: " << host << std::endl;
        return false;
    }

    fd_ = ::socket(res->ai_family, res->ai_socktype, res->ai_protocol);
    if (fd_ < 0)
    {
        freeaddrinfo(res);
        std::cerr << "[HaplyWebSocket] Failed to create socket" << std::endl;
        return false;
    }

    if (::connect(fd_, res->ai_addr, res->ai_addrlen) < 0)
    {
        freeaddrinfo(res);
        ::close(fd_);
        fd_ = -1;
        std::cerr << "[HaplyWebSocket] Failed to connect to " << host << ":" << port << std::endl;
        return false;
    }
    freeaddrinfo(res);

    // Disable Nagle's algorithm for lower latency
    int flag = 1;
    setsockopt(fd_, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));

    // Generate a random 16-byte WebSocket key
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> dis(0, 255);
    uint8_t key_bytes[16];
    for (int i = 0; i < 16; ++i)
    {
        key_bytes[i] = static_cast<uint8_t>(dis(gen));
    }

    // Base64 encode the key (simple implementation)
    static const char* b64_table = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string ws_key;
    ws_key.reserve(24);
    for (int i = 0; i < 16; i += 3)
    {
        uint32_t n = (static_cast<uint32_t>(key_bytes[i]) << 16);
        if (i + 1 < 16)
        {
            n |= (static_cast<uint32_t>(key_bytes[i + 1]) << 8);
        }
        if (i + 2 < 16)
        {
            n |= static_cast<uint32_t>(key_bytes[i + 2]);
        }
        ws_key += b64_table[(n >> 18) & 0x3F];
        ws_key += b64_table[(n >> 12) & 0x3F];
        ws_key += (i + 1 < 16) ? b64_table[(n >> 6) & 0x3F] : '=';
        ws_key += (i + 2 < 16) ? b64_table[n & 0x3F] : '=';
    }

    // Build HTTP upgrade request
    std::string request = "GET " + path + " HTTP/1.1\r\n";
    request += "Host: " + host + ":" + std::to_string(port) + "\r\n";
    request += "Upgrade: websocket\r\n";
    request += "Connection: Upgrade\r\n";
    request += "Sec-WebSocket-Key: " + ws_key + "\r\n";
    request += "Sec-WebSocket-Version: 13\r\n";
    request += "\r\n";

    if (!send_raw(request.data(), request.size()))
    {
        close();
        std::cerr << "[HaplyWebSocket] Failed to send HTTP upgrade request" << std::endl;
        return false;
    }

    // Read HTTP response headers (look for "101 Switching Protocols")
    std::string response;
    char buf[1];
    bool found_end = false;
    while (!found_end && response.size() < 4096)
    {
        if (!recv_raw(buf, 1))
        {
            close();
            std::cerr << "[HaplyWebSocket] Failed to receive HTTP upgrade response" << std::endl;
            return false;
        }
        response += buf[0];
        if (response.size() >= 4 && response.substr(response.size() - 4) == "\r\n\r\n")
        {
            found_end = true;
        }
    }

    if (response.find("101") == std::string::npos)
    {
        close();
        std::cerr << "[HaplyWebSocket] Upgrade failed, response: " << response.substr(0, 80) << std::endl;
        return false;
    }

    return true;
}

bool HaplyWebSocket::send_frame(uint8_t opcode, const void* payload, size_t len)
{
    if (fd_ < 0)
    {
        return false;
    }

    // Frame header
    std::vector<uint8_t> frame;
    frame.reserve(14 + len);

    // First byte: FIN + opcode
    frame.push_back(0x80 | opcode);

    // Second byte: MASK (clients must mask) + payload length
    if (len <= 125)
    {
        frame.push_back(0x80 | static_cast<uint8_t>(len));
    }
    else if (len <= 65535)
    {
        frame.push_back(0x80 | 126);
        frame.push_back(static_cast<uint8_t>((len >> 8) & 0xFF));
        frame.push_back(static_cast<uint8_t>(len & 0xFF));
    }
    else
    {
        frame.push_back(0x80 | 127);
        for (int i = 7; i >= 0; --i)
        {
            frame.push_back(static_cast<uint8_t>((len >> (8 * i)) & 0xFF));
        }
    }

    // 4-byte mask key
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> dis(0, 255);
    uint8_t mask[4];
    for (int i = 0; i < 4; ++i)
    {
        mask[i] = static_cast<uint8_t>(dis(gen));
        frame.push_back(mask[i]);
    }

    // Masked payload
    const uint8_t* src = static_cast<const uint8_t*>(payload);
    for (size_t i = 0; i < len; ++i)
    {
        frame.push_back(src[i] ^ mask[i % 4]);
    }

    return send_raw(frame.data(), frame.size());
}

bool HaplyWebSocket::send_text(const std::string& payload)
{
    return send_frame(0x01, payload.data(), payload.size());
}

bool HaplyWebSocket::recv_text(std::string& out)
{
    if (fd_ < 0)
    {
        return false;
    }

    out.clear();

    // We may receive a fragmented message; loop until FIN is set
    bool fin = false;
    while (!fin)
    {
        uint8_t header[2];
        if (!recv_raw(header, 2))
        {
            return false;
        }

        fin = (header[0] & 0x80) != 0;
        uint8_t opcode = header[0] & 0x0F;
        bool masked = (header[1] & 0x80) != 0;
        uint64_t payload_len = header[1] & 0x7F;

        if (payload_len == 126)
        {
            uint8_t ext[2];
            if (!recv_raw(ext, 2))
            {
                return false;
            }
            payload_len = (static_cast<uint64_t>(ext[0]) << 8) | ext[1];
        }
        else if (payload_len == 127)
        {
            uint8_t ext[8];
            if (!recv_raw(ext, 8))
            {
                return false;
            }
            payload_len = 0;
            for (int i = 0; i < 8; ++i)
            {
                payload_len = (payload_len << 8) | ext[i];
            }
        }

        uint8_t mask[4] = { 0, 0, 0, 0 };
        if (masked)
        {
            if (!recv_raw(mask, 4))
            {
                return false;
            }
        }

        std::vector<uint8_t> data(payload_len);
        if (payload_len > 0)
        {
            if (!recv_raw(data.data(), payload_len))
            {
                return false;
            }
            if (masked)
            {
                for (size_t i = 0; i < payload_len; ++i)
                {
                    data[i] ^= mask[i % 4];
                }
            }
        }

        // Handle control frames
        if (opcode == 0x08)
        {
            // Close frame — send close response and return false
            send_frame(0x08, data.data(), data.size());
            return false;
        }
        else if (opcode == 0x09)
        {
            // Ping — respond with pong
            send_frame(0x0A, data.data(), data.size());
            continue;
        }
        else if (opcode == 0x0A)
        {
            // Pong — ignore
            continue;
        }
        else if (opcode == 0x01 || opcode == 0x00)
        {
            // Text or continuation
            out.append(reinterpret_cast<char*>(data.data()), data.size());
        }
        else
        {
            // Binary or unknown — append as-is
            out.append(reinterpret_cast<char*>(data.data()), data.size());
        }
    }

    return true;
}

void HaplyWebSocket::close()
{
    if (fd_ >= 0)
    {
        // Send close frame (best effort)
        send_frame(0x08, nullptr, 0);
        ::close(fd_);
        fd_ = -1;
    }
}

// ============================================================================
// HaplyTracker implementation
// ============================================================================

HaplyTracker& HaplyTracker::instance(const std::string& app_name) noexcept(false)
{
    static HaplyTracker s(app_name);
    return s;
}

HaplyTracker::HaplyTracker(const std::string& app_name) noexcept(false)
{
    initialize(app_name);
}

HaplyTracker::~HaplyTracker()
{
    shutdown();
}

void HaplyTracker::initialize(const std::string& app_name) noexcept(false)
{
    std::lock_guard<std::mutex> lock(m_lifecycle_mutex);
    if (m_initialized)
    {
        return;
    }

    // Read WebSocket configuration from environment
    const char* host_env = std::getenv("HAPLY_WEBSOCKET_HOST");
    const char* port_env = std::getenv("HAPLY_WEBSOCKET_PORT");
    std::string ws_host = host_env ? host_env : "127.0.0.1";
    uint16_t ws_port = port_env ? static_cast<uint16_t>(std::atoi(port_env)) : 10001;

    std::cout << "[HaplyTracker] Initializing (WebSocket target: " << ws_host << ":" << ws_port << ")" << std::endl;

    // Start the WebSocket I/O thread
    m_running.store(true);
    m_io_thread = std::thread(&HaplyTracker::io_loop, this, ws_host, ws_port);

    std::string error_msg = "Unknown error";
    bool success = false;

    try
    {
        // Create ControllerTracker and DeviceIOSession
        m_controller_tracker = std::make_shared<core::ControllerTracker>();
        std::vector<std::shared_ptr<core::ITracker>> trackers = { m_controller_tracker };

        // Get required extensions from trackers
        auto extensions = core::DeviceIOSession::get_required_extensions(trackers);
        extensions.push_back(XR_NVX1_DEVICE_INTERFACE_BASE_EXTENSION_NAME);

        // Create OpenXR session — constructor automatically begins the session
        m_session = std::make_shared<core::OpenXRSession>(app_name, extensions);
        auto handles = m_session->get_handles();

        // Initialize hand injectors (one per hand) and time converter
        m_left_injector = std::make_unique<plugin_utils::HandInjector>(
            handles.instance, handles.session, XR_HAND_LEFT_EXT, handles.space);
        m_right_injector = std::make_unique<plugin_utils::HandInjector>(
            handles.instance, handles.session, XR_HAND_RIGHT_EXT, handles.space);
        m_time_converter.emplace(handles);

        m_deviceio_session = core::DeviceIOSession::run(trackers, handles);

        std::cout << "[HaplyTracker] OpenXR session, HandInjector and DeviceIOSession initialized" << std::endl;
        success = true;
    }
    catch (const std::exception& e)
    {
        error_msg = e.what();
    }

    if (!success)
    {
        std::cerr << "[HaplyTracker] Failed to initialize OpenXR: " << error_msg << std::endl;

        // Stop the I/O thread before propagating the error
        m_running.store(false);
        if (m_io_thread.joinable())
        {
            m_io_thread.join();
        }

        throw std::runtime_error(error_msg);
    }

    m_initialized = true;
}

void HaplyTracker::shutdown()
{
    {
        std::lock_guard<std::mutex> lock(m_lifecycle_mutex);
        if (!m_initialized)
        {
            return;
        }
        m_initialized = false;
    }

    // Stop the WebSocket I/O thread
    m_running.store(false);
    if (m_io_thread.joinable())
    {
        m_io_thread.join();
    }

    // Clean up OpenXR resources (unique_ptrs reset automatically)
    m_left_injector.reset();
    m_right_injector.reset();
    m_deviceio_session.reset();
    m_time_converter.reset();
    m_controller_tracker.reset();
    m_session.reset();

    std::cout << "[HaplyTracker] Shutdown complete" << std::endl;
}

void HaplyTracker::io_loop(const std::string& host, uint16_t port)
{
    HaplyWebSocket ws;
    int reconnect_delay_ms = 500;
    constexpr int max_reconnect_delay_ms = 10000;

    while (m_running.load())
    {
        if (!ws.connect(host, port, "/"))
        {
            std::cerr << "[HaplyTracker] Connection failed, retrying in " << reconnect_delay_ms << " ms" << std::endl;
            std::this_thread::sleep_for(std::chrono::milliseconds(reconnect_delay_ms));
            reconnect_delay_ms = std::min(reconnect_delay_ms * 2, max_reconnect_delay_ms);
            continue;
        }

        std::cout << "[HaplyTracker] Connected to Haply SDK" << std::endl;
        reconnect_delay_ms = 500;

        while (m_running.load() && ws.is_connected())
        {
            std::string msg;
            if (!ws.recv_text(msg))
            {
                std::cerr << "[HaplyTracker] Connection lost" << std::endl;
                break;
            }

            try
            {
                json j = json::parse(msg);
                std::string device_id_for_cmd;

                {
                    std::lock_guard<std::mutex> lock(m_state_mutex);

                    // Parse inverse3 array
                    if (j.contains("inverse3") && j["inverse3"].is_array() && !j["inverse3"].empty())
                    {
                        const auto& inv3 = j["inverse3"][0];
                        if (inv3.contains("device_id"))
                        {
                            m_state.inverse3_device_id = inv3["device_id"].get<std::string>();
                        }
                        // Handedness from config (only in first message typically)
                        if (inv3.contains("config") && inv3["config"].contains("handedness"))
                        {
                            m_state.handedness = inv3["config"]["handedness"].get<std::string>();
                        }
                        if (inv3.contains("state"))
                        {
                            const auto& st = inv3["state"];
                            if (st.contains("cursor_position"))
                            {
                                const auto& pos = st["cursor_position"];
                                m_state.cursor_position.x = pos.value("x", 0.0f);
                                m_state.cursor_position.y = pos.value("y", 0.0f);
                                m_state.cursor_position.z = pos.value("z", 0.0f);
                            }
                            if (st.contains("cursor_velocity"))
                            {
                                const auto& vel = st["cursor_velocity"];
                                m_state.cursor_velocity.x = vel.value("x", 0.0f);
                                m_state.cursor_velocity.y = vel.value("y", 0.0f);
                                m_state.cursor_velocity.z = vel.value("z", 0.0f);
                            }
                        }
                        m_state.has_data = true;
                    }

                    // Parse wireless_verse_grip array
                    if (j.contains("wireless_verse_grip") && j["wireless_verse_grip"].is_array() &&
                        !j["wireless_verse_grip"].empty())
                    {
                        const auto& vg = j["wireless_verse_grip"][0];
                        if (vg.contains("device_id"))
                        {
                            m_state.versegrip_device_id = vg["device_id"].get<std::string>();
                        }
                        if (vg.contains("state"))
                        {
                            const auto& st = vg["state"];
                            if (st.contains("orientation"))
                            {
                                const auto& ori = st["orientation"];
                                m_state.orientation.w = ori.value("w", 1.0f);
                                m_state.orientation.x = ori.value("x", 0.0f);
                                m_state.orientation.y = ori.value("y", 0.0f);
                                m_state.orientation.z = ori.value("z", 0.0f);
                            }
                            if (st.contains("buttons"))
                            {
                                const auto& btn = st["buttons"];
                                m_state.buttons.button_0 = btn.value("button_0", false);
                                m_state.buttons.button_1 = btn.value("button_1", false);
                                m_state.buttons.button_2 = btn.value("button_2", false);
                                m_state.buttons.button_3 = btn.value("button_3", false);
                            }
                        }
                        m_state.has_data = true;
                    }

                    device_id_for_cmd = m_state.inverse3_device_id;
                }

                // Send a zero-force command to keep receiving updates
                if (!device_id_for_cmd.empty())
                {
                    json cmd;
                    cmd["inverse3"] = json::array();
                    json dev;
                    dev["device_id"] = device_id_for_cmd;
                    dev["commands"]["set_cursor_force"]["values"]["x"] = 0;
                    dev["commands"]["set_cursor_force"]["values"]["y"] = 0;
                    dev["commands"]["set_cursor_force"]["values"]["z"] = 0;
                    cmd["inverse3"].push_back(dev);
                    ws.send_text(cmd.dump());
                }
            }
            catch (const json::exception& e)
            {
                std::cerr << "[HaplyTracker] JSON parse error: " << e.what() << std::endl;
            }
        }

        ws.close();
    }

    ws.close();
}

void HaplyTracker::update()
{
    if (!m_deviceio_session->update())
    {
        return;
    }

    inject_hand_data();
}

HaplyDeviceState HaplyTracker::get_raw_state() const
{
    std::lock_guard<std::mutex> lock(m_state_mutex);
    return m_state;
}

void HaplyTracker::inject_hand_data()
{
    HaplyDeviceState snapshot;
    {
        std::lock_guard<std::mutex> lock(m_state_mutex);
        snapshot = m_state;
    }

    // Determine active hand from device handedness
    const bool is_left = (snapshot.handedness == "left");

    auto& injector = is_left ? m_left_injector : m_right_injector;
    auto& other_injector = is_left ? m_right_injector : m_left_injector;

    if (!snapshot.has_data)
    {
        // No data received yet — reset injectors so runtime sees isActive=false
        injector.reset();
        other_injector.reset();
        return;
    }

    if (!injector)
    {
        // Device reconnected — lazily recreate the push device
        const auto handles = m_session->get_handles();
        XrHandEXT hand = is_left ? XR_HAND_LEFT_EXT : XR_HAND_RIGHT_EXT;
        injector = std::make_unique<plugin_utils::HandInjector>(handles.instance, handles.session, hand, handles.space);
    }

    // The other hand has no data — ensure its injector is inactive
    other_injector.reset();

    // Get controller snapshot for root tracking
    const auto& left_tracked = m_controller_tracker->get_left_controller(*m_deviceio_session);
    const auto& right_tracked = m_controller_tracker->get_right_controller(*m_deviceio_session);
    const auto& tracked = is_left ? left_tracked : right_tracked;

    bool is_root_tracked = false;
    if (tracked.data)
    {
        bool aim_valid = false;
        XrPosef raw_pose = oxr_utils::get_aim_pose(*tracked.data, aim_valid);

        if (aim_valid)
        {
            XrPosef offset_pose = is_left ? kLeftHandOffset : kRightHandOffset;
            XrPosef new_root = oxr_utils::multiply_poses(raw_pose, offset_pose);

            if (is_left)
            {
                m_left_root_pose = new_root;
            }
            else
            {
                m_right_root_pose = new_root;
            }
            is_root_tracked = true;
        }
    }

    XrPosef root_pose = is_left ? m_left_root_pose : m_right_root_pose;

    // Smooth grip interpolant based on button presses
    const bool gripping = snapshot.buttons.button_0 || snapshot.buttons.button_1 || snapshot.buttons.button_2 ||
                          snapshot.buttons.button_3;
    const float target_grip = gripping ? 1.0f : 0.0f;
    const float grip_speed = 0.15f;
    m_grip_interpolant += (target_grip - m_grip_interpolant) * grip_speed;

    // Build the local wrist pose from cursor position + VerseGrip orientation
    XrPosef wrist_local;
    wrist_local.position.x = snapshot.cursor_position.x;
    wrist_local.position.y = snapshot.cursor_position.y;
    wrist_local.position.z = snapshot.cursor_position.z;
    wrist_local.orientation.x = snapshot.orientation.x;
    wrist_local.orientation.y = snapshot.orientation.y;
    wrist_local.orientation.z = snapshot.orientation.z;
    wrist_local.orientation.w = snapshot.orientation.w;

    XrPosef wrist_world = oxr_utils::multiply_poses(root_pose, wrist_local);

    // Build hand joint locations
    XrHandJointLocationEXT joints[XR_HAND_JOINT_COUNT_EXT];

    for (uint32_t j = 0; j < XR_HAND_JOINT_COUNT_EXT; j++)
    {
        if (j == XR_HAND_JOINT_WRIST_EXT || j == XR_HAND_JOINT_PALM_EXT)
        {
            // Wrist and palm get the real tracked position + orientation
            joints[j].pose = wrist_world;
            joints[j].radius = (j == XR_HAND_JOINT_PALM_EXT) ? 0.04f : 0.03f;
            joints[j].locationFlags = XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT;

            if (is_root_tracked)
            {
                joints[j].locationFlags |=
                    XR_SPACE_LOCATION_POSITION_TRACKED_BIT | XR_SPACE_LOCATION_ORIENTATION_TRACKED_BIT;
            }
        }
        else
        {
            // All finger joints: placed at wrist position with identity orientation.
            // Marked VALID but not TRACKED (synthesised data).
            joints[j].pose = wrist_world;
            joints[j].radius = 0.008f;
            joints[j].locationFlags = XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT;
        }
    }

    // Use the OpenXR runtime clock for injection
    XrTime time = m_time_converter->os_monotonic_now();
    injector->push(joints, time);
}

} // namespace haply
} // namespace plugins
