// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio/controller_tracker.hpp>
#include <deviceio/deviceio_session.hpp>
#include <openxr/openxr.h>
#include <oxr_utils/oxr_time.hpp>
#include <plugin_utils/hand_injector.hpp>

#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

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


class __attribute__((visibility("default"))) HaplyTracker
{
public:
    static HaplyTracker& instance(const std::string& app_name = "HaplyHandPlugin") noexcept(false);

    /// Drive one update cycle: poll DeviceIOSession, read latest Haply state,
    /// map to OpenXR hand joints, and push via HandInjector.
    void update();

    /// Thread-safe snapshot of the latest raw device state.
    HaplyDeviceState get_raw_state() const;

private:
    // Lifecycle
    explicit HaplyTracker(const std::string& app_name) noexcept(false);
    ~HaplyTracker();

    HaplyTracker(const HaplyTracker&) = delete;
    HaplyTracker& operator=(const HaplyTracker&) = delete;
    HaplyTracker(HaplyTracker&&) = delete;
    HaplyTracker& operator=(HaplyTracker&&) = delete;

    void initialize(const std::string& app_name) noexcept(false);
    void shutdown();

    // WebSocket I/O thread
    void io_loop(const std::string& host, uint16_t port);

    // OpenXR hand data injection
    void inject_hand_data();

    // -- Member Variables --

    // Lifecycle
    std::mutex m_lifecycle_mutex;
    bool m_initialized = false;

    // WebSocket thread
    std::thread m_io_thread;
    std::atomic<bool> m_running{ false };

    // Haply device state (guarded by m_state_mutex)
    mutable std::mutex m_state_mutex;
    HaplyDeviceState m_state;

    // Smoothed grip interpolant [0, 1] for synthesised finger poses
    float m_grip_interpolant = 0.0f;

    // OpenXR State
    std::shared_ptr<core::OpenXRSession> m_session;
    std::unique_ptr<plugin_utils::HandInjector> m_left_injector;
    std::unique_ptr<plugin_utils::HandInjector> m_right_injector;
    std::optional<core::XrTimeConverter> m_time_converter;
    std::shared_ptr<core::ControllerTracker> m_controller_tracker;
    std::unique_ptr<core::DeviceIOSession> m_deviceio_session;

    // Persistent root poses (initialized to identity)
    XrPosef m_left_root_pose = { { 0.0f, 0.0f, 0.0f, 1.0f }, { 0.0f, 0.0f, 0.0f } };
    XrPosef m_right_root_pose = { { 0.0f, 0.0f, 0.0f, 1.0f }, { 0.0f, 0.0f, 0.0f } };
};

} // namespace haply
} // namespace plugins
