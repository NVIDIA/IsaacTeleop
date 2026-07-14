// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>
#include <oxr_utils/oxr_session_handles.hpp>

#include <memory>
#include <string>
#include <type_traits>
#include <vector>

namespace core
{

// OpenXR session management - creates and manages a headless OpenXR session
class OpenXRSession
{
public:
    OpenXRSession(const std::string& app_name, const std::vector<std::string>& extensions, bool wait_for_system = false);

    // Get session handles for use with trackers.
    // Non-owning views of session_/space_, valid only until close()/destruction; returns null handles thereafter.
    OpenXRSessionHandles get_handles() const;

    // Release the native OpenXR handles now, in reverse dependency order
    // (space -> session -> instance), so they are destroyed while the CloudXR
    // runtime/IPC socket is still alive rather than at garbage collection.
    // Idempotent: unique_ptr::reset() is a no-op on an already-null handle, so
    // close() and the destructor (or a double close()) are all safe.
    void close() noexcept;

    // Declaring the destructor suppresses the implicit move operations; inert
    // today because every construction site is make_shared<OpenXRSession>.
    ~OpenXRSession() noexcept
    {
        close();
    }

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
    XrSystemId system_id_;
    SessionHandle session_;
    SpaceHandle space_;
    bool wait_for_system_;
};

} // namespace core
