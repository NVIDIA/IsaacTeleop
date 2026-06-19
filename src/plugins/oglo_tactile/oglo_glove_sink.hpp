// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "oglo_config.hpp"
#include "oglo_packet_parser.hpp"

#include <cstdint>
#include <memory>
#include <string>

namespace plugins
{
namespace oglo_tactile
{

//! Consumes decoded glove samples and records / publishes them.
//!
//! Mirrors the OAK plugin's two recording modes: a local MCAP file
//! (self-contained, no OpenXR) or an OpenXR SchemaPusher collection that a host
//! tracker reads into a shared TeleopSession MCAP.
class IGloveSink
{
public:
    virtual ~IGloveSink() = default;

    //! Record one sample. Timestamps are nanoseconds: @p local_ns on the host
    //! monotonic clock (shared across devices), @p raw_ns on the device clock.
    //! Called from the plugin's single push thread.
    virtual void on_sample(const GloveSample& sample, int64_t local_ns, int64_t raw_ns) = 0;
};

//! Selects the sink from the two mutually exclusive output modes.
//!
//! @param side          Glove side (left/right), used in channel/collection names.
//! @param config        Device Config, attached as MCAP metadata for provenance.
//! @param mcap_filename Mode 1: local MCAP path (empty to disable).
//! @param collection_prefix Mode 2: OpenXR collection prefix (empty to disable).
//! @throws std::runtime_error if both or neither mode is given, or on open failure.
std::unique_ptr<IGloveSink> create_glove_sink(Side side,
                                              const OgloDeviceConfig& config,
                                              const std::string& mcap_filename,
                                              const std::string& collection_prefix);

} // namespace oglo_tactile
} // namespace plugins
