// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "camera_interface.hpp"
#include "rawdata_writer.hpp"

#include <oxr/oxr_session.hpp>
#include <pusherio/schema_pusher.hpp>

#include <atomic>
#include <chrono>
#include <memory>
#include <string>

namespace core
{

/**
 * @brief FrameMetadata-specific pusher that serializes and pushes camera frame metadata.
 *
 * This class creates its own OpenXR session and uses SchemaPusher via composition to provide
 * typed push functionality for FrameMetadata FlatBuffer messages from camera.fbs.
 */
class FrameMetadataPusher
{
public:
    //! Default maximum FlatBuffer size for FrameMetadata (timestamp + sequence number)
    static constexpr size_t DEFAULT_MAX_FLATBUFFER_SIZE = 128;

    /**
     * @brief Construct a FrameMetadataPusher.
     * @param app_name Application name for the OpenXR session.
     * @param collection_id Tensor collection identifier for discovery.
     * @param max_flatbuffer_size Maximum serialized message size (default: 128 bytes).
     */
    FrameMetadataPusher(const std::string& app_name,
                        const std::string& collection_id,
                        size_t max_flatbuffer_size = DEFAULT_MAX_FLATBUFFER_SIZE);

    /**
     * @brief Push a FrameMetadata message.
     * @param data The FrameMetadataT native object to serialize and push.
     */
    void push(const FrameMetadataT& data);

private:
    //! Owns the OpenXR session to keep handles valid
    std::shared_ptr<OpenXRSession> m_session;

    //! The underlying schema pusher (composition)
    SchemaPusher m_pusher;
};

/**
 * @brief Main plugin class for camera recording
 *
 * Coordinates camera capture with file recording.
 * Optionally integrates with OpenXR for CloudXR integration.
 * Takes ownership of an ICamera instance.
 */
class CameraPlugin
{
public:
    /**
     * @brief Construct the camera plugin
     * @param camera Camera instance (plugin takes ownership)
     * @param record_config Recording configuration
     * @param collection_id Optional tensor collection ID for frame metadata; if provided, enables metadata pushing via
     * OpenXR
     */
    CameraPlugin(std::unique_ptr<ICamera> camera, const RecordConfig& record_config, std::string collection_id = "");

    ~CameraPlugin();

    // Non-copyable, non-movable
    CameraPlugin(const CameraPlugin&) = delete;
    CameraPlugin& operator=(const CameraPlugin&) = delete;
    CameraPlugin(CameraPlugin&&) = delete;
    CameraPlugin& operator=(CameraPlugin&&) = delete;

    /**
     * @brief Run the capture loop (blocks until request_stop is called)
     */
    void capture_loop();

    /**
     * @brief Request the plugin to stop (signal-safe)
     */
    void request_stop();

    /**
     * @brief Get frame count
     */
    uint64_t frame_count() const
    {
        return m_frame_count;
    }

private:
    // Components
    std::unique_ptr<ICamera> m_camera;
    std::unique_ptr<RawDataWriter> m_writer;
    std::unique_ptr<FrameMetadataPusher> m_metadata_pusher;

    // State
    std::atomic<bool> m_stop_requested{ false };

    // Statistics
    uint64_t m_frame_count = 0;
    std::chrono::steady_clock::time_point m_start_time;
};

} // namespace core
