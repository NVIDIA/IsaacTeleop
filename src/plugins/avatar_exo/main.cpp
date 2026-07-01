// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "avatar_exo_plugin.hpp"

#include <charconv>
#include <cctype>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <dlfcn.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <string_view>
#include <system_error>
#include <thread>
#include <unistd.h>
#include <utility>
#include <vector>

using namespace plugins::avatar_exo;

namespace
{

volatile std::sig_atomic_t g_stop_requested = 0;

void signal_handler(int signal)
{
    if (signal == SIGINT || signal == SIGTERM)
    {
        g_stop_requested = 1;
    }
}

//! Split "a,b,c" into lowercase tokens (whitespace/empties dropped).
std::vector<std::string> split_csv(const std::string& value)
{
    std::vector<std::string> tokens;
    std::stringstream ss(value);
    std::string item;
    while (std::getline(ss, item, ','))
    {
        std::string trimmed;
        for (char c : item)
        {
            if (!std::isspace(static_cast<unsigned char>(c)))
            {
                trimmed.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
            }
        }
        if (!trimmed.empty())
        {
            tokens.push_back(trimmed);
        }
    }
    return tokens;
}

std::filesystem::path plugin_dir_from_argv0(const char* argv0)
{
    std::filesystem::path exe(argv0 ? argv0 : "");
    if (exe.has_parent_path())
    {
        if (exe.is_relative())
        {
            exe = std::filesystem::absolute(exe);
        }
        return exe.parent_path();
    }
    return std::filesystem::current_path();
}

std::filesystem::path default_config_path(const char* argv0)
{
    // PluginManager launches this process with cwd set to the plugin directory, and the CMake
    // build/install rules copy sdk/ beside the executable. Use argv[0] first so direct runs from
    // another cwd still work when the executable path includes a directory.
    const auto by_exe = plugin_dir_from_argv0(argv0) / "sdk" / "sdk_config.json";
    if (std::filesystem::is_regular_file(by_exe))
    {
        return by_exe;
    }
    return std::filesystem::current_path() / "sdk" / "sdk_config.json";
}

std::string replace_all(std::string text, const std::string& needle, const std::string& replacement)
{
    if (needle.empty())
    {
        return text;
    }

    size_t pos = 0;
    while ((pos = text.find(needle, pos)) != std::string::npos)
    {
        text.replace(pos, needle.size(), replacement);
        pos += replacement.size();
    }
    return text;
}

std::string json_escape_path(const std::filesystem::path& path)
{
    std::string s = path.lexically_normal().string();
    // Linux paths normally do not contain JSON-special characters, but keep this safe enough.
    s = replace_all(std::move(s), "\\", "\\\\");
    s = replace_all(std::move(s), "\"", "\\\"");
    return s;
}

bool env_path_contains(const std::string& value, const std::string& path)
{
    const std::string_view target(path.data(), path.size());
    size_t start = 0;
    while (start <= value.size())
    {
        const size_t end = value.find(':', start);
        const std::string_view entry(value.data() + start, (end == std::string::npos ? value.size() : end) - start);
        if (entry == target)
        {
            return true;
        }
        if (end == std::string::npos)
        {
            break;
        }
        start = end + 1;
    }
    return false;
}

void prepend_env_path(const char* key, const std::filesystem::path& path)
{
    const std::string path_s = path.lexically_normal().string();
    const char* old = std::getenv(key);
    if (old == nullptr || std::string(old).empty())
    {
        setenv(key, path_s.c_str(), /*overwrite=*/1);
        return;
    }

    const std::string old_s(old);
    if (env_path_contains(old_s, path_s))
    {
        return;
    }
    setenv(key, (path_s + ":" + old_s).c_str(), /*overwrite=*/1);
}

void preload_shared_library(const std::filesystem::path& path)
{
    void* handle = dlopen(path.c_str(), RTLD_NOW | RTLD_GLOBAL);
    if (!handle)
    {
        std::cerr << "AvatarExo: warning: failed to preload '" << path << "': " << dlerror() << std::endl;
        return;
    }
}

void configure_sdk_runtime_paths(const std::filesystem::path& sdk_dir)
{
    const auto lib_dir = sdk_dir / "lib";
    const auto wave_lib_dir = sdk_dir / "wave-sdk" / "lib";

    // CasADi's plugin loader (used by ROBOT retarget / Ipopt) does not rely on the executable's
    // rpath; it searches CASADIPATH/LD_LIBRARY_PATH. Point it at the vendored SDK libs explicitly.
    prepend_env_path("CASADIPATH", lib_dir);
    prepend_env_path("LD_LIBRARY_PATH", lib_dir);
    prepend_env_path("LD_LIBRARY_PATH", wave_lib_dir);

    // Loading these exact SONAMEs globally makes the later CasADi plugin dependency resolution
    // deterministic even when the dynamic loader ignores LD_LIBRARY_PATH changes made after process
    // start. Do NOT preload libcasadi.so or libcasadi_nlpsol_ipopt.so here:
    // libavatar_sdk.so carries its own CasADi core, and forcing a second dynamic CasADi core into
    // the process can make the Ipopt plugin register against the wrong option registry (observed as
    // "Unknown option: error_on_fail"). Let the SDK's CasADi core load the nlpsol plugin itself.
    preload_shared_library(lib_dir / "libcoinmetis.so.2");
    preload_shared_library(lib_dir / "libcoinmumps.so.3");
    preload_shared_library(lib_dir / "libipopt.so.3");
}

void absolutize_json_path_value(std::string& json, const std::string& key, const std::filesystem::path& sdk_dir)
{
    const std::string quoted_key = "\"" + key + "\"";
    const size_t key_pos = json.find(quoted_key);
    if (key_pos == std::string::npos)
    {
        return;
    }
    const size_t colon = json.find(':', key_pos + quoted_key.size());
    if (colon == std::string::npos)
    {
        return;
    }
    const size_t first_quote = json.find('"', colon + 1);
    if (first_quote == std::string::npos)
    {
        return;
    }
    const size_t second_quote = json.find('"', first_quote + 1);
    if (second_quote == std::string::npos)
    {
        return;
    }

    const std::string value = json.substr(first_quote + 1, second_quote - first_quote - 1);
    if (value.empty() || std::filesystem::path(value).is_absolute())
    {
        return;
    }

    const std::string absolute = json_escape_path(sdk_dir / value);
    json.replace(first_quote + 1, value.size(), absolute);
}

std::string resolve_config_paths(std::string text, const std::filesystem::path& config_path)
{
    const auto sdk_dir = config_path.parent_path();
    text = replace_all(std::move(text), "@AVATAR_EXO_SDK_DIR@", json_escape_path(sdk_dir));

    // These fields are consumed by the Avatar SDK as filesystem paths. In the vendored plugin
    // config they are intentionally relative to sdk/ so the plugin is relocatable.
    absolutize_json_path_value(text, "wave_sdk_root", sdk_dir);
    absolutize_json_path_value(text, "fingertip_offset_config", sdk_dir);
    absolutize_json_path_value(text, "surjection_config", sdk_dir);
    return text;
}

//! Read the Avatar config, resolving plugin-relative resource paths; returns "{}" on failure.
std::string read_config(const std::filesystem::path& path)
{
    std::ifstream f(path);
    if (!f.is_open())
    {
        std::cerr << "AvatarExo: cannot open config '" << path
                  << "', using defaults (retarget OFF -> no ROBOT data)" << std::endl;
        return "{}";
    }
    std::ostringstream ss;
    ss << f.rdbuf();
    return resolve_config_paths(ss.str(), path);
}

int parse_rate_hz(const std::string& text, int fallback)
{
    int parsed = 0;
    const auto* begin = text.data();
    const auto* end = text.data() + text.size();
    const auto result = std::from_chars(begin, end, parsed);
    if (result.ec != std::errc{} || result.ptr != end || parsed <= 0)
    {
        std::cerr << "AvatarExo: invalid --rate-hz='" << text << "', using " << fallback << std::endl;
        return fallback;
    }
    return parsed;
}

bool starts_with(const std::string& s, const std::string& prefix)
{
    return s.rfind(prefix, 0) == 0;
}

bool should_forward_avatar_log_line(const std::string& line)
{
    return line == "AvatarExoPlugin running; waiting for Avatar SDK + glove(s)..." ||
           starts_with(line, "AvatarExoPlugin: connected ") ||
           (starts_with(line, "AvatarExoPlugin: ") && line.find(" stream started") != std::string::npos) ||
           line.find("SerialHand::fetch_firmware_identity:") != std::string::npos;
}

void write_all(int fd, const std::string& text)
{
    const char* data = text.data();
    size_t remaining = text.size();
    while (remaining > 0)
    {
        const ssize_t written = write(fd, data, remaining);
        if (written <= 0)
        {
            return;
        }
        data += written;
        remaining -= static_cast<size_t>(written);
    }
}

//! Avatar SDK/OpenXR dependencies are chatty on stdout/stderr. Filter only this child process's
//! output; parent server/Pico logs are in a different process and remain untouched.
class AvatarOutputFilter
{
public:
    AvatarOutputFilter()
    {
        m_stdout_fd = dup(STDOUT_FILENO);
        m_stderr_fd = dup(STDERR_FILENO);
        if (m_stdout_fd < 0 || m_stderr_fd < 0)
        {
            return;
        }

        int pipe_fds[2];
        if (pipe(pipe_fds) != 0)
        {
            return;
        }

        std::cout.flush();
        std::cerr.flush();
        std::fflush(stdout);
        std::fflush(stderr);

        m_read_fd = pipe_fds[0];
        const int write_fd = pipe_fds[1];
        if (dup2(write_fd, STDOUT_FILENO) < 0 || dup2(write_fd, STDERR_FILENO) < 0)
        {
            if (m_stdout_fd >= 0)
            {
                dup2(m_stdout_fd, STDOUT_FILENO);
            }
            if (m_stderr_fd >= 0)
            {
                dup2(m_stderr_fd, STDERR_FILENO);
            }
            close(m_read_fd);
            close(write_fd);
            m_read_fd = -1;
            return;
        }
        close(write_fd);

        m_active = true;
        m_thread = std::thread(&AvatarOutputFilter::run, this);
    }

