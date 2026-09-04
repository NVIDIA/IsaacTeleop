// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "mj_api.hpp"

#include <dlfcn.h>
#include <stdexcept>
#include <string>

namespace robot_twin
{
namespace mujoco
{

#define ROBOT_TWIN_MJ_FN(name) decltype(::name)* name = nullptr;
#define ROBOT_TWIN_MJ_VAR(name) decltype(::name)* name = nullptr;
#include "mj_functions.inc"
#undef ROBOT_TWIN_MJ_FN
#undef ROBOT_TWIN_MJ_VAR

namespace
{

constexpr char kPrivateMujoco[] = "libisaacteleop_mujoco.so";

// Anything with an address in this .so serves; dladdr on it gives the file we were
// loaded from.
const char kAnchor = 0;

bool loaded_ = false;

// Ours, found by our own path rather than by name: a bare dlopen would search the
// process's library path and could land on something else called this. RTLD_LOCAL keeps
// its ~700 mj* out of the global scope, so it cannot interpose a user's libmujoco either.
void* open_private_mujoco()
{
    Dl_info info{};
    if (dladdr(&kAnchor, &info) == 0 || info.dli_fname == nullptr)
    {
        throw std::runtime_error("robot_twin: dladdr cannot name the file this extension was loaded from");
    }
    std::string path(info.dli_fname);
    const std::size_t slash = path.rfind('/');
    path.erase(slash == std::string::npos ? 0 : slash + 1);
    path += kPrivateMujoco;

    void* handle = dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL);
    if (handle == nullptr)
    {
        const char* why = dlerror();
        throw std::runtime_error("robot_twin: cannot open " + path + ": " + (why == nullptr ? "" : why));
    }
    return handle;
}

// Deduces the pointer type from the target, so no caller repeats a cast. Works for the
// hook variables too: dlsym returns the address of the variable, and `out` is a pointer
// to it.
template <typename T>
void resolve(void* handle, T& out, const char* name)
{
    void* symbol = dlsym(handle, name);
    if (symbol == nullptr)
    {
        throw std::runtime_error(std::string("robot_twin: ") + kPrivateMujoco + " has no " + name +
                                 ". It is not the MuJoCo this module was built against.");
    }
    out = reinterpret_cast<T>(symbol);
}

} // namespace

void load()
{
    if (loaded_)
    {
        return;
    }
    void* handle = open_private_mujoco();

#define ROBOT_TWIN_MJ_FN(name) resolve(handle, name, #name);
#define ROBOT_TWIN_MJ_VAR(name) resolve(handle, name, #name);
#include "mj_functions.inc"
#undef ROBOT_TWIN_MJ_FN
#undef ROBOT_TWIN_MJ_VAR

    // The one failure a private copy introduces: a stale libisaacteleop_mujoco.so left in
    // a package directory across a version bump. mjModel and mjData are laid out by the
    // headers this compiled against, so reading them through another version is silent
    // corruption, and mjVERSION_HEADER is what MuJoCo offers to catch it.
    if (mj_version() != mjVERSION_HEADER)
    {
        throw std::runtime_error(std::string("robot_twin: ") + kPrivateMujoco + " is " + mj_versionString() +
                                 ", not the version this module was built against. Rebuild, or delete the "
                                 "stale copy beside this extension.");
    }

    loaded_ = true;
}

} // namespace mujoco
} // namespace robot_twin
