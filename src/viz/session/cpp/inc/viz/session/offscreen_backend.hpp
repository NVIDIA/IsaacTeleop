// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/vk.hpp>
#include <viz/session/display_backend.hpp>

#include <memory>
#include <optional>

namespace viz
{

// Renders into an intermediate RT; readback_to_host copies it to a
// host-visible buffer on demand. No present, no events.
class OffscreenBackend final : public DisplayBackend
{
public:
    OffscreenBackend();
    ~OffscreenBackend() override;

    void init(const VkContext& ctx, Resolution preferred_size) override;

    std::optional<Frame> begin_frame(int64_t predicted_display_time) override;
    const RenderTarget& render_target() const override;

    Resolution current_extent() const override;

    // Synchronous tightly-packed RGBA8 copy of the RT's color attachment.
    HostImage readback_to_host() override;

    void destroy();

private:
    void create_readback_staging();

    const VkContext* ctx_ = nullptr;
    Resolution extent_{};
    std::unique_ptr<RenderTarget> render_target_;

    // Pre-allocated; reused per readback. Declared parent-first so
    // reverse-destruction is correct (memory after buffer/pool).
    vk::raii::DeviceMemory readback_memory_{ nullptr };
    vk::raii::Buffer readback_buffer_{ nullptr };
    VkDeviceSize readback_byte_size_ = 0;

    // Dedicated cmd buffer so readback never races the compositor's.
    vk::raii::CommandPool readback_command_pool_{ nullptr };
    // Wrapped in std::optional — older vulkan-hpp SDKs lack the
    // nullptr ctor on the vector-style raii types.
    std::optional<vk::raii::CommandBuffers> readback_command_buffers_;
};

} // namespace viz
