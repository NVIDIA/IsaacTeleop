// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "oak_camera.hpp"
#include "rawdata_writer.hpp"

#include <oxr/oxr_session.hpp>
#include <pusherio/schema_pusher.hpp>
#include <schema/oak_generated.h>

#include <map>
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
 * @brief Multi-stream output sink for OAK frames.
 *
 * Owns one RawDataWriter per configured stream and a single MetadataPusher.
 * on_frame() writes raw data to disk and pushes metadata per frame.
 */
class FrameSink
{
public:
    /**
     * @param collection_id OpenXR tensor collection ID for metadata pushing.
     *                      If empty, metadata pushing is disabled.
     */
    explicit FrameSink(const std::string& collection_id = "");

    FrameSink(const FrameSink&) = delete;
    FrameSink& operator=(const FrameSink&) = delete;

    /**
     * @brief Register an output stream. Creates a RawDataWriter for the given path.
     */
    void add_stream(core::StreamType type, const std::string& output_path);

    /**
     * @brief Write raw frame data and push metadata.
     */
    void on_frame(const OakFrame& frame);

private:
    std::map<core::StreamType, std::unique_ptr<RawDataWriter>> m_writers;
    std::unique_ptr<MetadataPusher> m_pusher;
};

} // namespace oak
} // namespace plugins
