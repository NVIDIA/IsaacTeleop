// SPDX-FileCopyrightText: Copyright (c) 2026 Xsens Technologies B.V. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "xsens_full_body_plugin.hpp"

#include "frame_decision.hpp"
#include "teleop_wire.hpp"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/os_time.hpp>
#include <sys/socket.h>
#include <sys/time.h>

#include <cerrno>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <unistd.h>

namespace plugins
{
namespace xsens_full_body
{

namespace
{

constexpr std::string_view TENSOR_IDENTIFIER = "full_body_pose";
//! Bounded so a stalled MVN cannot wedge the loop; the caller just gets a false from update().
constexpr int RECV_TIMEOUT_MS = 250;
//! MVN's datagram is 820 B. Larger than the 65507 B maximum IPv4 UDP payload, so a valid
//! datagram is never truncated and the MSG_TRUNC check below is belt and braces.
constexpr size_t RECV_BUFFER_SIZE = 64 * 1024;

//! Log every event of a category on its 1st and every 100th occurrence.
constexpr uint64_t LOG_EVERY = 100;

//! Socket re-bind budget: ~2.3 s total. A hard recv error is almost always transient (an
//! interface bounce); anything longer than this is a machine problem, not a blip.
constexpr int SOCKET_BACKOFF_MS[] = { 100, 200, 400, 800, 800 };
constexpr int SOCKET_RECOVERY_ATTEMPTS = static_cast<int>(std::size(SOCKET_BACKOFF_MS));

//! Session re-establish budget: ~23.5 s total. Sized for a CloudXR runtime restart, which is
//! slow -- the runtime has to come up and re-advertise its extensions before we can bind again.
constexpr int SESSION_BACKOFF_MS[] = { 500, 1000, 2000, 4000, 4000, 4000, 4000, 4000 };
constexpr int SESSION_RECOVERY_ATTEMPTS = static_cast<int>(std::size(SESSION_BACKOFF_MS));

//! Backoffs are slept in slices so a stop request during a long outage lands promptly.
constexpr int BACKOFF_SLICE_MS = 50;

} // namespace

XsensFullBodyPlugin::XsensFullBodyPlugin(const XsensFullBodyOptions& options)
    : collection_id_(options.collection_id),
      max_flatbuffer_size_(options.max_flatbuffer_size),
      buffer_(RECV_BUFFER_SIZE),
      decider_(options.max_flatbuffer_size)
{
    read_recv_error_injection();

    // Session before socket: if the CloudXR runtime is absent we fail before taking the port,
    // so a retried start does not collide with itself.
    establish_session();
    open_socket(options.bind_address, options.udp_port);
}

void XsensFullBodyPlugin::read_recv_error_injection()
{
    const char* spec = std::getenv("XSENS_TELEOP_INJECT_RECV_ERRORS");
    if (spec == nullptr)
    {
        return;
    }
    // "<count>" or "<count>:<errno>"; ENOTCONN by default because it is unambiguously hard.
    char* rest = nullptr;
    const long count = std::strtol(spec, &rest, 10);
    inject_recv_errors_left_ = (count > 0) ? static_cast<int>(count) : 0;
    inject_recv_errno_ =
        (rest != nullptr && *rest == ':') ? static_cast<int>(std::strtol(rest + 1, nullptr, 10)) : ENOTCONN;
    if (inject_recv_errors_left_ > 0)
    {
        std::cerr << "[XsensFullBody] TEST HOOK: forcing the next " << inject_recv_errors_left_
                  << " recv call(s) to fail with errno " << inject_recv_errno_ << " ("
                  << std::strerror(inject_recv_errno_) << ")" << std::endl;
    }
}

XsensFullBodyPlugin::~XsensFullBodyPlugin()
{
    close_socket();
}

void XsensFullBodyPlugin::establish_session()
{
    // Torn down first, and in this order: once the runtime's IPC pipe breaks, the pusher's
    // collection handle is dead and only a full re-create works.
    pusher_.reset();
    session_.reset();

    session_ =
        std::make_shared<core::OpenXRSession>("XsensFullBodyPlugin", core::SchemaPusher::get_required_extensions());
    pusher_.emplace(
        session_->get_handles(), core::SchemaPusherConfig{ .collection_id = collection_id_,
                                                           .max_flatbuffer_size = max_flatbuffer_size_,
                                                           .tensor_identifier = std::string(TENSOR_IDENTIFIER),
                                                           .localized_name = "Xsens Full Body",
                                                           .app_name = "XsensFullBodyPlugin" });
}

void XsensFullBodyPlugin::open_socket(const std::string& address, uint16_t port)
{
    in_addr bind_addr{};
    if (::inet_pton(AF_INET, address.c_str(), &bind_addr) != 1)
    {
        // Validated at parse time (see plugin_options.cpp), so reaching here is a programmer
        // error rather than operator input.
        throw std::runtime_error("XsensFullBodyPlugin: '" + address + "' is not a literal IPv4 address");
    }

    socket_fd_ = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (socket_fd_ < 0)
    {
        throw std::runtime_error(std::string("XsensFullBodyPlugin: socket() failed: ") + std::strerror(errno));
    }

    int reuse = 1;
    if (::setsockopt(socket_fd_, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse)) < 0)
    {
        close_socket();
        throw std::runtime_error(std::string("XsensFullBodyPlugin: SO_REUSEADDR failed: ") + std::strerror(errno));
    }

