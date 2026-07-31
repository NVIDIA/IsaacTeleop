// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <schema/orbbec_camera_generated.h>

#include <cstdint>
#include <map>
#include <memory>
#include <vector>

namespace plugins::orbbec
{

struct PreviewFrame
{
    core::OrbbecCameraStream stream;
    core::OrbbecPixelFormat format;
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<uint8_t> encoded;
};

class Preview
{
public:
    Preview();
    ~Preview();
    Preview(const Preview&) = delete;
    Preview& operator=(const Preview&) = delete;

    void submit(PreviewFrame frame);
    bool closed() const;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace plugins::orbbec
