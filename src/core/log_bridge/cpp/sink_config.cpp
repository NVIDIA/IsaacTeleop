// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "sink_config.hpp"

#include "socket_sink.hpp"

#include <spdlog/common.h>
#include <spdlog/sinks/rotating_file_sink.h>
#include <spdlog/sinks/stdout_color_sinks.h>

#include <algorithm>
#include <cctype>
#include <charconv>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <filesystem>
#include <string>
#include <system_error>

#ifndef _WIN32
#    include <sys/stat.h>

#    include <fcntl.h>
#    include <pwd.h>
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
// [timestamp] [LEVEL ] [logger.name] [pid:N] message -- same shape as the
// Python side's LINE_FORMAT (isaacteleop/logging_config/_core.py).
constexpr const char* kPattern = "[%Y-%m-%d %H:%M:%S.%e] [%-7l] [%n] [pid:%P] %v";

#ifndef _WIN32
// Path.expanduser(), matched. An operator who writes ISAACTELEOP_LOG_DIR=~/logs
// -- quoted, or assigned from Python, so no shell ever touched the tilde --
// otherwise has the two halves disagree: Python resolves it against the home
// directory while this one creates a directory literally named "~" under the
// process's cwd, which for a plugin is wherever plugin.cpp chdir'd it.
// Returns an empty path when it cannot resolve the tilde, so log_dir() falls
// back to the default -- which is what the Python half does now that
// expanduser()'s RuntimeError is caught there. ~user is not expanded.
std::filesystem::path expand_user(const std::string& raw)
{
    if (raw.empty() || raw[0] != '~' || (raw.size() > 1 && raw[1] != '/'))
    {
        return raw.empty() || raw[0] != '~' ? std::filesystem::path(raw) : std::filesystem::path();
    }
    const char* home = std::getenv("HOME");
    if (home == nullptr || home[0] == '\0')
    {
        const ::passwd* entry = ::getpwuid(::getuid());
        home = (entry != nullptr) ? entry->pw_dir : nullptr;
    }
    if (home == nullptr || home[0] == '\0')
    {
        return {}; // Nothing to resolve it against.
    }
    return raw.size() == 1 ? std::filesystem::path(home) : std::filesystem::path(home) / raw.substr(2);
}

bool ancestors_are_private(const std::filesystem::path& path)
{
    std::filesystem::path previous = path;
    std::filesystem::path parent = path.parent_path();
    while (!parent.empty() && parent != previous)
    {
        struct ::stat parent_info
        {
        };
        if (::lstat(parent.c_str(), &parent_info) != 0 || (parent_info.st_uid != ::getuid() && parent_info.st_uid != 0))
        {
            return false;
        }
        // A symlink ancestor is judged by its owner alone: its own mode bits are
        // not its target's (Linux reports 0777), so testing them here would refuse
        // ordinary paths -- /tmp and /var are symlinks on macOS.
        if (!S_ISLNK(parent_info.st_mode))
        {
            if (!S_ISDIR(parent_info.st_mode))
            {
                return false;
            }
            constexpr mode_t kSharedWrite = S_IWGRP | S_IWOTH;
            if ((parent_info.st_mode & kSharedWrite) != 0 && (parent_info.st_mode & S_ISVTX) == 0)
            {
                return false;
            }
        }
        previous = parent;
        parent = parent.parent_path();
    }
    return true;
}

// Mirrors ensure_private_dir() in the Python half. Check both the lexical path
// (which owns any symlinks) and its resolved path (which owns their targets).
// Never throws or reports: a false here costs the file sink and nothing else.
bool directory_is_private(const std::filesystem::path& dir)
{
    struct ::stat info
    {
    };
    if (::lstat(dir.c_str(), &info) != 0 || !S_ISDIR(info.st_mode) || info.st_uid != ::getuid() ||
        !ancestors_are_private(dir))
    {
        return false;
    }

    std::error_code canonical_ec;
    const std::filesystem::path resolved = std::filesystem::canonical(dir, canonical_ec);
    return !canonical_ec && ancestors_are_private(resolved);
}

