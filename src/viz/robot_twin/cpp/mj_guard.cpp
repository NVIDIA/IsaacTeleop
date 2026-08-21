// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "mj_guard.hpp"

#include "mj_api.hpp"

#include <csetjmp>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <string>

namespace robot_twin
{
namespace
{

// Thread-local because a robot twin renders on its own thread while the app's thread is
// elsewhere in the same libmujoco.
thread_local std::jmp_buf g_recover;
thread_local bool g_armed = false;
thread_local std::string g_message;

void on_error(const char* message)
{
    g_message = message == nullptr ? "" : message;
    if (!g_armed)
    {
        // Outside a guarded call there is nowhere to land. A core dump beats continuing
        // on state MuJoCo has already declared invalid.
        std::fprintf(stderr, "robot_twin: unguarded MuJoCo error: %s\n", g_message.c_str());
        std::abort();
    }
    g_armed = false;
    std::longjmp(g_recover, 1);
}

void on_warning(const char* message)
{
    std::fprintf(stderr, "robot_twin: MuJoCo warning: %s\n", message == nullptr ? "" : message);
}

} // namespace

void install_mujoco_handlers()
{
    *mujoco::mju_user_error = on_error;
    *mujoco::mju_user_warning = on_warning;
}

void guarded(const char* what, const std::function<void()>& fn)
{
    if (setjmp(g_recover) != 0)
    {
        throw std::runtime_error(std::string("robot_twin: ") + what + ": " + g_message);
    }
    g_armed = true;
    fn();
    g_armed = false;
}

} // namespace robot_twin
