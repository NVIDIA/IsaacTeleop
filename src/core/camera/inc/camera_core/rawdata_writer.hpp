// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "record_config.hpp"

#include <cstdint>
#include <fstream>
#include <vector>

namespace core
{

/**
 * @brief Raw H.264 file writer
 *
 * Writes H.264 NAL units directly to a file without container.
 * File opens in constructor and closes in destructor (RAII).
 */
// TODO(shaoxiangs): abstract RawDataWriter with writer interface.
class RawDataWriter
{
public:
    explicit RawDataWriter(const RecordConfig& config);
    ~RawDataWriter();

    // Non-copyable, non-movable
    RawDataWriter(const RawDataWriter&) = delete;
    RawDataWriter& operator=(const RawDataWriter&) = delete;

    void write(const std::vector<uint8_t>& data);

    size_t bytes_written() const;
    size_t frame_count() const;

private:
    std::ofstream m_file;
    size_t m_bytes_written = 0;
    size_t m_frame_count = 0;
};

} // namespace core