void secure_log_file(const spdlog::filename_t& filename, std::FILE* file)
{
    const int fd = ::fileno(file);
    struct ::stat opened
    {
    };
    struct ::stat path
    {
    };
    const bool safe = fd >= 0 && ::fstat(fd, &opened) == 0 && ::lstat(filename.c_str(), &path) == 0 &&
                      S_ISREG(opened.st_mode) && S_ISREG(path.st_mode) && opened.st_uid == ::getuid() &&
                      opened.st_dev == path.st_dev && opened.st_ino == path.st_ino && ::fchmod(fd, 0600) == 0;
    if (safe)
    {
        const int flags = ::fcntl(fd, F_GETFD);
        if (flags >= 0)
        {
            ::fcntl(fd, F_SETFD, flags | FD_CLOEXEC);
        }
        return;
    }

    // Keep the sink valid but prevent a planted path from receiving records.
    const int null_fd = ::open("/dev/null", O_WRONLY);
    if (null_fd >= 0)
    {
        ::dup2(null_fd, fd);
        ::close(null_fd);
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
    // on the Python side. This used to accept "" as a literal empty path.
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
    // The Python side resolves tempfile.gettempdir() here, which is already
    // per-user; a literal "/tmp" resolves against the current drive's root
    // instead, so the two halves of one session wrote to two directories. The
    // cwd fallback is Python's last resort too.
    std::error_code temp_ec;
    const auto temp_dir = std::filesystem::temp_directory_path(temp_ec);
    return (temp_ec ? std::filesystem::path(".") : temp_dir) / "isaacteleop" / "logs";
#endif
}

// Mirrors isaacteleop.logging_config's names and integer thresholds.
// spdlog::level::from_str() is deliberately not used here: it answers
// level::off for anything it does not recognise, so a typo would silently mute
// every standalone plugin instead of falling back to info.
spdlog::level::level_enum console_level()
{
    const char* level_str = std::getenv("ISAACTELEOP_LOG_LEVEL");
    if (level_str == nullptr)
    {
        return spdlog::level::info;
    }

    std::string name(level_str);
    std::transform(
        name.begin(), name.end(), name.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

    if (name == "trace")
    {
        return spdlog::level::trace;
    }
    if (name == "debug")
    {
        return spdlog::level::debug;
    }
    if (name == "info")
    {
        return spdlog::level::info;
    }
    if (name == "warning" || name == "warn")
    {
        return spdlog::level::warn;
    }
    if (name == "error" || name == "err")
    {
        return spdlog::level::err;
    }
    if (name == "critical")
    {
        return spdlog::level::critical;
    }

    int numeric = 0;
    const auto [end, ec] = std::from_chars(name.data(), name.data() + name.size(), numeric);
    if (ec == std::errc{} && end == name.data() + name.size())
    {
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
    return spdlog::level::info;
}

} // namespace

const std::vector<spdlog::sink_ptr>& local_sinks()
{
    static const std::vector<spdlog::sink_ptr> sinks = []
    {
        // Set by the process that spawned us (the session leader, or an intermediate
        // forwarder) so its own logging_config receiver becomes the one place that
        // formats, filters, and persists every process's records -- the session's
        // single log file. Standalone/manual runs with nothing to forward to (no
        // ISAACTELEOP_LOG_SOCKET) fall back to this process's own console+file sinks
        // below, unchanged from before this existed.
        if (auto socket_path = forwarding_socket_path(); !socket_path.empty())
        {
            auto forward = std::make_shared<SocketForwardSink>(std::move(socket_path));
            forward->set_level(spdlog::level::trace); // the receiver's own logger does the filtering
            return std::vector<spdlog::sink_ptr>{ forward };
        }

        // Built first and unconditionally: everything below it can fail on a
        // directory this process may not write, and Logger::get() -- which every
        // diagnostic call site in the tree treats as infallible -- must not throw.
        auto console = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
        console->set_level(console_level());
        console->set_pattern(kPattern);

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
        // One file per process: concurrent processes rotating a shared file
        // can corrupt it, so each process gets its own (mirrors the Python
        // side's <timestamp>.isaacteleop.<pid>.log default). The leading
        // timestamp makes the run's start time the first thing the name says,
        // keeps a run's files adjacent whatever produced them, and guards
        // against a reused pid colliding with an older run's file; the pid
        // still guards against two processes starting in the same second.
        auto filename = dir / (current_timestamp() + ".isaacteleop." + std::to_string(current_pid()) + ".log");

#ifndef _WIN32
        // Whoever owns the directory decides who reads what lands in it, and
        // create_directories() succeeds silently on one that already exists --
        // so without this a directory another user planted at the predictable
        // default path collected this process's whole log. The Python half
        // refuses the same shape; before this it refused and this did not.
        if (!directory_is_private(dir))
        {
            return std::vector<spdlog::sink_ptr>{ console };
        }
#endif

        try
        {
            spdlog::file_event_handlers events;
#ifndef _WIN32
            events.after_open = secure_log_file;
#endif
            auto file = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(
                filename.string(), kFileMaxBytes, kFileBackupCount, false, events);
            file->set_level(spdlog::level::debug); // always captures everything, not user-configurable
            file->set_pattern(kPattern);
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
