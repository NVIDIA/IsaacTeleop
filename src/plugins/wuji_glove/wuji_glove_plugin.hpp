// SPDX-FileCopyrightText: Copyright (c) 2026 Wuji Technology. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_session/deviceio_session.hpp>
#include <openxr/openxr.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/oxr_time.hpp>
#include <plugin_utils/hand_injector.hpp>

extern "C"
{
#include <wuji_sdk.h>
}

#include <array>
#include <atomic>
#include <chrono>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

namespace plugins
{
namespace wuji_glove
{

// Wuji glove -> OpenXR hand-tracking device plugin.
//
// Reads the glove's 21-joint MediaPipe skeleton via the wuji_sdk C API
// (callback-based subscription), converts each frame to a 26-joint
// XrHandJointLocationEXT set, and injects it into the OpenXR hand layer via
// plugin_utils::HandInjector. The existing core::HandTracker consumes it.
class WujiGlovePlugin
{
public:
    explicit WujiGlovePlugin(const std::string& plugin_root_id) noexcept(false);
    ~WujiGlovePlugin();

    bool is_running() const noexcept;
    bool has_failed() const noexcept;

    WujiGlovePlugin(const WujiGlovePlugin&) = delete;
    WujiGlovePlugin& operator=(const WujiGlovePlugin&) = delete;
    WujiGlovePlugin(WujiGlovePlugin&&) = delete;
    WujiGlovePlugin& operator=(WujiGlovePlugin&&) = delete;

private:
    // Latest converted joints for one hand, plus freshness bookkeeping.
    struct HandFrame
    {
        std::array<XrHandJointLocationEXT, XR_HAND_JOINT_COUNT_EXT> joints{};
        bool valid = false;
        std::chrono::steady_clock::time_point stamp{};
    };

    void worker_thread();
    void connection_thread();

    // Per-subscription context passed as user_data: identifies the plugin and
    // which hand this glove's frames belong to. The side is resolved explicitly
    // via wuji_glove_get_hand_side() at connect time (not from frame contents).
    struct SubContext
    {
        WujiGlovePlugin* self = nullptr;
        bool is_left = false;
        std::atomic<bool> terminal{ false };
    };

    struct GloveConnection
    {
        std::string serial;
        WujiDevice* device = nullptr;
        WujiSub* subscription = nullptr;
        std::unique_ptr<SubContext> context;
    };

    // wuji_sdk subscription callback (C ABI). user_data == SubContext*.
    static void skeleton_callback(WujiFrameKind kind, const WujiHandSkeleton* frame, void* user_data);
    void on_skeleton(const WujiHandSkeleton* frame, bool is_left);
    void invalidate_hand(bool is_left);

    bool connect_glove(GloveConnection& connection);
    void disconnect_glove(GloveConnection& connection);
    void discover_gloves();

    // Push (or reset) one hand's injector based on the latest HandFrame.
    void pump_hand(std::unique_ptr<plugin_utils::HandInjector>& injector,
                   XrHandEXT hand,
                   const HandFrame& frame,
                   XrTime time);

    std::shared_ptr<core::OpenXRSession> m_session;
    std::unique_ptr<core::DeviceIOSession> m_deviceio_session;
    std::unique_ptr<plugin_utils::HandInjector> m_left_injector;
    std::unique_ptr<plugin_utils::HandInjector> m_right_injector;
    std::optional<core::XrTimeConverter> m_time_converter;

    // Owned exclusively by m_connection_thread until it is joined.
    std::vector<std::unique_ptr<GloveConnection>> m_connections;

    std::mutex m_frame_mutex;
    HandFrame m_left;
    HandFrame m_right;

    std::thread m_thread;
    std::thread m_connection_thread;
    std::atomic<bool> m_running{ false };
    std::atomic<bool> m_failed{ false };
    std::string m_root_id;
};

} // namespace wuji_glove
} // namespace plugins
