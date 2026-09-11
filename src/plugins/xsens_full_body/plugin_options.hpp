// SPDX-FileCopyrightText: Copyright (c) 2026 Xsens Technologies B.V. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace plugins
{
namespace xsens_full_body
{

//! Everything the pusher is configured with, and the defaults it runs on when told nothing.
//!
//! Split out from `main.cpp` so the parser below can be unit tested: the plugin itself owns a
//! socket and an OpenXR session and cannot be constructed without a running CloudXR runtime,
//! which previously made argument handling reachable only through a live end-to-end run. Same
//! reason `frame_decision.{hpp,cpp}` is its own unit.
struct XsensFullBodyOptions
{
    //! The string the pusher and the reader rendezvous on. A mismatch fails silently and
    //! forever, which is why the parser refuses an empty one.
    std::string collection_id = "xsens_full_body";
    //! Interface to bind the receive socket to. `0.0.0.0` accepts the stream on every interface;
    //! a literal address narrows it to one, which is also how a run is confined to loopback.
    std::string bind_address = "0.0.0.0";
    uint16_t udp_port = 9764;
    //! Must match the reader's `max_flatbuffer_size`. A mismatch throws loudly on both sides --
    //! which is the good case; a `collection_id` mismatch instead fails silently and forever.
    size_t max_flatbuffer_size = 4096;

    //! Set when the deprecated positional form was used. Parse metadata rather than
    //! configuration: the parser stays free of I/O, and the caller decides how to warn.
    bool used_legacy_positionals = false;
};

enum class ParseOutcome
{
    Ok,
    HelpRequested,
    Error
};

/*!
 * @brief Parse the command line into \a out.
 *
 * Accepts the flag form (`--collection-id=`, `--address=`, `--port=`, `--max-flatbuffer-size=`)
 * and, deprecated, the original positional form `[collection_id] [udp_port]
 * [max_flatbuffer_size]`. The two cannot be mixed. `--plugin-root-id` is swallowed in both its
 * spellings: the plugin launcher injects it ahead of `plugin.yaml`'s own arguments.
 *
 * @param error filled with an operator-facing message when ParseOutcome::Error is returned.
 */
ParseOutcome parse_options(int argc, const char* const* argv, XsensFullBodyOptions& out, std::string& error);

} // namespace xsens_full_body
} // namespace plugins
