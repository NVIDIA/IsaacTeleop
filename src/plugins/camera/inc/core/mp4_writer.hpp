// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <core/record_config.hpp>

#include <cstdint>
#include <string>
#include <vector>

// Forward declarations for FFmpeg types
struct AVFormatContext;
struct AVStream;

namespace plugins
{
namespace camera
{

/**
 * @brief MP4 file writer using FFmpeg libavformat
 *
 * Writes H.264 NAL units to an MP4 container.
 */
class Mp4Writer
{
public:
    explicit Mp4Writer(const RecordConfig& config);
    ~Mp4Writer();

    // Non-copyable, non-movable
    Mp4Writer(const Mp4Writer&) = delete;
    Mp4Writer& operator=(const Mp4Writer&) = delete;

    void open();
    void close();

    bool write(const uint8_t* data, size_t size);
    bool write(const std::vector<uint8_t>& data);

    size_t bytes_written() const;
    size_t frame_count() const;

private:
    static std::string av_error_string(int errnum);
    size_t find_start_code(const uint8_t* data, size_t size, size_t pos);
    size_t skip_start_code(const uint8_t* data, size_t size, size_t pos);
    bool extract_extradata(const uint8_t* data, size_t size);
    bool write_annex_b_frame(const uint8_t* data, size_t size);

    RecordConfig m_config;
    std::string m_path;

    AVFormatContext* m_format_ctx = nullptr;
    AVStream* m_stream = nullptr;

    std::vector<uint8_t> m_sps;
    std::vector<uint8_t> m_pps;

    bool m_header_written = false;
    int64_t m_pts = 0;
    size_t m_bytes_written = 0;
    size_t m_frame_count = 0;
};

} // namespace camera
} // namespace plugins
