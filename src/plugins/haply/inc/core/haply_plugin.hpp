// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <pusherio/schema_pusher.hpp>

#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

namespace core
{
class OpenXRSession;
}

namespace plugins
{
namespace haply
{

/// 3-component vector (position / velocity / force).
struct HaplyVec3
{
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};

/// Quaternion orientation (w, x, y, z).
struct HaplyQuat
{
    float w = 1.0f;
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};

/// Button state snapshot from a VerseGrip controller.
struct HaplyButtons
{
    bool button_0 = false;
    bool button_1 = false;
    bool button_2 = false;
    bool button_3 = false;
};

/// Aggregated, mutex-guarded state received from the Haply SDK.
struct HaplyDeviceState
{
    // Inverse3
    std::string inverse3_device_id;
    HaplyVec3 cursor_position;
    HaplyVec3 cursor_velocity;

    // VerseGrip
    std::string versegrip_device_id;
    HaplyQuat orientation;
    HaplyButtons buttons;

    // Handedness detected from the first config message ("left" or "right").
    // Defaults to "right" when not yet received.
    std::string handedness = "right";

    // True once we have received at least one message from the Haply SDK.
    bool has_data = false;
};


/// Minimal WebSocket client for communicating with the Haply SDK service on localhost.
/// Supports text-frame read/write, ping/pong, and clean close over unencrypted TCP.
class HaplyWebSocket
{
public:
    HaplyWebSocket();
    ~HaplyWebSocket();

    HaplyWebSocket(const HaplyWebSocket&) = delete;
    HaplyWebSocket& operator=(const HaplyWebSocket&) = delete;

    /// Connect and perform the HTTP upgrade handshake.
    /// @return true on success.
    bool connect(const std::string& host, uint16_t port, const std::string& path = "/");

    /// Send a UTF-8 text frame.
    bool send_text(const std::string& payload);

    /// Receive a complete text frame (blocks until one arrives or error/close).
    /// @return true on success; the payload is written to @p out.
    bool recv_text(std::string& out);

    /// Perform a clean WebSocket close handshake and tear down the socket.
    void close();

    /// @return true when the underlying socket is connected.
    bool is_connected() const;

private:
    bool send_raw(const void* data, size_t len);
    bool recv_raw(void* data, size_t len);
    bool send_frame(uint8_t opcode, const void* payload, size_t len);

    int fd_ = -1;
};


/*!
 * @brief Reads Haply Inverse3 + VerseGrip state via WebSocket and pushes
 *        HaplyDeviceOutput FlatBuffers via OpenXR SchemaPusher.
 *
 * This plugin connects to the Haply SDK WebSocket service, parses JSON
 * device state messages, and serializes them into the HaplyDeviceOutput
 * FlatBuffer schema for consumption by the Isaac Teleop pipeline.
 *
 * The raw device data (cursor position, velocity, orientation, buttons)
 * flows directly through the SchemaPusher → SchemaTracker → IDeviceIOSource
 * pipeline without any lossy conversion to OpenXR hand joint format.
 */
class __attribute__((visibility("default"))) HaplyPlugin
{
public:
    /*!
     * @brief Construct the plugin and start the WebSocket connection.
     * @param collection_id OpenXR tensor collection identifier.
     * @param app_name OpenXR application name.
     * @throws std::runtime_error if OpenXR initialization fails.
     */
    explicit HaplyPlugin(const std::string& collection_id = "haply_device",
                         const std::string& app_name = "HaplyPlugin");
    ~HaplyPlugin();

    HaplyPlugin(const HaplyPlugin&) = delete;
    HaplyPlugin& operator=(const HaplyPlugin&) = delete;
    HaplyPlugin(HaplyPlugin&&) = delete;
    HaplyPlugin& operator=(HaplyPlugin&&) = delete;

    /*!
     * @brief Push the latest device state as a HaplyDeviceOutput FlatBuffer.
     *
     * Should be called at the desired push rate (e.g. 90 Hz).
     * If no data has been received from the Haply SDK yet, this is a no-op.
     */
    void update();

    /// Thread-safe snapshot of the latest raw device state.
    HaplyDeviceState get_raw_state() const;

private:
    void initialize(const std::string& collection_id, const std::string& app_name);
    void shutdown();

    // WebSocket I/O thread
    void io_loop(const std::string& host, uint16_t port);

    // Push current state via SchemaPusher
    void push_current_state();

    // Lifecycle
    std::mutex m_lifecycle_mutex;
    bool m_initialized = false;

    // WebSocket thread
    std::thread m_io_thread;
    std::atomic<bool> m_running{false};

    // Haply device state (guarded by m_state_mutex)
    mutable std::mutex m_state_mutex;
    HaplyDeviceState m_state;

    // OpenXR session and SchemaPusher
    std::shared_ptr<core::OpenXRSession> m_session;
    std::unique_ptr<core::SchemaPusher> m_pusher;
};

} // namespace haply
} // namespace plugins
