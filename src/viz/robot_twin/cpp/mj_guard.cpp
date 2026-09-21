// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "mj_guard.hpp"

#include "mj_api.hpp"

#include <log_bridge/logger.hpp>

#ifndef _WIN32
#    include <fcntl.h>
#    include <unistd.h>
#endif

#include <cerrno>
#include <csetjmp>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <string>
#include <string_view>

namespace viz
{
namespace
{

// Thread-local because a robot twin renders on its own thread while the app's thread is
// elsewhere in the same libmujoco.
thread_local std::jmp_buf g_recover;
thread_local bool g_armed = false;
thread_local std::string g_message;

// Vendor passthrough (MuJoCo's own error/warning text), so ThirdParty -- mirrors how
// Manus's SDK log stream is wrapped. Both callbacks below fire on a regular thread (not
// a signal handler, not between fork() and exec()), so logging from them is safe.
std::shared_ptr<spdlog::logger>& logger()
{
    static auto instance =
        isaacteleop::Logger::get("isaacteleop.viz.robot_twin.MuJoCo", isaacteleop::LoggerKind::ThirdParty);
    return instance;
}

void persist_fatal(std::string_view message) noexcept
{
#ifndef _WIN32
    const char* path = std::getenv("ISAACTELEOP_NATIVE_CAPTURE_FILE");
    const int fd = path != nullptr && path[0] != '\0' ? ::open(path, O_WRONLY | O_APPEND | O_NOFOLLOW) : -1;
    if (fd >= 0)
    {
        const auto write_all = [fd](std::string_view text)
        {
            while (!text.empty())
            {
                const ssize_t count = ::write(fd, text.data(), text.size());
                if (count < 0 && errno == EINTR)
                {
                    continue;
                }
                if (count <= 0)
                {
                    break;
                }
                text.remove_prefix(static_cast<std::size_t>(count));
            }
        };
        write_all("robot_twin: unguarded MuJoCo error: ");
        write_all(message);
        write_all("\n");
        ::fsync(fd);
        ::close(fd);
        return;
    }
#endif
    std::fprintf(stderr, "robot_twin: unguarded MuJoCo error: %.*s\n", static_cast<int>(message.size()), message.data());
    std::fflush(stderr);
}

void on_error(const char* message)
{
    g_message = message == nullptr ? "" : message;
    if (!g_armed)
    {
        // Outside a guarded call there is nowhere to land. A core dump beats continuing
        // on state MuJoCo has already declared invalid.
        logger()->error("unguarded MuJoCo error: {}", g_message);
        logger()->flush();
        // A forwarding flush cannot wait for the Python receiver thread;
        // abort() can stop that thread before it persists the record.
        persist_fatal(g_message);
        std::abort();
    }
    g_armed = false;
    std::longjmp(g_recover, 1);
}

void on_warning(const char* message)
{
    logger()->warn("{}", message == nullptr ? "" : message);
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

} // namespace viz
