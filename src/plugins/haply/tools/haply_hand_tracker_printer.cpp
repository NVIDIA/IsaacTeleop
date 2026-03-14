// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Standalone debugging tool that connects directly to the Haply SDK WebSocket
// and prints raw device state.  Does NOT require OpenXR — useful for verifying
// the Haply hardware and SDK service independently of the Isaac Teleop stack.

#include <arpa/inet.h>
#include <netinet/tcp.h>
#include <nlohmann/json.hpp>
#include <sys/socket.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <netdb.h>
#include <random>
#include <signal.h>
#include <string>
#include <thread>
#include <unistd.h>
#include <vector>

using json = nlohmann::json;

// ============================================================================
// Lightweight WebSocket client (duplicated from the plugin to stay standalone)
// ============================================================================
namespace
{

class MiniWebSocket
{
public:
    MiniWebSocket() = default;
    ~MiniWebSocket()
    {
        close();
    }

    MiniWebSocket(const MiniWebSocket&) = delete;
    MiniWebSocket& operator=(const MiniWebSocket&) = delete;

    bool connect(const std::string& host, uint16_t port, const std::string& path = "/")
    {
        close();

        struct addrinfo hints
        {
        };
        hints.ai_family = AF_INET;
        hints.ai_socktype = SOCK_STREAM;
        struct addrinfo* res = nullptr;
        std::string port_str = std::to_string(port);
        if (getaddrinfo(host.c_str(), port_str.c_str(), &hints, &res) != 0 || !res)
        {
            return false;
        }

        fd_ = ::socket(res->ai_family, res->ai_socktype, res->ai_protocol);
        if (fd_ < 0)
        {
            freeaddrinfo(res);
            return false;
        }

        if (::connect(fd_, res->ai_addr, res->ai_addrlen) < 0)
        {
            freeaddrinfo(res);
            ::close(fd_);
            fd_ = -1;
            return false;
        }
        freeaddrinfo(res);

        int flag = 1;
        setsockopt(fd_, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));

        // Random WebSocket key
        std::random_device rd;
        std::mt19937 gen(rd());
        std::uniform_int_distribution<> dis(0, 255);
        uint8_t key_bytes[16];
        for (int i = 0; i < 16; ++i)
        {
            key_bytes[i] = static_cast<uint8_t>(dis(gen));
        }

        static const char* b64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        std::string ws_key;
        ws_key.reserve(24);
        for (int i = 0; i < 16; i += 3)
        {
            uint32_t n = (static_cast<uint32_t>(key_bytes[i]) << 16);
            if (i + 1 < 16)
                n |= (static_cast<uint32_t>(key_bytes[i + 1]) << 8);
            if (i + 2 < 16)
                n |= static_cast<uint32_t>(key_bytes[i + 2]);
            ws_key += b64[(n >> 18) & 0x3F];
            ws_key += b64[(n >> 12) & 0x3F];
            ws_key += (i + 1 < 16) ? b64[(n >> 6) & 0x3F] : '=';
            ws_key += (i + 2 < 16) ? b64[n & 0x3F] : '=';
        }

        std::string req = "GET " + path + " HTTP/1.1\r\nHost: " + host + ":" + std::to_string(port) +
                          "\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: " + ws_key +
                          "\r\nSec-WebSocket-Version: 13\r\n\r\n";

        if (!send_raw(req.data(), req.size()))
        {
            close();
            return false;
        }

        std::string resp;
        char buf;
        while (resp.size() < 4096)
        {
            if (!recv_raw(&buf, 1))
            {
                close();
                return false;
            }
            resp += buf;
            if (resp.size() >= 4 && resp.substr(resp.size() - 4) == "\r\n\r\n")
            {
                break;
            }
        }

        if (resp.find("101") == std::string::npos)
        {
            close();
            return false;
        }

        return true;
    }

    bool send_text(const std::string& payload)
    {
        return send_frame(0x01, payload.data(), payload.size());
    }

