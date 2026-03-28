// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "third_party/nlohmann/json.hpp"

#include <arpa/inet.h>
#include <core/haply_plugin.hpp>
#include <netinet/tcp.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/os_time.hpp>
#include <schema/haply_device_generated.h>
#include <sys/socket.h>

#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <flatbuffers/flatbuffers.h>
#include <iostream>
#include <memory>
#include <netdb.h>
#include <random>
#include <unistd.h>

using json = nlohmann::json;

namespace plugins
{
namespace haply
{

namespace
{
constexpr size_t kMaxFlatbufferSize = 256;
} // namespace

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

    // Set receive timeout to avoid blocking indefinitely
    struct timeval tv;
    tv.tv_sec = 5;
    tv.tv_usec = 0;
    if (setsockopt(fd_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv)) < 0)
    {
        std::cerr << "[HaplyWebSocket] Warning: Failed to set SO_RCVTIMEO: " << strerror(errno) << std::endl;
    }

    // Disable Nagle's algorithm for lower latency
    int flag = 1;
    if (setsockopt(fd_, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag)) < 0)
    {
        std::cerr << "[HaplyWebSocket] Warning: Failed to set TCP_NODELAY: " << strerror(errno) << std::endl;
    }

    // Generate a random 16-byte WebSocket key
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> dis(0, 255);
    uint8_t key_bytes[16];
    for (int i = 0; i < 16; ++i)
    {
        key_bytes[i] = static_cast<uint8_t>(dis(gen));
    }

    // Base64 encode the key
    static const char* b64_table = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string ws_key;
    ws_key.reserve(24);
    for (int i = 0; i < 16; i += 3)
    {
        uint32_t n = (static_cast<uint32_t>(key_bytes[i]) << 16);
        if (i + 1 < 16)
            n |= (static_cast<uint32_t>(key_bytes[i + 1]) << 8);
        if (i + 2 < 16)
            n |= static_cast<uint32_t>(key_bytes[i + 2]);
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
        return false;

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
        return false;

    out.clear();

    bool fin = false;
    while (!fin)
    {
        uint8_t header[2];
        if (!recv_raw(header, 2))
            return false;

        fin = (header[0] & 0x80) != 0;
        uint8_t opcode = header[0] & 0x0F;
        bool masked = (header[1] & 0x80) != 0;
        uint64_t payload_len = header[1] & 0x7F;

        if (payload_len == 126)
        {
            uint8_t ext[2];
            if (!recv_raw(ext, 2))
                return false;
            payload_len = (static_cast<uint64_t>(ext[0]) << 8) | ext[1];
        }
        else if (payload_len == 127)
        {
            uint8_t ext[8];
            if (!recv_raw(ext, 8))
                return false;
            payload_len = 0;
            for (int i = 0; i < 8; ++i)
            {
                payload_len = (payload_len << 8) | ext[i];
            }
        }

        constexpr uint64_t kMaxPayloadSize = 16 * 1024 * 1024; // 16 MB
        if (payload_len > kMaxPayloadSize)
        {
            std::cerr << "[HaplyWebSocket] Payload too large: " << payload_len << " bytes" << std::endl;
            return false;
        }

        uint8_t mask[4] = {0, 0, 0, 0};
        if (masked)
        {
            if (!recv_raw(mask, 4))
                return false;
        }

        std::vector<uint8_t> data(payload_len);
        if (payload_len > 0)
        {
            if (!recv_raw(data.data(), payload_len))
                return false;
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
            // Close frame - send close response
            send_frame(0x08, data.data(), data.size());
            return false;
        }
        else if (opcode == 0x09)
        {
            // Ping - respond with pong
            send_frame(0x0A, data.data(), data.size());
            continue;
        }
        else if (opcode == 0x0A)
        {
            // Pong - ignore
            continue;
        }
        else if (opcode == 0x01 || opcode == 0x00)
        {
            // Text or continuation
            out.append(reinterpret_cast<char*>(data.data()), data.size());
        }
        else
        {
            // Binary or unknown
            out.append(reinterpret_cast<char*>(data.data()), data.size());
        }
    }

    return true;
}

void HaplyWebSocket::close()
{
    if (fd_ >= 0)
    {
        send_frame(0x08, nullptr, 0);
        ::close(fd_);
        fd_ = -1;
    }
}

// ============================================================================
// HaplyPlugin implementation
// ============================================================================

HaplyPlugin::HaplyPlugin(const std::string& collection_id, const std::string& app_name)
{
    initialize(collection_id, app_name);
}

HaplyPlugin::~HaplyPlugin()
{
    {
        std::lock_guard<std::mutex> lock(m_lifecycle_mutex);
        if (!m_initialized)
        {
            return;
        }
        m_initialized = false;
    }

    shutdown();
}

