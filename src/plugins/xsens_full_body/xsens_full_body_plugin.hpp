// SPDX-FileCopyrightText: Copyright (c) 2026 Xsens Technologies B.V. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "frame_decision.hpp"
#include "plugin_options.hpp"

#include <pusherio/schema_pusher.hpp>

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <ostream>
#include <string>
#include <vector>

namespace core
{
class OpenXRSession;
}

namespace plugins
{
namespace xsens_full_body
{

//! Counters reported on the periodic stats line; also the acceptance signal for a live run.
struct XsensFullBodyStats
{
    uint64_t delivered = 0;
    uint64_t dropped_malformed = 0;
    uint64_t dropped_unverified = 0;
    uint64_t dropped_stale = 0;
    //! Datagram larger than the receive buffer. Unreachable for IPv4 UDP (the buffer is bigger
    //! than the 65507 B maximum), counted so an over-large datagram is dropped rather than
    //! processed from a partial buffer.
    uint64_t dropped_truncated = 0;
    uint64_t timeline_rewinds = 0;
    //! Frames whose sample time was not a whole millisecond. A warning, not a drop -- these are
    //! counted in `delivered` too.
    uint64_t non_whole_ms_samples = 0;
    //! Two different questions, deliberately answered separately -- one number cannot do both,
    //! and reporting only one is how the same figure came to mean different things on the two
    //! branches. `gap_events` is how many times the stream jumped (a controller cares how often
    //! continuity broke); `sequence_numbers_skipped` is how many frames' worth went missing in
    //! total (a link report cares about volume). One 500-frame gap and 500 single-frame gaps are
    //! very different faults and are indistinguishable under either number alone.
    //!
    //! Neither is a transport-loss figure on its own -- see FrameOutcome::sequence_numbers_skipped.
    uint64_t sequence_gap_events = 0;
    uint64_t sequence_numbers_skipped = 0;
    uint64_t session_resets = 0;
    //! Hard `recv` errors survived by re-binding the port, and recovery episodes that gave up.
    uint64_t socket_recoveries = 0;
    uint64_t socket_recovery_failures = 0;
    //! `push_buffer` throws, and OpenXR sessions re-established in response.
    uint64_t push_failures = 0;
    uint64_t session_recoveries = 0;
    uint64_t last_seq = 0;
    uint64_t last_hash = 0;
    size_t last_size = 0;
};

/*!
 * @brief Receives Xsens MVN's Isaac Teleop UDP stream and republishes it as a tensor collection.
 *
 * MVN Studio already converts its 23-segment skeleton to the vendor-neutral 24-joint
 * XR_BD_body_tracking layout (see the "Isaac Teleop" network-streamer preset), so the payload
 * arriving here is a `core::FullBodyPose` FlatBuffer -- byte-identical to what any other
 * full-body vendor produces. This plugin therefore **forwards the payload bytes verbatim** and
 * never re-serializes: re-packing would risk silently changing a pose, and buys nothing.
 *
 * Pairs with the `body.xsens` vendor on the reader side:
 *
 *     deviceio.VendorConfig([(tracker, deviceio.TrackerVendor("body.xsens", {
 *         "collection_id": "xsens_full_body", "max_flatbuffer_size": "4096"}))])
 *
 * **Both of this plugin's dependencies can go away underneath it and come back.** The UDP socket
 * can fail hard, and the CloudXR runtime backing the OpenXR session can be restarted. Neither is
 * fatal: `update()` re-binds the socket and re-establishes the session on bounded backoffs, and
 * only throws once a retry budget is exhausted. See `recover_socket()` and `recover_session()`.
 */
class XsensFullBodyPlugin
{
public:
    explicit XsensFullBodyPlugin(const XsensFullBodyOptions& options);
    ~XsensFullBodyPlugin();

    XsensFullBodyPlugin(const XsensFullBodyPlugin&) = delete;
    XsensFullBodyPlugin& operator=(const XsensFullBodyPlugin&) = delete;