    bool recv_text(std::string& out)
    {
        if (fd_ < 0)
            return false;
        out.clear();
        bool fin = false;
        while (!fin)
        {
            uint8_t hdr[2];
            if (!recv_raw(hdr, 2))
                return false;
            fin = (hdr[0] & 0x80) != 0;
            uint8_t opcode = hdr[0] & 0x0F;
            bool masked = (hdr[1] & 0x80) != 0;
            uint64_t plen = hdr[1] & 0x7F;
            if (plen == 126)
            {
                uint8_t e[2];
                if (!recv_raw(e, 2))
                    return false;
                plen = (uint64_t(e[0]) << 8) | e[1];
            }
            else if (plen == 127)
            {
                uint8_t e[8];
                if (!recv_raw(e, 8))
                    return false;
                plen = 0;
                for (int i = 0; i < 8; ++i)
                    plen = (plen << 8) | e[i];
            }
            uint8_t mask[4] = {};
            if (masked && !recv_raw(mask, 4))
                return false;
            constexpr uint64_t kMaxPayloadSize = 16 * 1024 * 1024; // 16 MB
            if (plen > kMaxPayloadSize)
            {
                std::cerr << "[MiniWebSocket] Payload too large: " << plen << " bytes" << std::endl;
                return false;
            }
            std::vector<uint8_t> data(plen);
            if (plen > 0)
            {
                if (!recv_raw(data.data(), plen))
                    return false;
                if (masked)
                    for (size_t i = 0; i < plen; ++i)
                        data[i] ^= mask[i % 4];
            }
            if (opcode == 0x08)
            {
                send_frame(0x08, data.data(), data.size());
                return false;
            }
            if (opcode == 0x09)
            {
                send_frame(0x0A, data.data(), data.size());
                continue;
            }
            if (opcode == 0x0A)
                continue;
            out.append(reinterpret_cast<char*>(data.data()), data.size());
        }
        return true;
    }

    void close()
    {
        if (fd_ >= 0)
        {
            send_frame(0x08, nullptr, 0);
            ::close(fd_);
            fd_ = -1;
        }
    }

    bool is_connected() const
    {
        return fd_ >= 0;
    }

private:
    bool send_raw(const void* d, size_t len)
    {
        const uint8_t* p = static_cast<const uint8_t*>(d);
        size_t s = 0;
        while (s < len)
        {
            ssize_t n = ::send(fd_, p + s, len - s, MSG_NOSIGNAL);
            if (n <= 0)
                return false;
            s += size_t(n);
        }
        return true;
    }

    bool recv_raw(void* d, size_t len)
    {
        uint8_t* p = static_cast<uint8_t*>(d);
        size_t r = 0;
        while (r < len)
        {
            ssize_t n = ::recv(fd_, p + r, len - r, 0);
            if (n <= 0)
                return false;
            r += size_t(n);
        }
        return true;
    }

    bool send_frame(uint8_t opcode, const void* payload, size_t len)
    {
        if (fd_ < 0)
            return false;
        std::vector<uint8_t> f;
        f.reserve(14 + len);
        f.push_back(0x80 | opcode);
        if (len <= 125)
            f.push_back(0x80 | uint8_t(len));
        else if (len <= 65535)
        {
            f.push_back(0x80 | 126);
            f.push_back(uint8_t((len >> 8) & 0xFF));
            f.push_back(uint8_t(len & 0xFF));
        }
        else
        {
            f.push_back(0x80 | 127);
            for (int i = 7; i >= 0; --i)
                f.push_back(uint8_t((len >> (8 * i)) & 0xFF));
        }
        std::random_device rd;
        std::mt19937 gen(rd());
        std::uniform_int_distribution<> dis(0, 255);
        uint8_t mask[4];
        for (int i = 0; i < 4; ++i)
        {
            mask[i] = uint8_t(dis(gen));
            f.push_back(mask[i]);
        }
        const uint8_t* src = static_cast<const uint8_t*>(payload);
        for (size_t i = 0; i < len; ++i)
            f.push_back(src[i] ^ mask[i % 4]);
        return send_raw(f.data(), f.size());
    }

    int fd_ = -1;
};

std::atomic<bool> g_running{ true };

void signal_handler(int)
{
    g_running.store(false);
}

} // namespace

