// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "oak_camera.hpp"
#include "rawdata_writer.hpp"

#include <memory>
#include <string>

// Forward declarations to avoid leaking heavy headers
namespace core
{
class OpenXRSession;
class SchemaPusher;
} // namespace core

namespace plugins
{
namespace oak
{

/**
 * @brief Combined output sink for OAK frames.
 *
 * Writes raw H.264 data to a file via RawDataWriter and optionally pushes
 * frame metadata (timestamp + sequence number) via OpenXR tensor extensions.
 *
 * RAII: resources are acquired in constructor and released in destructor.
 */
class FrameSink
{
public:
    /**
     * @brief Construct the frame sink.
     * @param record_dir Directory for auto-named H.264 recordings.
     *                   A timestamped filename is generated automatically.
     * @param collection_id OpenXR tensor collection ID for metadata pushing.
     *                      If empty, metadata pushing is disabled.
     * @throws std::runtime_error if the directory cannot be created or file cannot be opened.
     */
    FrameSink(const std::string& record_dir, const std::string& collection_id = "");
    ~FrameSink();

    // Non-copyable, non-movable
    FrameSink(const FrameSink&) = delete;
    FrameSink& operator=(const FrameSink&) = delete;

    /**
     * @brief Process a frame: writes H.264 data to file and pushes metadata via OpenXR.
     */
    void on_frame(const OakFrame& frame);

private:
    RawDataWriter m_writer;

    // Optional OpenXR metadata pusher (pimpl to keep heavy headers out of this header)
    struct MetadataPusher;
    std::unique_ptr<MetadataPusher> m_pusher;
};

} // namespace oak
} // namespace plugins
