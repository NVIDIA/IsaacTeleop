// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "rawdata_writer.hpp"

#include <iostream>
#include <stdexcept>

namespace plugins
{
namespace oak
{

RawDataWriter::RawDataWriter(const std::string& path)
{
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
}

} // namespace oak
} // namespace plugins
