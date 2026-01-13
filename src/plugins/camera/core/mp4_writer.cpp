// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <core/mp4_writer.hpp>

extern "C"
{
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/opt.h>
}

#include <chrono>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>

namespace plugins
{
namespace camera
{

std::string RecordConfig::get_output_path() const
{
    if (!output_path.empty())
    {
        return output_path;
    }

    if (auto_name)
    {
        std::filesystem::create_directories(output_dir);

        auto now = std::chrono::system_clock::now();
        auto time = std::chrono::system_clock::to_time_t(now);
        std::tm tm = *std::localtime(&time);

        std::ostringstream oss;
        oss << output_dir << "/camera_recording_" << std::put_time(&tm, "%Y%m%d_%H%M%S") << ".mp4";
        return oss.str();
    }

    return "";
}

Mp4Writer::Mp4Writer(const RecordConfig& config) : m_config(config)
{
    m_path = m_config.get_output_path();
    if (m_path.empty())
    {
        throw std::runtime_error("No output path specified");
    }
}

Mp4Writer::~Mp4Writer()
{
    close();
}

void Mp4Writer::open()
{
    if (m_format_ctx)
    {
        return;
    }

    // Allocate output format context
    int ret = avformat_alloc_output_context2(&m_format_ctx, nullptr, "mp4", m_path.c_str());
    if (ret < 0 || !m_format_ctx)
    {
        throw std::runtime_error("Failed to create output context: " + av_error_string(ret));
    }

    // Create video stream
    m_stream = avformat_new_stream(m_format_ctx, nullptr);
    if (!m_stream)
    {
        avformat_free_context(m_format_ctx);
        m_format_ctx = nullptr;
        throw std::runtime_error("Failed to create video stream");
    }

    // Set up codec parameters for H.264
    m_stream->codecpar->codec_type = AVMEDIA_TYPE_VIDEO;
    m_stream->codecpar->codec_id = AV_CODEC_ID_H264;
    m_stream->codecpar->width = m_config.width;
    m_stream->codecpar->height = m_config.height;
    m_stream->codecpar->format = AV_PIX_FMT_YUV420P;
    m_stream->time_base = AVRational{ 1, 90000 }; // 90kHz timebase (standard for video)
    m_stream->avg_frame_rate = AVRational{ m_config.fps, 1 };

    // Open output file
    if (!(m_format_ctx->oformat->flags & AVFMT_NOFILE))
    {
        ret = avio_open(&m_format_ctx->pb, m_path.c_str(), AVIO_FLAG_WRITE);
        if (ret < 0)
        {
            avformat_free_context(m_format_ctx);
            m_format_ctx = nullptr;
            throw std::runtime_error("Failed to open output file: " + av_error_string(ret));
        }
    }

    // Write header (will be finalized when we have extradata from SPS/PPS)
    m_header_written = false;
    m_bytes_written = 0;
    m_frame_count = 0;
    m_pts = 0;

    std::cout << "Recording to: " << m_path << std::endl;
}

void Mp4Writer::close()
{
    if (m_format_ctx)
    {
        // Write trailer if header was written
        if (m_header_written)
        {
            av_write_trailer(m_format_ctx);
        }

        // Close file
        if (!(m_format_ctx->oformat->flags & AVFMT_NOFILE))
        {
            avio_closep(&m_format_ctx->pb);
        }

        avformat_free_context(m_format_ctx);
        m_format_ctx = nullptr;

        std::cout << "Recording saved: " << m_path << " (" << m_bytes_written << " bytes, " << m_frame_count
                  << " frames)" << std::endl;
    }
}

bool Mp4Writer::write(const uint8_t* data, size_t size)
{
    if (!m_format_ctx || !data || size == 0)
    {
        return false;
    }

    // Parse NAL units to extract SPS/PPS for extradata
    if (!m_header_written)
    {
        if (!extract_extradata(data, size))
        {
            // Haven't found SPS/PPS yet, buffer the data
            return true;
        }

        // Write file header now that we have extradata
        int ret = avformat_write_header(m_format_ctx, nullptr);
        if (ret < 0)
        {
            std::cerr << "Failed to write header: " << av_error_string(ret) << std::endl;
            return false;
        }
        m_header_written = true;
    }

    // Convert Annex B to AVCC format and write packet
    return write_annex_b_frame(data, size);
}

bool Mp4Writer::write(const std::vector<uint8_t>& data)
{
    return write(data.data(), data.size());
}

std::string Mp4Writer::get_path() const
{
    return m_path;
}

size_t Mp4Writer::bytes_written() const
{
    return m_bytes_written;
}

size_t Mp4Writer::frame_count() const
{
    return m_frame_count;
}

std::string Mp4Writer::av_error_string(int errnum)
{
    char buf[AV_ERROR_MAX_STRING_SIZE];
    av_strerror(errnum, buf, sizeof(buf));
    return std::string(buf);
}

size_t Mp4Writer::find_start_code(const uint8_t* data, size_t size, size_t pos)
{
    while (pos + 3 < size)
    {
        if (data[pos] == 0 && data[pos + 1] == 0)
        {
            if (data[pos + 2] == 1)
            {
                return pos;
            }
            if (pos + 3 < size && data[pos + 2] == 0 && data[pos + 3] == 1)
            {
                return pos;
            }
        }
        pos++;
    }
    return size;
}

size_t Mp4Writer::skip_start_code(const uint8_t* data, size_t size, size_t pos)
{
    if (pos + 4 <= size && data[pos] == 0 && data[pos + 1] == 0 && data[pos + 2] == 0 && data[pos + 3] == 1)
    {
        return pos + 4;
    }
    if (pos + 3 <= size && data[pos] == 0 && data[pos + 1] == 0 && data[pos + 2] == 1)
    {
        return pos + 3;
    }
    return pos;
}

bool Mp4Writer::extract_extradata(const uint8_t* data, size_t size)
{
    // Look for SPS and PPS NAL units
    size_t pos = 0;
    while (pos < size)
    {
        size_t start = find_start_code(data, size, pos);
        if (start >= size)
            break;

        size_t nal_start = skip_start_code(data, size, start);
        size_t next = find_start_code(data, size, nal_start);
        size_t nal_size = next - nal_start;

        if (nal_size > 0)
        {
            uint8_t nal_type = data[nal_start] & 0x1F;

            if (nal_type == 7) // SPS
            {
                m_sps.assign(data + nal_start, data + nal_start + nal_size);
            }
            else if (nal_type == 8) // PPS
            {
                m_pps.assign(data + nal_start, data + nal_start + nal_size);
            }
        }

        pos = next;
    }

    // Build AVCC extradata when we have both SPS and PPS
    if (!m_sps.empty() && !m_pps.empty() && m_stream->codecpar->extradata == nullptr)
    {
        // AVCC format: see ISO/IEC 14496-15
        size_t extradata_size = 6 + 2 + m_sps.size() + 1 + 2 + m_pps.size();
        uint8_t* extradata = static_cast<uint8_t*>(av_malloc(extradata_size + AV_INPUT_BUFFER_PADDING_SIZE));

        size_t i = 0;
        extradata[i++] = 1; // version
        extradata[i++] = m_sps[1]; // profile
        extradata[i++] = m_sps[2]; // compatibility
        extradata[i++] = m_sps[3]; // level
        extradata[i++] = 0xFF; // 6 bits reserved + 2 bits NAL size length - 1 (3 = 4 bytes)
        extradata[i++] = 0xE1; // 3 bits reserved + 5 bits SPS count (1)
        extradata[i++] = (m_sps.size() >> 8) & 0xFF;
        extradata[i++] = m_sps.size() & 0xFF;
        memcpy(extradata + i, m_sps.data(), m_sps.size());
        i += m_sps.size();
        extradata[i++] = 1; // PPS count
        extradata[i++] = (m_pps.size() >> 8) & 0xFF;
        extradata[i++] = m_pps.size() & 0xFF;
        memcpy(extradata + i, m_pps.data(), m_pps.size());

        m_stream->codecpar->extradata = extradata;
        m_stream->codecpar->extradata_size = static_cast<int>(extradata_size);

        return true;
    }

    return m_stream->codecpar->extradata != nullptr;
}

bool Mp4Writer::write_annex_b_frame(const uint8_t* data, size_t size)
{
    // Build AVCC format packet (4-byte length prefix instead of start codes)
    std::vector<uint8_t> avcc_data;
    avcc_data.reserve(size);

    bool is_keyframe = false;
    size_t pos = 0;

    while (pos < size)
    {
        size_t start = find_start_code(data, size, pos);
        if (start >= size)
            break;

        size_t nal_start = skip_start_code(data, size, start);
        size_t next = find_start_code(data, size, nal_start);
        size_t nal_size = next - nal_start;

        if (nal_size > 0)
        {
            uint8_t nal_type = data[nal_start] & 0x1F;

            // Skip SPS/PPS (already in extradata)
            if (nal_type != 7 && nal_type != 8)
            {
                // Check for IDR frame
                if (nal_type == 5)
                {
                    is_keyframe = true;
                }

                // Add 4-byte length prefix (big-endian)
                avcc_data.push_back((nal_size >> 24) & 0xFF);
                avcc_data.push_back((nal_size >> 16) & 0xFF);
                avcc_data.push_back((nal_size >> 8) & 0xFF);
                avcc_data.push_back(nal_size & 0xFF);

                // Add NAL data
                avcc_data.insert(avcc_data.end(), data + nal_start, data + nal_start + nal_size);
            }
        }

        pos = next;
    }

    if (avcc_data.empty())
    {
        return true; // No VCL NALs, but not an error
    }

    // Create packet
    AVPacket* pkt = av_packet_alloc();
    if (!pkt)
    {
        return false;
    }

    pkt->data = avcc_data.data();
    pkt->size = static_cast<int>(avcc_data.size());
    pkt->stream_index = m_stream->index;
    pkt->pts = m_pts;
    pkt->dts = m_pts;
    pkt->duration = 90000 / m_config.fps; // Duration in 90kHz units

    if (is_keyframe)
    {
        pkt->flags |= AV_PKT_FLAG_KEY;
    }

    // Write packet
    int ret = av_interleaved_write_frame(m_format_ctx, pkt);
    av_packet_free(&pkt);

    if (ret < 0)
    {
        std::cerr << "Failed to write frame: " << av_error_string(ret) << std::endl;
        return false;
    }

    m_pts += 90000 / m_config.fps;
    m_bytes_written += size;
    m_frame_count++;

    return true;
}

} // namespace camera
} // namespace plugins