void HaplyPlugin::initialize(const std::string& collection_id, const std::string& app_name)
{
    std::cout << "Initializing Haply Plugin..." << std::endl;

    // Read WebSocket config from environment
    const char* host_env = std::getenv("HAPLY_WS_HOST");
    std::string ws_host = host_env ? host_env : "127.0.0.1";
    uint16_t ws_port = 10001;
    const char* port_env = std::getenv("HAPLY_WS_PORT");
    if (port_env)
    {
        try
        {
            unsigned long parsed = std::stoul(port_env);
            if (parsed == 0 || parsed > 65535)
            {
                std::cerr << "[Haply] Invalid HAPLY_WS_PORT value: " << port_env << ", using default 10001" << std::endl;
            }
            else
            {
                ws_port = static_cast<uint16_t>(parsed);
            }
        }
        catch (const std::exception&)
        {
            std::cerr << "[Haply] Invalid HAPLY_WS_PORT value: " << port_env << ", using default 10001" << std::endl;
        }
    }

    std::cout << "Connecting to Haply SDK at " << ws_host << ":" << ws_port << std::endl;

    // Start WebSocket I/O thread
    m_running.store(true);
    m_io_thread = std::thread(&HaplyPlugin::io_loop, this, ws_host, ws_port);

    // Wait briefly for connection to establish
    std::this_thread::sleep_for(std::chrono::milliseconds(500));

    // Create OpenXR session with SchemaPusher extensions
    auto required_extensions = core::SchemaPusher::get_required_extensions();
    m_session = std::make_shared<core::OpenXRSession>(app_name, required_extensions);
    auto handles = m_session->get_handles();

    // Create the SchemaPusher
    m_pusher = std::make_unique<core::SchemaPusher>(
        handles,
        core::SchemaPusherConfig{
            .collection_id = collection_id,
            .max_flatbuffer_size = kMaxFlatbufferSize,
            .tensor_identifier = "haply_device",
            .localized_name = "Haply Inverse3 + VerseGrip",
            .app_name = app_name});

    std::cout << "OpenXR session and SchemaPusher initialized (collection: " << collection_id << ")" << std::endl;

    std::lock_guard<std::mutex> lock(m_lifecycle_mutex);
    m_initialized = true;
}

void HaplyPlugin::shutdown()
{
    if (m_running.load())
    {
        m_running.store(false);
        if (m_io_thread.joinable())
        {
            m_io_thread.join();
        }
        std::cout << "Haply Plugin shutdown complete" << std::endl;
    }
}

void HaplyPlugin::update()
{
    push_current_state();
}

HaplyDeviceState HaplyPlugin::get_raw_state() const
{
    std::lock_guard<std::mutex> lock(m_state_mutex);
    return m_state;
}

void HaplyPlugin::push_current_state()
{
    HaplyDeviceState snapshot;
    {
        std::lock_guard<std::mutex> lock(m_state_mutex);
        if (!m_state.has_data)
        {
            return; // No data yet, skip
        }
        snapshot = m_state;
    }

    core::HaplyDeviceOutputT out;
    out.cursor_position_x = snapshot.cursor_position.x;
    out.cursor_position_y = snapshot.cursor_position.y;
    out.cursor_position_z = snapshot.cursor_position.z;
    out.cursor_velocity_x = snapshot.cursor_velocity.x;
    out.cursor_velocity_y = snapshot.cursor_velocity.y;
    out.cursor_velocity_z = snapshot.cursor_velocity.z;
    out.orientation_w = snapshot.orientation.w;
    out.orientation_x = snapshot.orientation.x;
    out.orientation_y = snapshot.orientation.y;
    out.orientation_z = snapshot.orientation.z;
    out.button_0 = snapshot.buttons.button_0;
    out.button_1 = snapshot.buttons.button_1;
    out.button_2 = snapshot.buttons.button_2;
    out.button_3 = snapshot.buttons.button_3;
    out.handedness = (snapshot.handedness == "left") ? 1 : 0;

    auto sample_time_ns = core::os_monotonic_now_ns();

    flatbuffers::FlatBufferBuilder builder(kMaxFlatbufferSize);
    auto offset = core::HaplyDeviceOutput::Pack(builder, &out);
    builder.Finish(offset);
    m_pusher->push_buffer(builder.GetBufferPointer(), builder.GetSize(), sample_time_ns, sample_time_ns);
}

