// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <core/rawdata_writer.hpp>

#include <chrono>
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
        oss << output_dir << "/camera_recording_" << std::put_time(&tm, "%Y%m%d_%H%M%S") << ".h264";
        return oss.str();
    }

    return "";
}

RawDataWriter::RawDataWriter(const RecordConfig& config) : m_config(config)
{
    m_path = m_config.get_output_path();
    if (m_path.empty())
    {
        throw std::runtime_error("No output path specified");
    }
}

RawDataWriter::~RawDataWriter()
{
    close();
}

void RawDataWriter::open()
{
    m_file.open(m_path, std::ios::binary);
    if (!m_file.is_open())
    {
        throw std::runtime_error("Failed to open file: " + m_path);
    }

    m_bytes_written = 0;
    m_frame_count = 0;

    std::cout << "Recording to: " << m_path << std::endl;
}

void RawDataWriter::close()
{
    if (m_file.is_open())
    {
        m_file.close();
        std::cout << "Recording saved: " << m_path << " (" << m_bytes_written << " bytes, " << m_frame_count
                  << " frames)" << std::endl;
    }
}

bool RawDataWriter::write(const std::vector<uint8_t>& data)
{
    if (!m_file.is_open() || data.empty())
    {
        return false;
    }

    m_file.write(reinterpret_cast<const char*>(data.data()), data.size());
    if (!m_file.good())
    {
        std::cerr << "Write error" << std::endl;
        return false;
    }

    m_bytes_written += data.size();
    m_frame_count++;
    return true;
}

size_t RawDataWriter::bytes_written() const
{
    return m_bytes_written;
}

size_t RawDataWriter::frame_count() const
{
    return m_frame_count;
}

} // namespace camera
} // namespace plugins
