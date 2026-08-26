// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/mcap/recorded_schemas.hpp"

#include <algorithm>
#include <stdexcept>

namespace core
{

namespace
{

//! Whether every channel names a Schema record the reader holds. A channel may name none.
bool schemas_resolved(const mcap::McapReader& reader,
                      const std::unordered_map<mcap::ChannelId, mcap::ChannelPtr>& channels)
{
    for (const auto& entry : channels)
    {
        if (entry.second != nullptr && entry.second->schemaId != 0 && reader.schema(entry.second->schemaId) == nullptr)
        {
            return false;
        }
    }
    return true;
}

} // namespace

RecordedSchemas::RecordedSchemas(mcap::McapReader& reader)
{
    // Asking for the scan here rather than through AllowFallbackScan is what keeps the data
    // section to at most one walk: the two-step would scan, come up short, and scan again.
    const auto ignore_problem = [](const mcap::Status&) {};
    mcap::Status status = reader.readSummary(mcap::ReadSummaryMethod::NoFallbackScan, ignore_problem);
    if (!status.ok() || !schemas_resolved(reader, reader.channels()))
    {
        status = reader.readSummary(mcap::ReadSummaryMethod::ForceScan, ignore_problem);
    }

    // A scan that runs into damage stops where it is and still reports success -- reaching the
    // end of a truncated chunk is indistinguishable from reaching the end of the data. What it
    // has to show for itself is the test: a recording anything replays declares channels, so
    // coming back with none means the records that say what this file holds were not readable.
    if (!status.ok() || reader.channels().empty())
    {
        throw std::runtime_error("RecordedSchemas: cannot tell what this recording holds" +
                                 (status.ok() ? std::string(": it declares no channels") : ": " + status.message) +
                                 " (it is damaged, or was cut short before its writer closed it)");
    }

    for (const auto& entry : reader.channels())
    {
        const mcap::ChannelPtr& channel = entry.second;
        if (channel == nullptr)
        {
            continue;
        }
        channels_.push_back({ channel->topic, channel->messageEncoding, reader.schema(channel->schemaId) });
    }

    // The reader holds channels in a hash map, so without this which one a mismatch is reported
    // against varies between runs of the same file.
    std::sort(channels_.begin(), channels_.end(), [](const Channel& a, const Channel& b) { return a.topic < b.topic; });
}

} // namespace core