    timeval timeout{};
    timeout.tv_sec = RECV_TIMEOUT_MS / 1000;
    timeout.tv_usec = (RECV_TIMEOUT_MS % 1000) * 1000;
    if (::setsockopt(socket_fd_, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) < 0)
    {
        close_socket();
        throw std::runtime_error(std::string("XsensFullBodyPlugin: SO_RCVTIMEO failed: ") + std::strerror(errno));
    }

    sockaddr_in endpoint{};
    endpoint.sin_family = AF_INET;
    endpoint.sin_addr = bind_addr;
    endpoint.sin_port = htons(port);
    if (::bind(socket_fd_, reinterpret_cast<sockaddr*>(&endpoint), sizeof(endpoint)) < 0)
    {
        // Two failures dominate here and they have opposite fixes, so the hint follows errno
        // rather than guessing. With a non-default --address, the second is the common one.
        const int reason_errno = errno;
        const std::string reason = std::strerror(reason_errno);
        const char* hint = "";
        if (reason_errno == EADDRINUSE)
        {
            hint = " (is another pusher already running?)";
        }
        else if (reason_errno == EADDRNOTAVAIL)
        {
            hint = " (no interface on this host has that address)";
        }
        close_socket();
        throw std::runtime_error("XsensFullBodyPlugin: bind to UDP " + address + ":" + std::to_string(port) +
                                 " failed: " + reason + hint);
    }
    bind_address_ = address;
    port_ = port;
}

void XsensFullBodyPlugin::close_socket()
{
    if (socket_fd_ >= 0)
    {
        ::close(socket_fd_);
        socket_fd_ = -1;
    }
}

void XsensFullBodyPlugin::log_rate_limited(LogCategory category, const std::string& message, std::ostream& out)
{
    const uint64_t n = ++log_counts_[category];
    if (n == 1 || (n % LOG_EVERY) == 0)
    {
        out << "[XsensFullBody] " << message;
        if (n > 1)
        {
            out << " (x" << n << ")";
        }
        out << std::endl;
    }
}

bool XsensFullBodyPlugin::wait_unless_stopped(int total_ms, const std::atomic<bool>& stop)
{
    for (int remaining = total_ms; remaining > 0; remaining -= BACKOFF_SLICE_MS)
    {
        if (stop.load(std::memory_order_relaxed))
        {
            return false;
        }
        std::this_thread::sleep_for(
            std::chrono::milliseconds(remaining < BACKOFF_SLICE_MS ? remaining : BACKOFF_SLICE_MS));
    }
    return !stop.load(std::memory_order_relaxed);
}

bool XsensFullBodyPlugin::recover_socket(const std::atomic<bool>& stop)
{
    // Without a port, re-binding would take an ephemeral one the sender cannot reach -- which
    // looks like a working pusher that never receives anything. Refuse instead. Zero here means
    // the first bind never succeeded, since both members are assigned only on success.
    if (port_ == 0)
    {
        ++stats_.socket_recovery_failures;
        return false;
    }

    for (int attempt = 0; attempt < SOCKET_RECOVERY_ATTEMPTS; ++attempt)
    {
        if (!wait_unless_stopped(SOCKET_BACKOFF_MS[attempt], stop))
        {
            return false;
        }

        close_socket(); // the dead fd, before asking for a new one
        try
        {
            open_socket(bind_address_, port_);
            ++stats_.socket_recoveries;
            log_rate_limited(
                LC_SOCKET_RECOVERED,
                "socket re-bound to UDP " + bind_address_ + ":" + std::to_string(port_) + ", receive loop continuing",
                std::cerr);
            return true;
        }
        catch (const std::exception& e)
        {
            // Expected while the interface is down; the caller reports the give-up.
            if (attempt == SOCKET_RECOVERY_ATTEMPTS - 1)
            {
                std::cerr << "[XsensFullBody] final socket re-bind attempt failed: " << e.what() << std::endl;
            }
        }
    }

    ++stats_.socket_recovery_failures;
    return false;
}

bool XsensFullBodyPlugin::recover_session(const std::atomic<bool>& stop)
{
    for (int attempt = 0; attempt < SESSION_RECOVERY_ATTEMPTS; ++attempt)
    {
        if (!wait_unless_stopped(SESSION_BACKOFF_MS[attempt], stop))
        {
            return false;
        }

        try
        {
            establish_session();
            ++stats_.session_recoveries;
            std::cout << "[XsensFullBody] OpenXR session re-established after " << (attempt + 1)
                      << " attempt(s); resuming push" << std::endl;
            return true;
        }
        catch (const std::exception& e)
        {
            // Expected while the runtime is down. Log only the first and last attempt, so a long
            // outage cannot flood the console with one line per retry.
            if (attempt == 0 || attempt == SESSION_RECOVERY_ATTEMPTS - 1)
            {
                std::cerr << "[XsensFullBody] session re-establish attempt " << (attempt + 1) << "/"
                          << SESSION_RECOVERY_ATTEMPTS << " failed: " << e.what() << std::endl;
            }
        }
    }
    return false;
}

bool XsensFullBodyPlugin::update(const std::atomic<bool>& stop)
{
    ssize_t received;
    if (inject_recv_errors_left_ > 0) // test hook; see read_recv_error_injection()
    {
        --inject_recv_errors_left_;
        errno = inject_recv_errno_;
        received = -1;
    }
    else
    {
        // MSG_TRUNC makes recv report the datagram's real length even when it overflowed the
        // buffer, so an over-large datagram is dropped rather than processed from a partial one.
        received = ::recv(socket_fd_, buffer_.data(), buffer_.size(), MSG_TRUNC);
    }
    if (received < 0)
    {
        // The idle path: the receive timeout expired, or a signal landed. Not an error, and it is
        // what paces this loop while MVN is not streaming.
        if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)
        {
            return false;
        }

        // Anything else is a hard socket error. Without this branch it would be indistinguishable
        // from "MVN is not streaming yet" and would spin the caller's loop at full CPU.
        const std::string reason = std::strerror(errno);
        log_rate_limited(
            LC_SOCKET_ERROR, "recv failed: " + reason + " -- re-binding UDP port " + std::to_string(port_), std::cerr);
        if (!recover_socket(stop))
        {
            if (stop.load(std::memory_order_relaxed))
            {
                return false; // stopping anyway; let the caller's loop exit normally
            }
            throw std::runtime_error("XsensFullBodyPlugin: UDP socket unrecoverable after " +
                                     std::to_string(SOCKET_RECOVERY_ATTEMPTS) +
                                     " re-bind attempts (last error: " + reason + ")");
        }
        return false;
    }
    if (received == 0)
    {
        return false; // empty datagram
    }
    if (static_cast<size_t>(received) > buffer_.size())
    {
        ++stats_.dropped_truncated;
        log_rate_limited(LC_TRUNCATED, "dropped over-large datagram (" + std::to_string(received) + " B)", std::cerr);
        return false;
    }

