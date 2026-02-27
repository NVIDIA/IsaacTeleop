// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <depthai/depthai.hpp>

#include <memory>
#include <string>

namespace plugins
{
namespace oak
{

/**
 * @brief Self-contained color preview stream.
 *
 * Owns the full lifecycle: adds preview nodes to the pipeline, opens an SDL2
 * window, connects to the device output queue, and polls/displays frames.
 */
class PreviewStream
{
public:
    ~PreviewStream();

    PreviewStream(const PreviewStream&) = delete;
    PreviewStream& operator=(const PreviewStream&) = delete;

    /**
     * @brief Wire preview nodes into an existing pipeline and create the window.
     *
     * Searches the pipeline for an existing ColorCamera on CAM_A. If none is
     * found, creates and configures one. Then attaches preview output nodes.
     *
     * @return A valid PreviewStream, or nullptr if the SDL window could not be created.
     */
    static std::unique_ptr<PreviewStream> try_create(const std::string& name,
                                                     dai::Pipeline& pipeline,
                                                     dai::ColorCameraProperties::SensorResolution resolution);

    /** @brief Set the output queue to poll frames from. Call after Device::startPipeline. */
    void setOutputQueue(std::shared_ptr<dai::DataOutputQueue> queue);

    /** @brief Poll the queue and display a frame if available. */
    void update();

private:
    PreviewStream() = default;

    struct Impl;
    std::unique_ptr<Impl> m_impl;
};

} // namespace oak
} // namespace plugins
