// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <log_bridge/logger.hpp>
#include <openxr/openxr.h>
#include <oxr_utils/debug_utils_messenger.hpp>
#include <oxr_utils/oxr_session_handles.hpp>

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <type_traits>
#include <vector>

namespace core
{

enum class OpenXRProviderState
{
    AVAILABLE,
    FAILED,
};

enum class OpenXRHeadsetState
{
    CONNECTED,
    DISCONNECTED,
};

enum class OpenXRProviderReason
{
    NONE,
    FORM_FACTOR_UNAVAILABLE,
    SESSION_LOST,
    INSTANCE_LOST,
    POLL_ERROR,
};

struct OpenXRProviderSnapshot
{
    OpenXRProviderState state = OpenXRProviderState::AVAILABLE;
    OpenXRHeadsetState headset_state = OpenXRHeadsetState::CONNECTED;
    OpenXRProviderReason reason = OpenXRProviderReason::NONE;
    std::optional<std::int32_t> result_code;
    std::string error;
};

// OpenXR session management - creates and manages a headless OpenXR session
class OpenXRSession
{
public:
    OpenXRSession(const std::string& app_name, const std::vector<std::string>& extensions, bool wait_for_system = true);

    // Get session handles for use with trackers
    OpenXRSessionHandles get_handles() const;

    // Poll the owned OpenXR event queue and return the cached provider state.
    OpenXRProviderSnapshot get_provider_snapshot();

private:
    // PFN_* deleter types work when OpenXR was already included with XR_NO_PROTOTYPES (no xrDestroy* declarations).
    using InstanceHandle = std::unique_ptr<std::remove_pointer_t<XrInstance>, PFN_xrDestroyInstance>;
    using SessionHandle = std::unique_ptr<std::remove_pointer_t<XrSession>, PFN_xrDestroySession>;
    using SpaceHandle = std::unique_ptr<std::remove_pointer_t<XrSpace>, PFN_xrDestroySpace>;

    // Initialization methods
    void create_instance(const std::string& app_name, const std::vector<std::string>& extensions);
    void create_system();
    void create_session();
    void create_reference_space();
    void begin();

    InstanceHandle instance_;
    // Must be destroyed before instance_ (declared after it: members destroy in reverse
    // declaration order), and only becomes active() once create_instance() constructs it.
    std::optional<oxr_utils::DebugUtilsMessenger> debug_messenger_;
    XrSystemId system_id_;
    SessionHandle session_;
    SpaceHandle space_;
    bool wait_for_system_;
    OpenXRProviderSnapshot provider_snapshot_;
    std::shared_ptr<spdlog::logger> logger_ = isaacteleop::Logger::get("isaacteleop.core.OpenXRSession");
};

} // namespace core
