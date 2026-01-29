// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/camera_core/rawdata_writer.hpp"

#include <chrono>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>

namespace core
{

std::string RecordConfig::get_output_path() const
{
    if (!output_path.empty())
    {
        return output_path;
    }

    // Auto-generate timestamped filename
    std::filesystem::create_directories(output_dir);

    auto now = std::chrono::system_clock::now();
    auto time = std::chrono::system_clock::to_time_t(now);
    std::tm tm = *std::localtime(&time);

    std::ostringstream oss;
    oss << output_dir << "/camera_recording_" << std::put_time(&tm, "%Y%m%d_%H%M%S") << ".h264";
    return oss.str();
}

RawDataWriter::RawDataWriter(const RecordConfig& config)
{
    auto path = config.get_output_path();
    if (path.empty())
    {
        throw std::runtime_error("No output path specified");
    }

    m_file.open(path, std::ios::binary);
    if (!m_file.is_open())
    {
        throw std::runtime_error("Failed to open file: " + path);
    }

    std::cout << "Recording to: " << path << std::endl;
}

RawDataWriter::~RawDataWriter()
{
    if (m_file.is_open())
    {
        m_file.close();
        std::cout << "Recording saved: " << m_bytes_written << " bytes, " << m_frame_count << " frames" << std::endl;
    }
}

void RawDataWriter::write(const std::vector<uint8_t>& data)
{
    if (data.empty())
    {
        return;
    }

    m_file.write(reinterpret_cast<const char*>(data.data()), data.size());
    if (!m_file.good())
    {
        throw std::runtime_error("Write error");
    }

    m_bytes_written += data.size();
    m_frame_count++;
}

size_t RawDataWriter::bytes_written() const
{
    return m_bytes_written;
}

size_t RawDataWriter::frame_count() const
{
    return m_frame_count;
}

} // namespace core
