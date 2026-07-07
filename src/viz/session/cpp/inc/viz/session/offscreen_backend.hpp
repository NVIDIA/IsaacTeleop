// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "display_backend.hpp"

#include <memory>

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
    uint32_t image_count() const override
    {
        return 1;
    }

    // Direct-present: copy a ProjectionLayer's color image into the RT's
    // color attachment (leaving it in TRANSFER_SRC) so readback_to_host
    // works unchanged. Depth isn't read back. Empty views → clear.
    bool supports_direct() const noexcept override
    {
        return true;
    }
    void record_direct(VkCommandBuffer cmd, const Frame& frame, const std::vector<DirectPresentView>& views) override;

    // Synchronous tightly-packed RGBA8 copy of the RT's color attachment.
    HostImage readback_to_host() override;

    void destroy();

private:
    void create_readback_staging();
    void destroy_readback_staging();

    const VkContext* ctx_ = nullptr;
    Resolution extent_{};
    std::unique_ptr<RenderTarget> render_target_;

    // Pre-allocated; reused per readback.
    VkBuffer readback_buffer_ = VK_NULL_HANDLE;
    VkDeviceMemory readback_memory_ = VK_NULL_HANDLE;
    VkDeviceSize readback_byte_size_ = 0;

    // Dedicated cmd buffer so readback never races the compositor's.
    VkCommandPool readback_command_pool_ = VK_NULL_HANDLE;
    VkCommandBuffer readback_command_buffer_ = VK_NULL_HANDLE;
};

} // namespace viz
