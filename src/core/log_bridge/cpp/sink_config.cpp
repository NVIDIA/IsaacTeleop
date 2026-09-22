// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "sink_config.hpp"

#include "socket_sink.hpp"

#include <spdlog/common.h>
#include <spdlog/pattern_formatter.h>
#include <spdlog/sinks/rotating_file_sink.h>
#include <spdlog/sinks/stdout_color_sinks.h>

#include <algorithm>
#include <cctype>
#include <charconv>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <filesystem>
#include <memory>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>

#ifndef _WIN32
#    include <sys/stat.h>

#    include <fcntl.h>
#    include <unistd.h>
#    include <vector>
#else
#    include <process.h>
#endif

namespace isaacteleop::detail
{
namespace
{

constexpr std::size_t kFileMaxBytes = 10 * 1024 * 1024; // 10 MiB
constexpr std::size_t kFileBackupCount = 5;
// Same shape as the Python side's LINE_FORMAT (logging_config/_core.py). %* is
// PythonLevelFormatter below; spdlog's own %l is lowercase and %L a single
// letter, so neither renders the level the way Python's handlers do.
constexpr const char* kPattern = "[%Y-%m-%d %H:%M:%S.%e] [%*] [%n] [pid:%P] %v";

// The stdlib names Python's LINE_FORMAT renders, plus TRACE
// (logging.addLevelName(TRACE, "TRACE") in logging_config/_core.py). Needed so
// a record this process formats itself reads like one that reached a file
// through Python -- the case a standalone plugin executable has to carry alone.
std::string_view python_level_name(spdlog::level::level_enum level)
{
    switch (level)
    {
    case spdlog::level::trace:
        return "TRACE";
    case spdlog::level::debug:
        return "DEBUG";
    case spdlog::level::info:
        return "INFO";
    case spdlog::level::warn:
        return "WARNING";
    case spdlog::level::err:
        return "ERROR";
    case spdlog::level::critical:
        return "CRITICAL";
    default:
        return "INFO";
    }
}

// Right-padded to 5 and never truncated, matching Python's own "%(levelname)-5s".
class PythonLevelFormatter : public spdlog::custom_flag_formatter
{
public:
    void format(const spdlog::details::log_msg& msg, const std::tm&, spdlog::memory_buf_t& dest) override
    {
        const std::string_view name = python_level_name(msg.level);
        dest.append(name.data(), name.data() + name.size());
        for (std::size_t pad = name.size(); pad < 5; ++pad)
        {
            dest.push_back(' ');
        }
    }