    ~AvatarOutputFilter()
    {
        if (m_active)
        {
            std::cout.flush();
            std::cerr.flush();
            std::fflush(stdout);
            std::fflush(stderr);

            dup2(m_stdout_fd, STDOUT_FILENO);
            dup2(m_stderr_fd, STDERR_FILENO);

            if (m_thread.joinable())
            {
                m_thread.join();
            }
        }

        if (m_read_fd >= 0)
            close(m_read_fd);
        if (m_stdout_fd >= 0)
            close(m_stdout_fd);
        if (m_stderr_fd >= 0)
            close(m_stderr_fd);
    }

    AvatarOutputFilter(const AvatarOutputFilter&) = delete;
    AvatarOutputFilter& operator=(const AvatarOutputFilter&) = delete;

private:
    void run()
    {
        std::string pending;
        char buffer[1024];
        while (true)
        {
            const ssize_t n = read(m_read_fd, buffer, sizeof(buffer));
            if (n <= 0)
            {
                break;
            }
            pending.append(buffer, static_cast<size_t>(n));

            size_t newline_pos = std::string::npos;
            while ((newline_pos = pending.find('\n')) != std::string::npos)
            {
                std::string line = pending.substr(0, newline_pos);
                if (!line.empty() && line.back() == '\r')
                {
                    line.pop_back();
                }
                if (should_forward_avatar_log_line(line))
                {
                    write_all(m_stdout_fd, line + "\n");
                }
                pending.erase(0, newline_pos + 1);
            }
        }

        if (!pending.empty() && should_forward_avatar_log_line(pending))
        {
            write_all(m_stdout_fd, pending + "\n");
        }
    }

