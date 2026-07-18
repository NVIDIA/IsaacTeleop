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

//! Consumes decoded glove samples and publishes them over OpenXR.
//!
//! Pushes samples via an OpenXR SchemaPusher collection that a host
//! OgloTactileTracker reads into a shared TeleopSession MCAP.
class IGloveSink
{
public:
    virtual ~IGloveSink() = default;

    //! Publish one sample. Timestamps are nanoseconds: @p local_ns on the host
    //! monotonic clock (shared across devices), @p raw_ns on the device clock.
    //! Called from the plugin's single push thread.
    virtual void on_sample(const GloveSample& sample, int64_t local_ns, int64_t raw_ns) = 0;
};

//! Create the OpenXR SchemaPusher sink for a host tracker to consume.
//!
//! @param side              Glove side (left/right), used in the collection name.
//! @param collection_prefix OpenXR collection prefix (pushes @c PREFIX/left or
//!                          @c PREFIX/right).
//! @throws std::runtime_error if @p collection_prefix is empty.
std::unique_ptr<IGloveSink> create_glove_sink(Side side, const std::string& collection_prefix);

} // namespace oglo_tactile
} // namespace plugins
