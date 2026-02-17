// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "frame_sink_interface.hpp"

#include <mcap/types.hpp>
#include <mcap/writer.hpp>

#include <cstdint>
#include <string>

namespace plugins
{
namespace oak
{

/**
 * @brief MCAP output sink for OAK frames.
 *
 * Writes each OakFrame (H.264 data + metadata) as a single McapFrame message
 * into an MCAP file, using the schema defined in mcap_frame.fbs.
 *
 * RAII: the MCAP file is opened in the constructor and closed in the destructor.
 */
class McapFrameSink : public IFrameSink
{
public:
    /**
     * @brief Construct the sink and open the MCAP file.
     * @param record_path Full path to the output .mcap file.
     *                    Parent directories are created automatically.
     * @throws std::runtime_error if the file cannot be opened.
     */
    explicit McapFrameSink(const std::string& record_path);
    ~McapFrameSink() override;

    // Non-copyable, non-movable
    McapFrameSink(const McapFrameSink&) = delete;
    McapFrameSink& operator=(const McapFrameSink&) = delete;
    McapFrameSink(McapFrameSink&&) = delete;
    McapFrameSink& operator=(McapFrameSink&&) = delete;

    /**
     * @brief Write a frame to the MCAP file.
     *
     * Serializes the OakFrame as a McapFrame FlatBuffer (metadata + h264_data)
     * and writes it as an MCAP message with the appropriate timestamp.
     */
    void on_frame(const OakFrame& frame) override;

private:
    mcap::McapWriter m_writer;
    mcap::ChannelId m_channel_id = 0;
    uint64_t m_message_count = 0;
};

} // namespace oak
} // namespace plugins
