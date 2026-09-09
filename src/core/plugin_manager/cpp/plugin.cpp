// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/plugin_manager/plugin.hpp"

#include <log_bridge/log_relay.hpp>

#ifndef _WIN32
#    include <sys/wait.h>

#    include <fcntl.h>
#    include <signal.h>
#    include <stdlib.h>
#    include <string.h>
#    include <unistd.h>
#endif

#include <chrono>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <thread>

namespace core
{
namespace
{

// Where this plugin's unframed output lands: the OpenXR runtime and vendor SDKs
// write straight to the descriptor and name no logger, so the executable is the
// most specific attribution available.
std::string relay_logger_name(const std::string& command)
{
    std::string executable = command.substr(0, command.find(' '));
    if (const auto slash = executable.find_last_of('/'); slash != std::string::npos)
    {
        executable.erase(0, slash + 1);
    }
    return "isaacteleop.plugins." + (executable.empty() ? std::string("unknown") : executable) + ".stdio";
}

} // namespace

Plugin::Plugin(const std::string& command,
               const std::string& working_dir,
               const std::string& plugin_root_id,
               const std::vector<std::string>& plugin_args)
{
    start_process(command, working_dir, plugin_root_id, plugin_args);
}

Plugin::~Plugin()
{
    stop_process();
}

void Plugin::stop()
{
    check_health();
    stop_process();
}

void Plugin::check_health() const
{
#ifndef _WIN32
    if (m_pid == -1)
    {
        return; // Already stopped
    }

    int status;
    pid_t result = waitpid(m_pid, &status, WNOHANG);

    if (result == m_pid)
    {
        // Process has exited
        if (WIFEXITED(status))
        {
            int exit_code = WEXITSTATUS(status);
            if (exit_code != 0)
            {
                throw PluginCrashException("Plugin process unexpectedly exited with code " + std::to_string(exit_code));
            }
        }
        else if (WIFSIGNALED(status))
        {
            int sig = WTERMSIG(status);
            throw PluginCrashException("Plugin process crashed with signal " + std::to_string(sig) + " (" +
                                       strsignal(sig) + ")");
        }
    }
    else if (result == -1)
    {
        if (errno != ECHILD)
        {
            throw PluginCrashException("Failed to check plugin health: " + std::string(strerror(errno)));
        }
        // ECHILD means process already reaped, ignore
    }
    // result == 0 means process still running
#endif
}

void Plugin::start_process(const std::string& command,
                           const std::string& working_dir,
                           const std::string& plugin_root_id,
                           const std::vector<std::string>& plugin_args)
{
#ifndef _WIN32
    // O_CLOEXEC so the ends this process keeps do not leak into later plugins:
    // a stray write end elsewhere would hold the pipe open and starve the reader
    // of the EOF it uses to finish.
    int log_pipe[2];
    if (pipe2(log_pipe, O_CLOEXEC) != 0)
    {
        throw std::runtime_error("Failed to create log relay pipe for plugin: " + std::string(strerror(errno)));
    }

    m_pid = fork();
    if (m_pid == -1)
    {
        close(log_pipe[0]);
        close(log_pipe[1]);
        throw std::runtime_error("Failed to fork process for plugin");
    }

    if (m_pid == 0)
    {
        // Child process, between fork() and execvp(): only async-signal-safe calls
        // are allowed here (POSIX). Never add Logger/spdlog calls in this window --
        // spdlog's registry and (in a Python process) GIL acquisition are both
        // unsafe post-fork-pre-exec.

        // Change working directory
        if (!working_dir.empty())
        {
            if (chdir(working_dir.c_str()) != 0)
            {
                std::cerr << "Failed to change directory to " << working_dir << std::endl;
                _exit(1);
            }
        }

        // Hand both streams to the relay pipe before anything can write to them,
        // and mark the process relayed so its log sink frames records onto fd 1
        // rather than applying a console policy of its own. dup2 clears O_CLOEXEC,
        // so these two survive the exec. setenv allocates and so is not strictly
        // permitted here, but neither are the stream and string operations this
        // window already performs.
        if (dup2(log_pipe[1], STDOUT_FILENO) == -1 || dup2(log_pipe[1], STDERR_FILENO) == -1 ||
            setenv(isaacteleop::kRelayEnvVar, "1", 1) != 0)
        {
            _exit(1);
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
        // The child's copy is the only write end left, so closing this one is what
        // makes the reader see EOF when the child exits.
        close(log_pipe[1]);
        m_log_relay = std::thread(isaacteleop::relay_logs, log_pipe[0], relay_logger_name(command));

        // Parent process - give the plugin a moment to start
        std::this_thread::sleep_for(std::chrono::milliseconds(100));

        // Check if process died during startup
        int status;
        pid_t result = waitpid(m_pid, &status, WNOHANG);
        if (result == m_pid)
        {
            m_pid = -1;
            m_log_relay.join();
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
    if (m_pid != -1)
    {
        kill(m_pid, SIGINT);

        int status;
        int attempts = 0;
        while (waitpid(m_pid, &status, WNOHANG) == 0)
        {
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
            attempts++;
            if (attempts > 40)
            {
                kill(m_pid, SIGKILL);
                waitpid(m_pid, &status, 0);
                break;
            }
        }

        m_pid = -1;
    }

    // Only now can the reader reach EOF: the reaped child's descriptors are gone.
    if (m_log_relay.joinable())
    {
        m_log_relay.join();
    }
#endif
}

} // namespace core
