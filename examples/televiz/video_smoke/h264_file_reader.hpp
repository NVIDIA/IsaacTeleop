// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstddef>
#include <cstdint>
#include <fstream>
#include <string>
#include <vector>

namespace viz_smoke
{

// Reads an Annex B H.264 elementary stream and returns one NAL unit
// (start-code-prefixed) per next_nalu() call. Loops back to file
// start on EOF. Convert MP4/MKV to .h264 with:
//   ffmpeg -i in.mp4 -c:v copy -bsf:v h264_mp4toannexb -f h264 out.h264
class H264FileReader
{
public:
    explicit H264FileReader(const std::string& path);

    // Returns a span into the internal buffer. The span includes the
    // leading start code (00 00 00 01 or 00 00 01) so the result can
    // be fed directly into NvDecoder::Decode.
    bool next_nalu(const uint8_t** data, size_t* size);

    bool eof() const noexcept
    {
        return eof_;
    }

private:
    void load_file(const std::string& path);

    std::vector<uint8_t> bytes_;
    size_t cursor_ = 0;
    bool eof_ = false;
};

} // namespace viz_smoke
