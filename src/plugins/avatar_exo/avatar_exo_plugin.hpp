// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <avatar_sdk/AvatarSDK.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/oxr_time.hpp>
#include <plugin_utils/hand_injector.hpp>
#include <pusherio/schema_pusher.hpp>

#include <atomic>
#include <memory>
#include <optional>
#include <string>
#include <thread>
#include <vector>

namespace plugins
{
namespace avatar_exo
{

//! The three Avatar glove data sets this plugin can publish. Any subset may be enabled.
enum class DataSet
{
    RAW,   //!< Raw joint angles -> JointStateOutput (generic joint-space path).
    ROBOT, //!< Retargeted robot joint frame -> JointStateOutput (generic joint-space path).
    HUMAN  //!< Hand-skeleton landmarks -> OpenXR hand tracking (HandsSource path).
};

//! Init-time configuration. The set of data sets / sides is fixed for the process lifetime.
struct AvatarExoConfig
{
    bool raw = false;
    bool robot = false;
    bool human = false;

    bool left = true;
    bool right = true;

    //! Prefix for joint-space collection ids: "<prefix>_raw_<side>" / "<prefix>_robot_<side>".
    std::string collection_prefix = "avatar";

    //! Avatar SDK init JSON (the contents of an sdk_config.json, or "{}" for defaults).
    std::string sdk_config_json = "{}";

    //! Publish/poll rate for the worker loop.
    int rate_hz = 90;
};

/*!
 * @brief Streams Avatar exoskeleton-glove data into Isaac Teleop.
 *
 * One process owns a single OpenXR session and the Avatar SDK singleton. For every connected
 * glove (left/right) the enabled data sets are forwarded each frame:
 *   - RAW / ROBOT  -> a `JointStateOutput` FlatBuffer pushed via `core::SchemaPusher`
 *                     (consumed by a `JointStateTracker` / `JointStateSource` on the host).
 *   - HUMAN        -> 26 OpenXR hand joints injected via `plugin_utils::HandInjector`
 *                     (consumed by the runtime hand tracker / `HandsSource`).
 *
 * The OpenXR session is created up front (a genuine fatal error if it fails), but Avatar SDK
 * init and glove discovery are done lazily in the worker and **retried** rather than aborting:
 * a glove that is unplugged, or a backend that is not up yet, must not crash the host
 * `TeleopSession` (which treats any plugin exit as a fatal crash). Gloves are picked up as soon
 * as they appear.
 */
class AvatarExoPlugin
{
public:
    explicit AvatarExoPlugin(const AvatarExoConfig& config) noexcept(false);
    ~AvatarExoPlugin();

    AvatarExoPlugin(const AvatarExoPlugin&) = delete;
    AvatarExoPlugin& operator=(const AvatarExoPlugin&) = delete;
    AvatarExoPlugin(AvatarExoPlugin&&) = delete;
    AvatarExoPlugin& operator=(AvatarExoPlugin&&) = delete;

private:
    //! Per-glove output adapters; only the enabled data sets are allocated. An output that fails
    //! to construct (e.g. HUMAN when push devices are unsupported) is left null without dropping
    //! the others.
    struct GloveOutputs
    {
        avatar::DeviceSide side = avatar::DeviceSide::RIGHT;
        std::string side_name; //!< "left" / "right"
        avatar::DevicePtr device;
        std::unique_ptr<core::SchemaPusher> raw_pusher;
        std::unique_ptr<core::SchemaPusher> robot_pusher;
        std::unique_ptr<plugin_utils::HandInjector> hand_injector;
        bool raw_started_logged = false;
        bool robot_started_logged = false;
        bool human_started_logged = false;
    };

    void worker_thread();

    //! Requested sides (from config) that are not yet connected.
    std::vector<avatar::DeviceSide> requested_sides() const;

    //! Try to attach any requested-but-missing glove; allocates its enabled outputs on success.
    void try_connect_pending();

    //! Construct a JointStateOutput SchemaPusher for "<prefix>_<dataset>_<side>".
    std::unique_ptr<core::SchemaPusher> make_joint_pusher(const std::string& dataset, const std::string& side);

    //! Serialize one Avatar `Hand` as a `JointStateOutput` and push it through @p pusher.
    void push_joint_state(core::SchemaPusher& pusher, const avatar::Hand& hand, const std::string& device_id);

    //! Map an Avatar `HandSkeleton` to 26 OpenXR joints and inject them through @p injector.
    void inject_human(plugin_utils::HandInjector& injector, const avatar::HandSkeleton& skeleton, XrTime time);

    AvatarExoConfig m_config;
    std::shared_ptr<core::OpenXRSession> m_session;
    std::optional<core::XrTimeConverter> m_time_converter;

    //! Connected gloves (worker-thread-only after construction).
    std::vector<GloveOutputs> m_gloves;
    bool m_sdk_initialized = false;

    std::thread m_thread;
    std::atomic<bool> m_running{ false };
};

} // namespace avatar_exo
} // namespace plugins