    std::unique_ptr<custom_flag_formatter> clone() const override
    {
        return std::make_unique<PythonLevelFormatter>();
    }
};

// A fresh formatter per sink: sink::set_formatter() takes a unique_ptr, so
// console and file each need their own instance built from the same recipe.
std::unique_ptr<spdlog::pattern_formatter> make_formatter()
{
    auto formatter = std::make_unique<spdlog::pattern_formatter>();
    formatter->add_flag<PythonLevelFormatter>('*').set_pattern(kPattern);
    return formatter;
}

#ifndef _WIN32
// Path.expanduser(), for the "~" and "~/..." forms only. A session with a
// Python leader never needs this -- logging_config's log_dir() republishes
// ISAACTELEOP_LOG_DIR already expanded -- but a standalone plugin run by hand
// with the value quoted would otherwise create a directory literally named "~".
// "~user" is not expanded; the default is used instead.
std::filesystem::path expand_user(const std::string& raw)
{
    if (raw.empty() || raw[0] != '~')
    {
        return raw;
    }
    if (raw.size() > 1 && raw[1] != '/')
    {
        return {};
    }
    const char* home = std::getenv("HOME");
    if (home == nullptr || home[0] == '\0')
    {
        return {};
    }
    return raw.size() == 1 ? std::filesystem::path(home) : std::filesystem::path(home) / raw.substr(2);
}

// Rotation reopens by name with "wb", so every generation past the first is
// created at 0666 & ~umask however the first one was made. Runs from
// spdlog's after_open hook and must not log: sink_it_ holds this sink's mutex
// across it.
void harden_log_file(const spdlog::filename_t&, std::FILE* file)
{
    const int fd = ::fileno(file);
    if (fd < 0)
    {
        return;
    }
    ::fchmod(fd, 0600);
    const int flags = ::fcntl(fd, F_GETFD);
    if (flags >= 0)
    {
        ::fcntl(fd, F_SETFD, flags | FD_CLOEXEC);
    }
}
#endif

int current_pid()
{
#ifndef _WIN32
    return static_cast<int>(::getpid());
#else
    return static_cast<int>(::_getpid());
#endif
}

// A rotating file no other writer in this session already owns.
//
// Two rotating writers on one path corrupt it: each keeps its own size counter
// and whichever renames first leaves the other's handle on the renamed inode.
// Two can want one file in the same process, because log_bridge_core is a
// static library -- _oxr, _viz and every other extension module carries its own
// local_sinks(), loaded RTLD_LOCAL so nothing unifies them -- and because the
// forwarding socket that normally keeps C++ out of the file business does not
// exist on Windows and may fail to bind anywhere.
//
// Hence ".cpp": the plain <timestamp>.isaacteleop.<pid>.log belongs to the
// Python half (logging_config/_file.py). The trailing -1, -2 then separate one
// module's copy from the next. A dash, not a dot: rotating_file_sink inserts
// its backup index before the extension, so "x.cpp.1.log" is already taken.
std::filesystem::path unique_log_path(const std::filesystem::path& dir, const std::string& stem)
{
    constexpr int kMaxAttempts = 16;
    for (int attempt = 0; attempt < kMaxAttempts; ++attempt)
    {
        const std::string suffix = attempt == 0 ? std::string() : "-" + std::to_string(attempt);
        auto candidate = dir / (stem + suffix + ".log");
        // Reserved by an exclusive create, not merely checked: exists() leaves a
        // gap before the real open that two modules' independent creation_mutex()es
        // do not close. O_NOFOLLOW also refuses a symlink planted at the name, and
        // 0600 is set by the creating call rather than after the sink opens it.
#ifndef _WIN32
        const int reserved = ::open(candidate.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
        if (reserved >= 0)
        {
            ::close(reserved);
            return candidate;
        }
#else
        // No mode to set on this platform: the file inherits the directory's ACL.
        if (std::FILE* reserved = std::fopen(candidate.string().c_str(), "wx"))
        {
            std::fclose(reserved);
            return candidate;
        }
#endif
    }
    return {}; // Console only; see local_sinks().
}

// Local time, filename-safe (no ':' or ' '): YYYYMMDD-HHMMSS.
std::string current_timestamp()
{
    const std::time_t now = std::time(nullptr);
    std::tm tm_buf{};
#ifndef _WIN32
    ::localtime_r(&now, &tm_buf);
#else
    ::localtime_s(&tm_buf, &now);
#endif
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y%m%d-%H%M%S", &tm_buf);
    return std::string(buf);
}

// Must resolve to the same place as isaacteleop.logging_config's log_dir(),
// including the uid: a single shared /tmp/isaacteleop is created by whichever
// user reaches it first and is then unwritable for everyone else on the machine.
std::filesystem::path log_dir()
{
    // Empty means unset, exactly as `os.environ.get(...) or default` makes it
    // on the Python side.
    if (const char* override_dir = std::getenv("ISAACTELEOP_LOG_DIR"); override_dir != nullptr && override_dir[0] != '\0')
    {
#ifndef _WIN32
        if (auto expanded = expand_user(override_dir); !expanded.empty())
        {
            return expanded;
        }
#else
        return std::filesystem::path(override_dir);
#endif
    }
#ifndef _WIN32
    return "/tmp/isaacteleop-" + std::to_string(static_cast<unsigned>(::getuid())) + "/logs";
#else
    // tempfile.gettempdir() is what the Python side resolves here, and it is
    // already per-user; a literal "/tmp" would resolve against the current
    // drive's root instead and split one session across two directories.
    std::error_code temp_ec;
    const auto temp_dir = std::filesystem::temp_directory_path(temp_ec);
    return (temp_ec ? std::filesystem::path(".") : temp_dir) / "isaacteleop" / "logs";
#endif
}

// Mirrors isaacteleop.logging_config's names and integer thresholds.
// spdlog::level::from_str() is deliberately not used: it answers level::off for
// anything it does not recognise, so a typo would mute a standalone plugin
// entirely instead of falling back to info. spdlog's own "warn"/"err"
// spellings are absent for the same reason the Python half has no entry for
// them -- one operator value must not mean two different thresholds.
spdlog::level::level_enum console_level()
{
    const char* raw = std::getenv("ISAACTELEOP_LOG_LEVEL");
    if (raw == nullptr)
    {
        return spdlog::level::info;
    }

    // Trimmed before anything looks at it, as the Python half's
    // env_console_level() does: a systemd `Environment=` line, a sourced .env
    // file and a here-doc all hand this leading or trailing whitespace.
    std::string_view text(raw);
    while (!text.empty() && std::isspace(static_cast<unsigned char>(text.front())))
    {
        text.remove_prefix(1);
    }
    while (!text.empty() && std::isspace(static_cast<unsigned char>(text.back())))
    {
        text.remove_suffix(1);
    }

    std::string name(text);
    std::transform(
        name.begin(), name.end(), name.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

    static constexpr std::pair<std::string_view, spdlog::level::level_enum> kNames[] = {
        { "trace", spdlog::level::trace },  { "debug", spdlog::level::debug }, { "info", spdlog::level::info },
        { "warning", spdlog::level::warn }, { "error", spdlog::level::err },   { "critical", spdlog::level::critical },
    };
    for (const auto& [candidate, level] : kNames)
    {
        if (name == candidate)
        {
            return level;
        }
    }

    // Python's numeric form, bucketed: spdlog has no room between its six levels.
    const char* first = name.data() + (name.starts_with('+') ? 1 : 0);
    const char* last = name.data() + name.size();
    long long numeric = 0;
    const auto [end, ec] = std::from_chars(first, last, numeric);
    if (ec != std::errc{} || end != last)
    {
        return spdlog::level::info;
    }
    if (numeric <= 5)
    {
        return spdlog::level::trace;
    }
    if (numeric <= 10)
    {
        return spdlog::level::debug;
    }
    if (numeric <= 20)
    {
        return spdlog::level::info;
    }
    if (numeric <= 30)
    {
        return spdlog::level::warn;
    }
    if (numeric <= 40)
    {
        return spdlog::level::err;
    }
    if (numeric <= 50)
    {
        return spdlog::level::critical;
    }
    return spdlog::level::off;
}

} // namespace

const std::vector<spdlog::sink_ptr>& local_sinks()
{
    static const std::vector<spdlog::sink_ptr> sinks = []
    {
        // Set by the process that spawned us (the session leader, or an intermediate
        // forwarder) so its own logging_config receiver becomes the one place that
        // formats, filters and persists every process's records. A standalone run
        // with nothing to forward to falls back to this process's own sinks below.
        if (auto socket_path = forwarding_socket_path(); !socket_path.empty())
        {
            auto forward = std::make_shared<SocketForwardSink>(std::move(socket_path));
            forward->set_level(spdlog::level::trace); // the receiver's own logger does the filtering
            return std::vector<spdlog::sink_ptr>{ forward };
        }

        // Built first and unconditionally: everything below it can fail on a
        // directory this process may not write, and Logger::get() -- which every
        // diagnostic call site in the tree treats as infallible -- must not throw.
        // stderr, like the Python half's console handler: on stdout a standalone
        // tool's own product and its diagnostics share one descriptor, so
        // `tool > data.txt` both swallows the diagnostics and corrupts the data.
        auto console = std::make_shared<spdlog::sinks::stderr_color_sink_mt>();
        console->set_level(console_level());
        console->set_formatter(make_formatter());

        auto dir = log_dir();
#ifndef _WIN32
        // Every component this call is about to create, deepest first. The Python
        // half chmods each of them, not just the leaf, because the default log
        // directory is <runtime dir>/logs and the runtime directory is where the
        // log socket lives; chmodding only the leaf left it at the umask.
        std::vector<std::filesystem::path> missing;
        {
            std::error_code exists_ec;
            std::filesystem::path probe = dir;
            while (!probe.empty() && probe != probe.parent_path() && !std::filesystem::exists(probe, exists_ec))
            {
                missing.push_back(probe);
                probe = probe.parent_path();
            }
        }
#endif
        std::error_code dir_ec;
        std::filesystem::create_directories(dir, dir_ec);
#ifndef _WIN32
        // Owner-only, and only on what this call created -- an operator-chosen
        // ISAACTELEOP_LOG_DIR keeps the permissions the operator gave it.
        for (const auto& component : missing)
        {
            std::error_code perms_ec;
            std::filesystem::permissions(
                component, std::filesystem::perms::owner_all, std::filesystem::perm_options::replace, perms_ec);
        }
#endif

        // One file per writer: the leading timestamp makes the run's start
        // time the first thing the name says and guards against a reused pid
        // colliding with an older run's file; the pid guards against two
        // processes starting in the same second. See unique_log_path() for what
        // ".cpp" and the numeric suffix are keeping apart.
        auto filename =
            unique_log_path(dir, current_timestamp() + ".isaacteleop." + std::to_string(current_pid()) + ".cpp");
        if (filename.empty())
        {
            return std::vector<spdlog::sink_ptr>{ console };
        }

        try
        {
            spdlog::file_event_handlers events;
#ifndef _WIN32
            events.after_open = harden_log_file;
#endif
            auto file = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(
                filename.string(), kFileMaxBytes, kFileBackupCount, false, events);
            file->set_level(spdlog::level::debug); // always captures everything, not user-configurable
            file->set_formatter(make_formatter());
            return std::vector<spdlog::sink_ptr>{ console, file };
        }
        catch (const spdlog::spdlog_ex&)
        {
            // Console only, and reported nowhere: this call is what builds the sinks
            // every logger is created with, so there is no logger to report through.
            return std::vector<spdlog::sink_ptr>{ console };
        }
    }();
    return sinks;
}

} // namespace isaacteleop::detail
