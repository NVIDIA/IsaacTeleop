// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "oak_camera.hpp"
#include "rawdata_writer.hpp"

#include <oxr/oxr_session.hpp>
#include <pusherio/schema_pusher.hpp>
#include <schema/oak_generated.h>

#include <memory>
#include <string>

namespace plugins
{
namespace oak
{

/**
 * @brief FrameMetadata-specific pusher that serializes and pushes frame metadata messages.
 *
 * Uses composition with SchemaPusher to handle the OpenXR tensor pushing.
 */
class MetadataPusher
{
public:
    /**
     * @brief Construct the metadata pusher.
     * @param collection_id OpenXR tensor collection ID for metadata pushing.
     */
    MetadataPusher(const std::string& collection_id);

    /**
     * @brief Push a FrameMetadata message.
     * @param data The FrameMetadataT native object to serialize and push.
     * @throws std::runtime_error if the push fails.
     */
    void push(const core::FrameMetadataT& data);

private:
    static constexpr size_t MAX_FLATBUFFER_SIZE = 128;

    std::shared_ptr<core::OpenXRSession> m_session;
    core::SchemaPusher m_pusher;
};

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
     * @param record_path Full path to the output H.264 recording file.
     * @param collection_id OpenXR tensor collection ID for metadata pushing.
     *                      If empty, metadata pushing is disabled.
     * @throws std::runtime_error if the parent directory cannot be created or file cannot be opened.
     */
    FrameSink(const std::string& record_path, const std::string& collection_id = "");

    // Non-copyable, non-movable
    FrameSink(const FrameSink&) = delete;
    FrameSink& operator=(const FrameSink&) = delete;

    /**
     * @brief Process a frame: writes H.264 data to file and pushes metadata via OpenXR.
     */
    void on_frame(const OakFrame& frame);

private:
    RawDataWriter m_writer;

    // Optional OpenXR metadata pusher
    std::unique_ptr<MetadataPusher> m_pusher;
};

} // namespace oak
} // namespace plugins
