// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/plugin_manager/plugin.hpp"

#ifndef _WIN32
#    include <sys/wait.h>

#    include <signal.h>
#    include <string.h>
#    include <unistd.h>
#endif

#include <cerrno>
#include <chrono>
#include <cstring>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <thread>

namespace core
{

Plugin::Plugin(const std::string& command,
               const std::string& working_dir,
               const std::string& plugin_root_id,
               const std::vector<std::string>& plugin_args)
{
    start_process(command, working_dir, plugin_root_id, plugin_args);
}

Plugin::~Plugin()
{
    try
    {
        stop_process();
    }
    catch (...)
    {
    }
}

void Plugin::stop()
{
    check_health();
    stop_process();
}

void Plugin::check_health() const
{
    const ProcessSnapshot snapshot = get_process_snapshot();
    switch (snapshot.state)
    {
    case ProcessState::EXITED:
        if (snapshot.exit_code.value_or(0) != 0)
        {
            throw PluginCrashException(snapshot.error);
        }
        break;
    case ProcessState::SIGNALED:
    case ProcessState::ERROR:
        throw PluginCrashException(snapshot.error);
    case ProcessState::RUNNING:
    case ProcessState::STOPPED:
        break;
    }
}

ProcessSnapshot Plugin::get_process_snapshot() const
{
    std::lock_guard<std::mutex> lock(m_process_mutex);
#ifndef _WIN32
    if (m_pid != -1)
    {
        refresh_process_snapshot_locked(false);
    }
#endif
    return m_process_snapshot;
}

void Plugin::start_process(const std::string& command,
                           const std::string& working_dir,
                           const std::string& plugin_root_id,
                           const std::vector<std::string>& plugin_args)
{
#ifndef _WIN32
    const pid_t child_pid = fork();
    if (child_pid == -1)
    {
        throw std::runtime_error("Failed to fork process for plugin");
    }

    if (child_pid == 0)
    {
        // Child process

        // Change working directory
        if (!working_dir.empty())
        {
            if (chdir(working_dir.c_str()) != 0)
            {
                std::cerr << "Failed to change directory to " << working_dir << std::endl;
                _exit(1);
            }
        }

        // Close file descriptors to avoid sharing with parent process
        for (int i = 3; i < 1024; ++i)
        {
            close(i);
        }

        // Split command into args (naive splitting by space)
        std::vector<std::string> args_str;
        std::stringstream ss(command);
        std::string item;
        while (std::getline(ss, item, ' '))
        {
            if (!item.empty())
                args_str.push_back(item);
        }

        if (args_str.empty())
        {
            std::cerr << "Empty command" << std::endl;
            _exit(1);
        }

        // Append plugin root ID argument if set
        if (!plugin_root_id.empty())
        {
            args_str.push_back("--plugin-root-id=" + plugin_root_id);
        }

        // Append plugin arguments, skipping --plugin-root-id if already injected above
        for (const auto& arg : plugin_args)
        {
            if (!arg.starts_with("--plugin-root-id="))
            {
                args_str.push_back(arg);
            }
            else
            {
                std::cerr << "Warning: --plugin-root-id is managed by the plugin launcher, ignoring manual override"
                          << std::endl;
            }
        }

        std::vector<char*> args;
        for (auto& s : args_str)
        {
            args.push_back(&s[0]);
        }
        args.push_back(nullptr);

        execvp(args[0], args.data());

        // If execvp returns, it failed
        std::cerr << "Failed to exec plugin command: " << command << std::endl;
        _exit(1);
    }
    else
    {
        {
            std::lock_guard<std::mutex> lock(m_process_mutex);
            m_pid = child_pid;
            m_stop_requested = false;
            m_process_snapshot = ProcessSnapshot{};
            m_process_snapshot.pid = child_pid;
        }

        // Parent process - give the plugin a moment to start
        std::this_thread::sleep_for(std::chrono::milliseconds(100));

        // Check if process died during startup
        ProcessState startup_state;
        std::string startup_error;
        {
            std::lock_guard<std::mutex> lock(m_process_mutex);
            refresh_process_snapshot_locked(false);
            startup_state = m_process_snapshot.state;
            startup_error = m_process_snapshot.error;
        }
        if (startup_state == ProcessState::ERROR)
        {
            throw std::runtime_error("Failed to observe plugin process during startup: " + startup_error);
        }
        if (startup_state == ProcessState::EXITED || startup_state == ProcessState::SIGNALED)
        {
            throw std::runtime_error("Plugin process exited immediately");
        }
    }
#else
    throw std::runtime_error("Plugin process management not supported on Windows");
#endif
}

void Plugin::stop_process()
{
#ifndef _WIN32
    std::unique_lock<std::mutex> lock(m_process_mutex);
    if (m_pid == -1)
    {
        return;
    }

    refresh_process_snapshot_locked(false);
    if (m_pid == -1)
    {
        return;
    }

    m_stop_requested = true;
    if (kill(m_pid, SIGINT) == -1)
    {
        cache_signal_error_locked(errno, "send SIGINT to plugin process");
        throw PluginCrashException(m_process_snapshot.error);
    }

    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    while (m_pid != -1 && std::chrono::steady_clock::now() < deadline)
    {
        refresh_process_snapshot_locked(false);
        if (m_pid != -1)
        {
            lock.unlock();
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
            lock.lock();
        }
    }

    refresh_process_snapshot_locked(false);
    if (m_pid == -1)
    {
        return;
    }

    if (kill(m_pid, SIGKILL) == -1)
    {
        cache_signal_error_locked(errno, "send SIGKILL to plugin process");
        throw PluginCrashException(m_process_snapshot.error);
    }
    refresh_process_snapshot_locked(true);
#endif
}

void Plugin::refresh_process_snapshot_locked(bool block) const
{
#ifndef _WIN32
    if (m_pid == -1)
    {
        return;
    }

    int status = 0;
    pid_t result;
    do
    {
        result = waitpid(m_pid, &status, block ? 0 : WNOHANG);
    } while (result == -1 && errno == EINTR);

    if (result == 0)
    {
        return;
    }

    if (result == -1)
    {
        const int wait_error = errno;
        m_pid = -1;
        m_process_snapshot.state = ProcessState::ERROR;
        m_process_snapshot.reason = ProcessReason::WAIT_ERROR;
        m_process_snapshot.error_code = wait_error;
        m_process_snapshot.error = "Failed to check plugin health: " + std::string(std::strerror(wait_error));
        return;
    }

    // waitpid returned the child, so the PID must no longer be used for signaling.
    m_pid = -1;
    m_process_snapshot.exit_code.reset();
    m_process_snapshot.term_signal.reset();
    m_process_snapshot.error_code.reset();
    m_process_snapshot.error.clear();

    if (WIFEXITED(status))
    {
        m_process_snapshot.exit_code = WEXITSTATUS(status);
    }
    else if (WIFSIGNALED(status))
    {
        m_process_snapshot.term_signal = WTERMSIG(status);
    }

    if (m_stop_requested)
    {
        m_process_snapshot.state = ProcessState::STOPPED;
        m_process_snapshot.reason = ProcessReason::EXPLICIT_STOP;
        m_process_snapshot.exit_code.reset();
        m_process_snapshot.term_signal.reset();
        return;
    }

    if (m_process_snapshot.exit_code.has_value())
    {
        m_process_snapshot.state = ProcessState::EXITED;
        if (*m_process_snapshot.exit_code == 0)
        {
            m_process_snapshot.reason = ProcessReason::CLEAN_EXIT;
        }
        else
        {
            m_process_snapshot.reason = ProcessReason::NONZERO_EXIT;
            m_process_snapshot.error =
                "Plugin process unexpectedly exited with code " + std::to_string(*m_process_snapshot.exit_code);
        }
        return;
    }

    if (m_process_snapshot.term_signal.has_value())
    {
        const int term_signal = *m_process_snapshot.term_signal;
        const char* signal_name = strsignal(term_signal);
        m_process_snapshot.state = ProcessState::SIGNALED;
        m_process_snapshot.reason = ProcessReason::SIGNAL;
        m_process_snapshot.error = "Plugin process crashed with signal " + std::to_string(term_signal);
        if (signal_name != nullptr)
        {
            m_process_snapshot.error += " (" + std::string(signal_name) + ")";
        }
        return;
    }

    m_process_snapshot.state = ProcessState::ERROR;
    m_process_snapshot.reason = ProcessReason::WAIT_ERROR;
    m_process_snapshot.error = "Plugin process ended with an unrecognized wait status";
#else
    (void)block;
#endif
}

void Plugin::cache_signal_error_locked(int error_code, const std::string& operation) const
{
    m_process_snapshot.state = ProcessState::ERROR;
    m_process_snapshot.reason = ProcessReason::SIGNAL_ERROR;
    m_process_snapshot.error_code = error_code;
    m_process_snapshot.error = "Failed to " + operation + ": " + std::string(std::strerror(error_code));
}

} // namespace core
