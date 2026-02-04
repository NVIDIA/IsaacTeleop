// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "camera_interface.hpp"
#include "rawdata_writer.hpp"

#include <oxr/oxr_session.hpp>
#include <pusherio/schema_pusher.hpp>

#include <atomic>
#include <chrono>
#include <functional>
#include <memory>
#include <string>

namespace core
{

/**
 * @brief Factory function type for creating camera instances
 */
using CameraFactory = std::function<std::unique_ptr<ICamera>(const CameraConfig&)>;

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
     * @brief Factory method to create a FrameMetadataPusher.
     * @param app_name Application name for the OpenXR session.
     * @param collection_id Tensor collection identifier for discovery.
     * @param max_flatbuffer_size Maximum serialized message size (default: 128 bytes).
     * @return unique_ptr to FrameMetadataPusher, or nullptr on failure.
     */
    static std::unique_ptr<FrameMetadataPusher> Create(const std::string& app_name,
                                                       const std::string& collection_id,
                                                       size_t max_flatbuffer_size = DEFAULT_MAX_FLATBUFFER_SIZE);

    /**
     * @brief Push a FrameMetadata message.
     * @param data The FrameMetadataT native object to serialize and push.
     * @return true on success, false on failure.
     */
    bool push(const FrameMetadataT& data);

private:
    /**
     * @brief Private constructor - use Create() factory method.
     */
    FrameMetadataPusher(std::shared_ptr<OpenXRSession> session,
                        const std::string& collection_id,
                        size_t max_flatbuffer_size);

    //! Owns the OpenXR session to keep handles valid
    std::shared_ptr<OpenXRSession> m_session;

    //! The underlying schema pusher (composition)
    std::unique_ptr<SchemaPusher> m_pusher;
};

/**
 * @brief Main plugin class for camera recording
 *
 * Coordinates camera capture with file recording.
 * Optionally integrates with OpenXR for CloudXR integration.
 * Camera implementation is injected via a factory function.
 */
class CameraPlugin
{
public:
    /**
     * @brief Construct the camera plugin
     * @param camera_factory Factory function to create cameras
     * @param camera_config Camera configuration
     * @param record_config Recording configuration
     * @param plugin_root_id Root identifier used for OpenXR tensor collection naming
     */
    CameraPlugin(CameraFactory camera_factory,
                 const CameraConfig& camera_config,
                 const RecordConfig& record_config,
                 const std::string& plugin_root_id);

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
    void init_metadata_pusher();

    // Components
    std::unique_ptr<ICamera> m_camera;
    std::unique_ptr<RawDataWriter> m_writer;
    std::unique_ptr<FrameMetadataPusher> m_metadata_pusher;

    // Configuration
    std::string m_collection_id;

    // State
    std::atomic<bool> m_stop_requested{ false };

    // Statistics
    uint64_t m_frame_count = 0;
    std::chrono::steady_clock::time_point m_start_time;
};

} // namespace core
