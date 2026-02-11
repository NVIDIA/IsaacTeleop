#include "inc/plugin_manager/plugin.hpp"

#ifndef _WIN32
#    include <sys/wait.h>

#    include <map>
#    include <mutex>
#    include <signal.h>
#    include <string.h>
#    include <unistd.h>
#endif

#include <algorithm>
#include <chrono>
#include <filesystem>
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
    m_pid = fork();
    if (m_pid == -1)
    {
        throw std::runtime_error("Failed to fork process for plugin");
    }

    if (m_pid == 0)
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

        // Append plugin arguments; skip if option already in args_str (e.g. --plugin-root-id= from above)
        for (const auto& arg : plugin_args)
        {
            // Option prefix: "--name=" or whole arg for "--flag"
            const std::string arg_prefix = (arg.find('=') != std::string::npos) ? arg.substr(0, arg.find('=') + 1) : arg;
            const bool already = std::any_of(args_str.cbegin(), args_str.cend(),
                                             [&arg_prefix](const std::string& s) { return s.starts_with(arg_prefix); });
            if (!already)
            {
                args_str.push_back(arg);
            }
            else
            {
                std::cerr << "Warning: Option " << arg_prefix << " already specified, ignoring duplicate" << std::endl;
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
        // Parent process - give the plugin a moment to start
        std::this_thread::sleep_for(std::chrono::milliseconds(100));

        // Check if process died during startup
        int status;
        pid_t result = waitpid(m_pid, &status, WNOHANG);
        if (result == m_pid)
        {
            m_pid = -1;
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
#endif
}

} // namespace core
