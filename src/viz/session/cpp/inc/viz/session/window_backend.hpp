// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/session/display_backend.hpp>

#include <chrono>
#include <cstdint>
#include <memory>
#include <string>

namespace viz
{

class GlfwWindow;
class Swapchain;

// GLFW window + Vulkan swapchain. record_post_render_pass blits the
// intermediate RT to the swapchain image; end_frame presents.
class WindowBackend final : public DisplayBackend
{
public:
    struct Config
    {
        uint32_t width = 1024;
        uint32_t height = 1024;
        std::string title = "televiz";
        // Soft fps cap; 0 = primary monitor's refresh rate.
        uint32_t target_fps = 0;
    };

    explicit WindowBackend(Config config);
    ~WindowBackend() override;

    std::vector<std::string> required_instance_extensions() const override;
    std::vector<std::string> required_device_extensions() const override;
    void init(const VkContext& ctx, Resolution preferred_size) override;

    std::optional<Frame> begin_frame(int64_t predicted_display_time) override;
    const RenderTarget& render_target() const override;
    void record_post_render_pass(VkCommandBuffer cmd, const Frame& frame) override;
    void end_frame(const Frame& frame) override;
    void abort_frame(const Frame& frame) override;

    void poll_events() override;
    bool should_close() const override;
    bool consume_resized() override;
    void resize(Resolution new_size) override;
    Resolution current_extent() const override;

    void destroy();

private:
    Config config_;
    const VkContext* ctx_ = nullptr;

    std::unique_ptr<GlfwWindow> window_;
    std::unique_ptr<Swapchain> swapchain_;
    std::unique_ptr<RenderTarget> render_target_;

    // MAILBOX doesn't throttle acquire; the pacer at begin_frame's
    // start caps render rate (and runs even on OUT_OF_DATE early-out
    // so the loop can't spin).
    std::chrono::nanoseconds frame_period_{ 0 };
    std::chrono::steady_clock::time_point next_frame_deadline_{};

    // Set by abort_frame and by acquire-time OUT_OF_DATE; consumed
    // at the top of the next begin_frame, which forces a swapchain
    // recreate before doing anything else.
    bool needs_recreate_ = false;

    // Recreate swapchain + RT at the current window framebuffer size.
    // Skips the size-match check that resize() applies, because
    // OUT_OF_DATE fires for non-size reasons too (monitor reconfig,
    // format change). Returns false if the recreate cannot run (e.g.
    // minimized window) so the caller can keep the dirty flag set.
    bool force_recreate();
};

} // namespace viz