    const FrameOutcome outcome = decider_.classify(buffer_.data(), static_cast<size_t>(received));

    // Events are independent of the verdict: a delivered frame can still carry a session reset
    // or a rewind, so these are counted before the verdict is acted on.
    if (outcome.session_reset)
    {
        ++stats_.session_resets;
        log_rate_limited(LC_SESSION_RESET, "sequence reset -> new MVN session", std::cout);
    }
    if (outcome.sequence_numbers_skipped > 0)
    {
        ++stats_.sequence_gap_events;
        stats_.sequence_numbers_skipped += outcome.sequence_numbers_skipped;
    }
    if (outcome.non_whole_ms)
    {
        ++stats_.non_whole_ms_samples;
        log_rate_limited(LC_NON_WHOLE_MS,
                         "sample time is not a whole millisecond -- not from MVN's solver; delivering anyway", std::cout);
    }
    if (outcome.timeline_rewind)
    {
        ++stats_.timeline_rewinds;
        log_rate_limited(LC_TIMELINE_REWIND,
                         "sample time moved backwards -- timeline rewind (scrub or recording restart)", std::cout);
    }

    switch (outcome.verdict)
    {
    case FrameVerdict::Deliver:
        break;
    case FrameVerdict::DroppedOversize:
        // Counted as malformed, like any other unusable frame; logged separately because the
        // fix is specific and the number is the whole diagnosis.
        ++stats_.dropped_malformed;
        log_rate_limited(LC_OVERSIZE_PAYLOAD,
                         "payload " + std::to_string(outcome.observed_payload_size) + " B exceeds max_flatbuffer_size " +
                             std::to_string(max_flatbuffer_size_) + " -- raise it on BOTH pusher and reader",
                         std::cerr);
        return false;
    case FrameVerdict::DroppedMalformed:
        ++stats_.dropped_malformed;
        return false;
    case FrameVerdict::DroppedUnverified:
        ++stats_.dropped_unverified;
        return false;
    case FrameVerdict::DroppedStale:
        ++stats_.dropped_stale;
        return false;
    }

