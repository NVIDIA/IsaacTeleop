// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <pusherio/schema_pusher.hpp>
#include <schema/full_body_generated.h>

#include <MocapApi.h>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace core
{
class OpenXRSession;
}

namespace plugins
{
namespace noitom_mocap
{

static constexpr size_t DEFAULT_NOITOM_MOCAP_MAX_FLATBUFFER_SIZE = 16 * 1024;

enum class MocapProtocol
{
    Tcp,
    Udp,
};

struct NoitomMocapPluginConfig
{
    MocapProtocol protocol = MocapProtocol::Tcp;
    std::string host = "127.0.0.1";
    uint16_t port = 8001;
    uint16_t udp_local_port = 8002;
    std::string udp_server_host;
    uint16_t udp_server_port = 8001;
    std::string collection_id = "noitom_mocap";
    size_t max_flatbuffer_size = DEFAULT_NOITOM_MOCAP_MAX_FLATBUFFER_SIZE;
};

class NoitomMocapPlugin
{
public:
    explicit NoitomMocapPlugin(NoitomMocapPluginConfig config);
    ~NoitomMocapPlugin();

    // Returns false when the Noitom SDK connection is lost (caller should exit).
    bool update();

private:
    template <typename InterfaceT>
    InterfaceT* get_interface(const char* version);

    void initialize_mocap();
    void close_mocap();
    std::vector<MocapApi::MCPEvent_t> poll_events();
    std::vector<MocapApi::MCPAvatarHandle_t> poll_avatars();
    bool handle_avatar(MocapApi::MCPAvatarHandle_t avatar_handle);
    void ensure_pusher(size_t flatbuffer_size);
    void push_frame(int64_t sample_time_local_common_clock_ns, int64_t sample_time_raw_device_clock_ns);

    NoitomMocapPluginConfig config_;
    std::shared_ptr<core::OpenXRSession> session_;
    std::unique_ptr<core::SchemaPusher> pusher_;

    MocapApi::IMCPSettings* settings_api_ = nullptr;
    MocapApi::IMCPApplication* application_api_ = nullptr;
    MocapApi::IMCPAvatar* avatar_api_ = nullptr;
    MocapApi::IMCPJoint* joint_api_ = nullptr;
    MocapApi::IMCPRenderSettings* render_settings_api_ = nullptr;

    MocapApi::MCPSettingsHandle_t settings_handle_ = 0;
    MocapApi::MCPRenderSettingsHandle_t render_settings_handle_ = 0;
    MocapApi::MCPApplicationHandle_t application_handle_ = 0;
    bool application_open_ = false;
    bool warned_no_avatars_ = false;

    core::FullBodyPosePicoT frame_;
    int64_t latest_sample_time_raw_device_clock_ns_ = 0;
};

} // namespace noitom_mocap
} // namespace plugins
