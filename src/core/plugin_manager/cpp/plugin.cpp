#include "inc/plugin_manager/plugin.hpp"

#ifndef _WIN32
#    include <sys/wait.h>

#    include <signal.h>
#    include <unistd.h>
#endif

#include <chrono>
#include <filesystem>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <thread>

namespace oxr
{

Plugin::Plugin(const std::string& command, const std::string& working_dir, const std::string& plugin_root_id)
{
    start_process(command, working_dir, plugin_root_id);
}

Plugin::~Plugin()
{
    stop_process();
}

void Plugin::stop()
{
    stop_process();
}

void Plugin::start_process(const std::string& command, const std::string& working_dir, const std::string& plugin_root_id)
{
#ifndef _WIN32
    if (is_running())
    {
        return;
    }

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

        // Wait for exit
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

bool Plugin::is_running() const
{
#ifndef _WIN32
    if (m_pid == -1)
        return false;
    int status;
    return waitpid(m_pid, &status, WNOHANG) == 0;
#else
    return false;
#endif
}

} // namespace oxr