    // The header's sample_time_ns is on MVN's SEND-HOST clock -- a different domain from ours,
    // so it must not be published as the local common clock. Stamp the common clock here, at
    // publish time, and forward MVN's device clock verbatim alongside it.
    //
    // push_buffer THROWS on failure, and a dead CloudXR runtime arrives as
    // XR_ERROR_RUNTIME_FAILURE rather than anything session-shaped. Uncaught, a runtime restart
    // would take the whole pusher down with it.
    try
    {
        pusher_->push_buffer(
            outcome.payload, outcome.payload_size, core::os_monotonic_now_ns(), outcome.raw_device_time_ns);
    }
    catch (const std::exception& e)
    {
        ++stats_.push_failures;
        log_rate_limited(LC_PUSH_FAILED,
                         "push failed at seq=" + std::to_string(outcome.seq) + ": " + e.what() +
                             " -- re-establishing the OpenXR session",
                         std::cerr);
        if (!recover_session(stop))
        {
            if (stop.load(std::memory_order_relaxed))
            {
                return false; // stopping anyway; let the caller's loop exit normally
            }
            throw std::runtime_error("XsensFullBodyPlugin: OpenXR session unrecoverable after " +
                                     std::to_string(SESSION_RECOVERY_ATTEMPTS) +
                                     " re-establish attempts -- restart the CloudXR runtime, then restart "
                                     "this pusher");
        }
        return false; // recovered, but this frame is now stale; the next one goes out
    }

    ++stats_.delivered;
    stats_.last_seq = outcome.seq;
    stats_.last_size = outcome.payload_size;
    stats_.last_hash = fnv1a64(outcome.payload, outcome.payload_size);
    return true;
}

} // namespace xsens_full_body
} // namespace plugins