int main(int argc, char** argv)
{
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);

    const char* host_env = std::getenv("HAPLY_WEBSOCKET_HOST");
    std::string host = host_env ? host_env : "127.0.0.1";
    uint16_t port = 10001;
    const char* port_env = std::getenv("HAPLY_WEBSOCKET_PORT");
    if (port_env)
    {
        try
        {
            unsigned long parsed = std::stoul(port_env);
            if (parsed == 0 || parsed > 65535)
            {
                std::cerr << "[Haply] Invalid HAPLY_WEBSOCKET_PORT value: " << port_env << ", using default 10001"
                          << std::endl;
            }
            else
            {
                port = static_cast<uint16_t>(parsed);
            }
        }
        catch (const std::exception&)
        {
            std::cerr << "[Haply] Invalid HAPLY_WEBSOCKET_PORT value: " << port_env << ", using default 10001"
                      << std::endl;
        }
    }

    std::cout << "Haply Hand Tracker Printer" << std::endl;
    std::cout << "Connecting to " << host << ":" << port << " ..." << std::endl;

    MiniWebSocket ws;
    int reconnect_delay_ms = 500;
    constexpr int max_reconnect_delay_ms = 10000;
    int frame = 0;

    while (g_running.load())
    {
        if (!ws.connect(host, port, "/"))
        {
            std::cerr << "Connection failed, retrying in " << reconnect_delay_ms << " ms" << std::endl;
            std::this_thread::sleep_for(std::chrono::milliseconds(reconnect_delay_ms));
            reconnect_delay_ms = std::min(reconnect_delay_ms * 2, max_reconnect_delay_ms);
            continue;
        }

        std::cout << "Connected!" << std::endl;
        reconnect_delay_ms = 500;

        while (g_running.load() && ws.is_connected())
        {
            std::string msg;
            if (!ws.recv_text(msg))
            {
                std::cerr << "Connection lost" << std::endl;
                break;
            }

            try
            {
                json j = json::parse(msg);

                std::string device_id;
                float px = 0, py = 0, pz = 0;
                float vx = 0, vy = 0, vz = 0;
                float ow = 1, ox = 0, oy = 0, oz = 0;
                bool b0 = false, b1 = false, b2 = false, b3 = false;
                std::string handedness = "unknown";
                bool has_inv3 = false;
                bool has_vg = false;

                if (j.contains("inverse3") && j["inverse3"].is_array() && !j["inverse3"].empty())
                {
                    has_inv3 = true;
                    const auto& inv3 = j["inverse3"][0];
                    if (inv3.contains("device_id"))
                    {
                        device_id = inv3["device_id"].get<std::string>();
                    }
                    if (inv3.contains("config") && inv3["config"].contains("handedness"))
                    {
                        handedness = inv3["config"]["handedness"].get<std::string>();
                    }
                    if (inv3.contains("state"))
                    {
                        const auto& st = inv3["state"];
                        if (st.contains("cursor_position"))
                        {
                            const auto& p = st["cursor_position"];
                            px = p.value("x", 0.0f);
                            py = p.value("y", 0.0f);
                            pz = p.value("z", 0.0f);
                        }
                        if (st.contains("cursor_velocity"))
                        {
                            const auto& v = st["cursor_velocity"];
                            vx = v.value("x", 0.0f);
                            vy = v.value("y", 0.0f);
                            vz = v.value("z", 0.0f);
                        }
                    }
                }

                if (j.contains("wireless_verse_grip") && j["wireless_verse_grip"].is_array() &&
                    !j["wireless_verse_grip"].empty())
                {
                    has_vg = true;
                    const auto& vg = j["wireless_verse_grip"][0];
                    if (vg.contains("state"))
                    {
                        const auto& st = vg["state"];
                        if (st.contains("orientation"))
                        {
                            const auto& o = st["orientation"];
                            ow = o.value("w", 1.0f);
                            ox = o.value("x", 0.0f);
                            oy = o.value("y", 0.0f);
                            oz = o.value("z", 0.0f);
                        }
                        if (st.contains("buttons"))
                        {
                            const auto& btn = st["buttons"];
                            b0 = btn.value("button_0", false);
                            b1 = btn.value("button_1", false);
                            b2 = btn.value("button_2", false);
                            b3 = btn.value("button_3", false);
                        }
                    }
                }

                // Print every 10th frame to avoid flooding the terminal
                if (frame % 10 == 0)
                {
                    std::cout << "\n=== Frame " << frame << " ===" << std::endl;
                    if (has_inv3)
                    {
                        std::cout << "  Inverse3  [" << device_id << "]  hand=" << handedness << std::endl;
                        std::cout << "    pos=(" << std::fixed << std::setprecision(4) << px << ", " << py << ", " << pz
                                  << ")" << std::endl;
                        std::cout << "    vel=(" << vx << ", " << vy << ", " << vz << ")" << std::endl;
                    }
                    if (has_vg)
                    {
                        std::cout << "  VerseGrip" << std::endl;
                        std::cout << "    ori=(w=" << ow << ", x=" << ox << ", y=" << oy << ", z=" << oz << ")"
                                  << std::endl;
                        std::cout << "    btn=[" << b0 << ", " << b1 << ", " << b2 << ", " << b3 << "]" << std::endl;
                    }
                    std::cout << std::flush;
                }

                // Send zero-force command to keep the stream alive
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

                ++frame;
            }
            catch (const json::exception& e)
            {
                std::cerr << "JSON parse error: " << e.what() << std::endl;
            }
        }

        ws.close();
    }

    std::cout << "\nDone." << std::endl;
    return 0;
}