void HaplyPlugin::io_loop(const std::string& host, uint16_t port)
{
    HaplyWebSocket ws;
    int reconnect_delay_ms = 500;
    constexpr int max_reconnect_delay_ms = 10000;

    while (m_running.load())
    {
        if (!ws.connect(host, port, "/"))
        {
            std::cerr << "[HaplyPlugin] Connection failed, retrying in " << reconnect_delay_ms << " ms" << std::endl;
            std::this_thread::sleep_for(std::chrono::milliseconds(reconnect_delay_ms));
            reconnect_delay_ms = std::min(reconnect_delay_ms * 2, max_reconnect_delay_ms);
            continue;
        }

        std::cout << "[HaplyPlugin] Connected to Haply SDK" << std::endl;
        reconnect_delay_ms = 500;

        while (m_running.load() && ws.is_connected())
        {
            std::string msg;
            if (!ws.recv_text(msg))
            {
                std::cerr << "[HaplyPlugin] Connection lost" << std::endl;
                break;
            }

            try
            {
                json j = json::parse(msg);

                // Parse into local variables first to minimize mutex hold time
                std::string inverse3_device_id;
                std::string versegrip_device_id;
                std::string handedness;
                HaplyVec3 cursor_position{};
                HaplyVec3 cursor_velocity{};
                HaplyQuat orientation{1.0f, 0.0f, 0.0f, 0.0f};
                HaplyButtons buttons{};
                bool has_inverse3 = false;
                bool has_versegrip = false;
                bool has_handedness = false;

                // Parse inverse3 array
                if (j.contains("inverse3") && j["inverse3"].is_array() && !j["inverse3"].empty())
                {
                    const auto& inv3 = j["inverse3"][0];
                    if (inv3.contains("device_id"))
                    {
                        inverse3_device_id = inv3["device_id"].get<std::string>();
                    }
                    if (inv3.contains("config") && inv3["config"].contains("handedness"))
                    {
                        handedness = inv3["config"]["handedness"].get<std::string>();
                        has_handedness = true;
                    }
                    if (inv3.contains("state"))
                    {
                        const auto& st = inv3["state"];
                        if (st.contains("cursor_position"))
                        {
                            const auto& pos = st["cursor_position"];
                            cursor_position.x = pos.value("x", 0.0f);
                            cursor_position.y = pos.value("y", 0.0f);
                            cursor_position.z = pos.value("z", 0.0f);
                        }
                        if (st.contains("cursor_velocity"))
                        {
                            const auto& vel = st["cursor_velocity"];
                            cursor_velocity.x = vel.value("x", 0.0f);
                            cursor_velocity.y = vel.value("y", 0.0f);
                            cursor_velocity.z = vel.value("z", 0.0f);
                        }
                    }
                    has_inverse3 = true;
                }

                // Parse wireless_verse_grip array
                if (j.contains("wireless_verse_grip") && j["wireless_verse_grip"].is_array() &&
                    !j["wireless_verse_grip"].empty())
                {
                    const auto& vg = j["wireless_verse_grip"][0];
                    if (vg.contains("device_id"))
                    {
                        versegrip_device_id = vg["device_id"].get<std::string>();
                    }
                    if (vg.contains("state"))
                    {
                        const auto& st = vg["state"];
                        if (st.contains("orientation"))
                        {
                            const auto& ori = st["orientation"];
                            orientation.w = ori.value("w", 1.0f);
                            orientation.x = ori.value("x", 0.0f);
                            orientation.y = ori.value("y", 0.0f);
                            orientation.z = ori.value("z", 0.0f);
                        }
                        if (st.contains("buttons"))
                        {
                            const auto& btn = st["buttons"];
                            buttons.button_0 = btn.value("button_0", false);
                            buttons.button_1 = btn.value("button_1", false);
                            buttons.button_2 = btn.value("button_2", false);
                            buttons.button_3 = btn.value("button_3", false);
                        }
                    }
                    has_versegrip = true;
                }

                // Brief lock to update shared state
                {
                    std::lock_guard<std::mutex> lock(m_state_mutex);
                    if (has_inverse3)
                    {
                        m_state.inverse3_device_id = std::move(inverse3_device_id);
                        m_state.cursor_position = cursor_position;
                        m_state.cursor_velocity = cursor_velocity;
                        m_state.has_data = true;
                    }
                    if (has_handedness)
                    {
                        m_state.handedness = std::move(handedness);
                    }
                    if (has_versegrip)
                    {
                        m_state.versegrip_device_id = std::move(versegrip_device_id);
                        m_state.orientation = orientation;
                        m_state.buttons = buttons;
                        m_state.has_data = true;
                    }
                }

                // Send a command to keep receiving updates (set zero force) — outside lock
                std::string device_id;
                {
                    std::lock_guard<std::mutex> lock(m_state_mutex);
                    device_id = m_state.inverse3_device_id;
                }
                if (!device_id.empty())
                {
                    json cmd;
                    cmd["inverse3"] = json::array();
                    json dev;
                    dev["device_id"] = device_id;
                    dev["commands"]["set_cursor_force"]["values"]["x"] = 0;
                    dev["commands"]["set_cursor_force"]["values"]["y"] = 0;
                    dev["commands"]["set_cursor_force"]["values"]["z"] = 0;
                    cmd["inverse3"].push_back(dev);
                    ws.send_text(cmd.dump());
                }
            }
            catch (const json::exception& e)
            {
                std::cerr << "[HaplyPlugin] JSON parse error: " << e.what() << std::endl;
            }
        }

        ws.close();
    }
}

} // namespace haply
} // namespace plugins
