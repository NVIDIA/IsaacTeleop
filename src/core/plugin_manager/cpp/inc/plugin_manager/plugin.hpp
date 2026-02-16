// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#ifndef _WIN32
#    include <sys/types.h>
#endif

#include <stdexcept>
#include <string>
#include <vector>

namespace core
{

/**
 * @brief Custom exception thrown when a plugin crashes or exits unexpectedly
 */
class PluginCrashException : public std::runtime_error
{
public:
    explicit PluginCrashException(const std::string& message) : std::runtime_error(message)
    {
    }
};

class Plugin
{
public:
    /**
     * @brief Construct a new Plugin object (starts the plugin process)
     * @param command The command to run the plugin (from metadata)
     * @param working_dir The directory to run the plugin in (where metadata was found)
     * @param plugin_root_id The root ID for the plugin
     * @param plugin_args Optional list of arguments to append to the command
     */
    Plugin(const std::string& command,
           const std::string& working_dir,
           const std::string& plugin_root_id,
           const std::vector<std::string>& plugin_args = {});

    /**
     * @brief Destructor - stops the plugin process
     */
    ~Plugin();

    /**
     * @brief Explicitly stop the plugin (same as destructor)
     * @throws PluginCrashException if the plugin has crashed
     */
    void stop();

    /**
     * @brief Check if plugin crashed (lightweight, non-blocking)
     * @throws PluginCrashException if the plugin has crashed
     */
    void check_health() const;

private:
    void start_process(const std::string& command,
                       const std::string& working_dir,
                       const std::string& plugin_root_id,
                       const std::vector<std::string>& plugin_args);

    void stop_process();

#ifndef _WIN32
    pid_t m_pid = -1;
#else
    int m_pid = -1;
#endif
};

} // namespace core
