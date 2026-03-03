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
 * Owns the full lifecycle: requests a preview output from an existing Camera
 * node on CAM_A, opens an SDL2 window, and polls/displays frames.
 */
class PreviewStream
{
public:
    ~PreviewStream();

    PreviewStream(const PreviewStream&) = delete;
    PreviewStream& operator=(const PreviewStream&) = delete;

    /**
     * @brief Wire a preview output into an existing pipeline and create the window.
     *
     * Searches the pipeline for an existing Camera node on CAM_A. If none is
     * found, creates and builds one. Requests a small BGR output for preview
     * and creates the output queue internally.
     *
     * @throws std::runtime_error if no CAM_A node exists and creation fails,
     *         or if SDL initialisation / window creation fails.
     */
    static std::unique_ptr<PreviewStream> create(const std::string& name, dai::Pipeline& pipeline);

    /** @brief Poll the queue and display a frame if available. */
    void update();

private:
    PreviewStream() = default;

    struct Impl;
    std::unique_ptr<Impl> m_impl;
};

} // namespace oak
} // namespace plugins
