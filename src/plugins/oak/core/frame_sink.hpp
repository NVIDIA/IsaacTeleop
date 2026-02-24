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
 * @brief FrameMetadataOak-specific pusher that serializes and pushes frame metadata messages.
 *
 * Uses composition with SchemaPusher to handle the OpenXR tensor pushing.
 * Does not own the OpenXR session — the caller must keep it alive.
 */
class MetadataPusher
{
public:
    /**
     * @brief Construct the metadata pusher using an existing OpenXR session.
     * @param handles OpenXR session handles (caller must keep the session alive).
     * @param collection_id OpenXR tensor collection ID for metadata pushing.
     */
    MetadataPusher(const core::OpenXRSessionHandles& handles, const std::string& collection_id);

    /**
     * @brief Push a FrameMetadataOak message.
     * @param data The FrameMetadataOakT native object to serialize and push.
     * @throws std::runtime_error if the push fails.
     */
    void push(const core::FrameMetadataOakT& data);

private:
    static constexpr size_t MAX_FLATBUFFER_SIZE = 128;

    core::SchemaPusher m_pusher;
};

/**
 * @brief Multi-stream output sink for OAK frames.
 *
 * Owns one RawDataWriter and one MetadataPusher per configured stream,
 * sharing a single OpenXR session across all pushers.
 */
class FrameSink
{
public:
    FrameSink() = default;
    FrameSink(const FrameSink&) = delete;
    FrameSink& operator=(const FrameSink&) = delete;

    /**
     * @brief Register an output stream. Creates a RawDataWriter and, if metadata
     *        is enabled, a per-stream MetadataPusher.
     */
    void add_stream(StreamConfig config);

    /**
     * @brief Write raw frame data and push metadata for the corresponding stream.
     */
    void on_frame(const OakFrame& frame);

private:
    std::shared_ptr<core::OpenXRSession> m_oxr_session;
    std::map<core::StreamType, std::unique_ptr<RawDataWriter>> m_writers;
    std::map<core::StreamType, std::unique_ptr<MetadataPusher>> m_pushers;
};

} // namespace oak
} // namespace plugins
