// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "schema_tracker_base.hpp"

#include <flatbuffers/flatbuffers.h>
#include <mcap/tracker_channels.hpp>

#include <memory>

namespace core
{

/**
 * @brief Typed SchemaTracker that optionally records to MCAP.
 *
 * Wraps SchemaTrackerBase with FlatBuffer type knowledge so that each sample
 * read from the tensor can be automatically written to an MCAP channel.
 *
 * @tparam RecordT    FlatBuffer record wrapper (e.g. Generic3AxisPedalOutputRecord).
 * @tparam DataTableT FlatBuffer data table (e.g. Generic3AxisPedalOutput).
 */
template <typename RecordT, typename DataTableT>
class SchemaTracker : public SchemaTrackerBase
{
public:
    using NativeDataT = typename DataTableT::NativeTableType;
    using Channels = McapTrackerChannels<RecordT, DataTableT>;

    /**
     * @param mcap_channels Non-owning pointer to the MCAP channel writer. Must outlive
     *        this SchemaTracker. Owned by the live tracker impl that also owns this
     *        SchemaTracker instance. Null when recording is disabled.
     * @param mcap_channel_index 0-based sub-channel index within mcap_channels.
     */
    SchemaTracker(const OpenXRSessionHandles& handles,
                  SchemaTrackerConfig config,
                  Channels* mcap_channels = nullptr,
                  size_t mcap_channel_index = 0)
        : SchemaTrackerBase(handles, std::move(config)),
          mcap_channels_(mcap_channels),
          mcap_channel_index_(mcap_channel_index)
    {
    }

    /**
     * @brief Read all pending samples; write each to MCAP if channels are set.
     *
     * Each sample is unpacked, repacked into a Record with its timestamp,
     * and written to the MCAP channel. The last sample's unpacked data is
     * returned via out_latest (if non-null and samples were read).
     *
     * @param out_latest If non-null and samples were read, receives the unpacked
     *                   data from the last sample. Cleared when the tensor collection
     *                   is absent.
     * @throws std::runtime_error On critical OpenXR/tensor API failures propagated
     *         from SchemaTrackerBase.
     * @note Missing collection, temporary collection loss, and "no new sample"
     *       are treated as common non-fatal conditions and do not throw.
     */
    void update(std::shared_ptr<NativeDataT>& out_latest)
    {
        samples_.clear();
        bool present = read_all_samples(samples_);

        if (samples_.empty())
        {
            if (!present)
            {
                out_latest.reset();
            }
            return;
        }

        for (const auto& sample : samples_)
        {
            auto fb = flatbuffers::GetRoot<DataTableT>(sample.buffer.data());
            if (!fb)
            {
                continue;
            }

            if (!out_latest)
            {
                out_latest = std::make_shared<NativeDataT>();
            }
            fb->UnPackTo(out_latest.get());

            // write() serializes synchronously and does not retain the shared_ptr,
            // so reusing out_latest across loop iterations is safe.
            if (mcap_channels_)
            {
                mcap_channels_->write(mcap_channel_index_, sample.timestamp, out_latest);
            }
        }
    }

private:
    Channels* mcap_channels_;
    size_t mcap_channel_index_;
    std::vector<SampleResult> samples_;
};

} // namespace core