    int m_stdout_fd = -1;
    int m_stderr_fd = -1;
    int m_read_fd = -1;
    bool m_active = false;
    std::thread m_thread;
};

} // namespace

int main(int argc, char** argv)
try
{
    AvatarExoConfig config;
    config.raw = false;
    config.robot = false;
    config.human = false;
    config.left = false;
    config.right = false;
    std::string config_path_arg;
    std::string sides_arg = "both";
    std::string datasets_arg;

    for (int i = 1; i < argc; ++i)
    {
        const std::string arg = argv[i];
        if (starts_with(arg, "--datasets="))
        {
            datasets_arg = arg.substr(std::string("--datasets=").size());
        }
        else if (starts_with(arg, "--sides="))
        {
            sides_arg = arg.substr(std::string("--sides=").size());
        }
        else if (starts_with(arg, "--collection-prefix="))
        {
            config.collection_prefix = arg.substr(std::string("--collection-prefix=").size());
        }
        else if (starts_with(arg, "--config="))
        {
            config_path_arg = arg.substr(std::string("--config=").size());
        }
        else if (starts_with(arg, "--rate-hz="))
        {
            config.rate_hz = parse_rate_hz(arg.substr(std::string("--rate-hz=").size()), config.rate_hz);
        }
        else if (starts_with(arg, "--plugin-root-id="))
        {
            // Injected by the PluginManager; not used by this plugin.
        }
        else
        {
            std::cerr << "AvatarExo: ignoring unknown argument '" << arg << "'" << std::endl;
        }
    }

    for (const auto& ds : split_csv(datasets_arg))
    {
        if (ds == "raw")
            config.raw = true;
        else if (ds == "robot")
            config.robot = true;
        else if (ds == "human")
            config.human = true;
        else
            std::cerr << "AvatarExo: ignoring unknown data set '" << ds << "'" << std::endl;
    }

    if (sides_arg == "both")
    {
        config.left = true;
        config.right = true;
    }
    else
    {
        for (const auto& s : split_csv(sides_arg))
        {
            if (s == "left")
                config.left = true;
            else if (s == "right")
                config.right = true;
            else
                std::cerr << "AvatarExo: ignoring unknown side '" << s << "'" << std::endl;
        }
    }

    const std::filesystem::path config_path =
        config_path_arg.empty() ? default_config_path(argv[0]) : std::filesystem::absolute(config_path_arg);

    AvatarOutputFilter output_filter;

    // Let the Avatar SDK and any SDK-side helpers know where the config and relative assets live.
    if (!config_path.empty())
    {
        const std::string config_path_s = config_path.string();
        const std::string config_dir_s = config_path.parent_path().string();
        setenv("AVATAR_SDK_CONFIG_PATH", config_path_s.c_str(), /*overwrite=*/1);
        setenv("AVATAR_SDK_CONFIG_DIR", config_dir_s.c_str(), /*overwrite=*/1);
        setenv("AVATAR_SDK_HAND_FK_DATA_DIR", (config_path.parent_path() / "hand_fk").string().c_str(), /*overwrite=*/1);
        configure_sdk_runtime_paths(config_path.parent_path());
    }
    config.sdk_config_json = read_config(config_path);
    // --config only controls Avatar SDK initialization/resources. RAW/ROBOT JointState names stay
    // on the stable positional wire contract j0..jN-1, which the server declares too.

    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    AvatarExoPlugin plugin(config);

    while (!g_stop_requested)
    {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    // RAII: plugin stops its worker and releases the gloves / SDK in its destructor.
    return 0;
}
catch (const std::exception& e)
{
    std::cerr << argv[0] << ": " << e.what() << std::endl;
    return 1;
}
catch (...)
{
    std::cerr << argv[0] << ": Unknown error occurred" << std::endl;
    return 1;
}
