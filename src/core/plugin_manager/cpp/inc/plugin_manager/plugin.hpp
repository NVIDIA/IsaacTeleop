#pragma once

#ifndef _WIN32
#    include <sys/types.h>
#endif

#include <string>
#include <vector>

namespace oxr
{

class Plugin
{
public:
    /**
     * @brief Construct a new Plugin object (starts the plugin process)
     * @param command The command to run the plugin (from metadata)
     * @param working_dir The directory to run the plugin in (where metadata was found)
     * @param plugin_root_id The root ID for the plugin
     */
    Plugin(const std::string& command, const std::string& working_dir, const std::string& plugin_root_id);

    /**
     * @brief Destructor - stops the plugin process
     */
    ~Plugin();

    /**
     * @brief Explicitly stop the plugin (same as destructor)
     */
    void stop();

private:
    void start_process(const std::string& command, const std::string& working_dir, const std::string& plugin_root_id);
    void stop_process();
    bool is_running() const;

#ifndef _WIN32
    pid_t m_pid = -1;
#else
    int m_pid = -1;
#endif
};

} // namespace oxr
