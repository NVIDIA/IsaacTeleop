// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "h264_file_reader.hpp"

#include <ios>
#include <stdexcept>

namespace viz_smoke
{

namespace
{

// Looks for the next Annex B start code (00 00 00 01 or 00 00 01)
// starting at offset start. Returns the offset of the first 00 byte
// of the start code, or bytes.size() if none.
size_t find_start_code(const std::vector<uint8_t>& bytes, size_t start)
{
    if (bytes.size() < 3)
    {
        return bytes.size();
    }
    for (size_t i = start; i + 2 < bytes.size(); ++i)
    {
        if (bytes[i] == 0x00 && bytes[i + 1] == 0x00)
        {
            if (bytes[i + 2] == 0x01)
            {
                return i;
            }
            if (i + 3 < bytes.size() && bytes[i + 2] == 0x00 && bytes[i + 3] == 0x01)
            {
                return i;
            }
        }
    }
    return bytes.size();
}

} // namespace

H264FileReader::H264FileReader(const std::string& path)
{
    load_file(path);
}

void H264FileReader::load_file(const std::string& path)
{
    std::ifstream f(path, std::ios::binary | std::ios::ate);
    if (!f)
    {
        throw std::runtime_error("H264FileReader: cannot open " + path);
    }
    const std::streamsize size = f.tellg();
    if (size <= 0)
    {
        throw std::runtime_error("H264FileReader: empty file " + path);
    }
    f.seekg(0, std::ios::beg);
    bytes_.resize(static_cast<size_t>(size));
    if (!f.read(reinterpret_cast<char*>(bytes_.data()), size))
    {
        throw std::runtime_error("H264FileReader: read failed for " + path);
    }
    // Stream must start with a NAL start code; reject anything else
    // (likely an MP4 / MKV container).
    if (find_start_code(bytes_, 0) != 0)
    {
        throw std::runtime_error("H264FileReader: " + path +
                                 " does not start with an Annex B start code "
                                 "(use ffmpeg -bsf:v h264_mp4toannexb to convert)");
    }
}

bool H264FileReader::next_nalu(const uint8_t** data, size_t* size)
{
    if (bytes_.empty())
    {
        return false;
    }
    if (cursor_ >= bytes_.size())
    {
        // Loop the stream so the demo plays continuously.
        cursor_ = 0;
        eof_ = true;
    }
    else
    {
        eof_ = false;
    }

    const size_t start = cursor_;
    const size_t next = find_start_code(bytes_, start + 3);
    *data = bytes_.data() + start;
    *size = next - start;
    cursor_ = next;
    return true;
}

} // namespace viz_smoke