    /*!
     * @brief Block for one datagram (up to the socket timeout) and push it if it is valid.
     *
     * @param stop Observed during a recovery backoff so SIGINT/SIGTERM still stops the pusher
     *             promptly during an outage rather than waiting the whole budget out.
     * @return true if a frame was delivered, false on timeout, a rejected datagram, or a
     *         recovered outage.
     * @throws std::runtime_error when the socket or the OpenXR session could not be recovered
     *         within its retry budget. That is the operator-restart case; the caller should
     *         report the counters and exit.
     */
    bool update(const std::atomic<bool>& stop);

    const XsensFullBodyStats& stats() const
    {
        return stats_;
    }

private:
    /*!
     * @brief Per-category log throttle.
     *
     * A lossy link or a scrubbing operator can produce one event per frame, and these messages
     * are emitted from inside the receive loop. Each category therefore logs only its first
     * occurrence and every hundredth after that, so a flood cannot drown the console.
     */
    enum LogCategory
    {
        LC_TRUNCATED = 0,
        LC_OVERSIZE_PAYLOAD,
        LC_SESSION_RESET,
        LC_TIMELINE_REWIND,
        LC_NON_WHOLE_MS,
        LC_SOCKET_ERROR,
        LC_SOCKET_RECOVERED,
        LC_PUSH_FAILED,
        LC_COUNT
    };

    //! Read the XSENS_TELEOP_INJECT_RECV_ERRORS test hook. No-op unless it is set.
    void read_recv_error_injection();

    void open_socket(const std::string& address, uint16_t port);
    void close_socket();

    //! Create the OpenXR session and the pusher on it. Also the recovery path: both are torn
    //! down first, because once the runtime's IPC pipe breaks only a full re-create works.
    void establish_session();

    //! Re-bind the same address and port after a hard `recv` error, on a bounded backoff. Stream state is
    //! deliberately left alone: the outage reappears as a sequence gap or a session reset, and
    //! both are already handled. \return false if \a stop was set or the budget ran out.
    bool recover_socket(const std::atomic<bool>& stop);

    //! Re-establish the OpenXR session after `push_buffer` threw, on a bounded backoff.
    //! \return false if \a stop was set or the budget ran out.
    bool recover_session(const std::atomic<bool>& stop);

    //! Sleep \a total_ms in slices, returning early (false) if \a stop is set.
    static bool wait_unless_stopped(int total_ms, const std::atomic<bool>& stop);

    //! Emit \a message for \a category only on its first and every hundredth occurrence.
    //! Stream diagnostics go to stdout; anything an operator would call a problem -- a bad
    //! sender, a broken socket, a dead runtime -- goes to stderr, so the outage narrative reads
    //! in one place.
    void log_rate_limited(LogCategory category, const std::string& message, std::ostream& out);

    std::string collection_id_;
    size_t max_flatbuffer_size_ = 0;

    int socket_fd_ = -1;
    //! The address and port actually bound, assigned only once `bind()` has succeeded -- so a
    //! zero `port_` still means "never successfully bound", and recovery cannot drift onto a
    //! different interface than the one the operator asked for.
    std::string bind_address_;
    uint16_t port_ = 0;
    //! Recovery-matrix test hook, set from XSENS_TELEOP_INJECT_RECV_ERRORS=<n>[:<errno>]. Forces
    //! the next n recv calls to fail hard, which is the only practical way to exercise
    //! recover_socket() -- a real hard error needs the interface to fail underneath you. Zero,
    //! and therefore inert, unless the variable is set.
    int inject_recv_errors_left_ = 0;
    int inject_recv_errno_ = 0;
    std::vector<uint8_t> buffer_;
    XsensFullBodyStats stats_;
    //! Everything decided per datagram. Separate so it can be unit tested without a runtime.
    FrameDecider decider_;
    //! Occurrences seen per LogCategory, for rate limiting.
    uint64_t log_counts_[LC_COUNT] = {};

    std::shared_ptr<core::OpenXRSession> session_;
    //! Optional because SchemaPusher is neither copyable nor movable, and recovery has to
    //! destroy and re-create it in place.
    std::optional<core::SchemaPusher> pusher_;
};

} // namespace xsens_full_body
} // namespace plugins
