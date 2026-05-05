// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// window_smoke: minimal Televiz kWindow demo. Opens a 1024x768 GLFW
// window, fills four QuadLayers with solid RGBA patterns, tiles them
// in a 2x2 aspect-preserving grid, runs the render loop until the
// window is closed.
//
// Mirrors the camera_streamer monitor mode (HolovizOp tiling) on a
// Holoscan-free path. No Holoscan, no HoloHub, no GXF.

#include <viz/core/vk_context.hpp>
#include <viz/layers/quad_layer.hpp>
#include <viz/session/viz_session.hpp>

#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <vector>

#include <cuda_runtime.h>

namespace
{

struct Rgba
{
    uint8_t r, g, b, a;
};

// Allocates a CUDA device buffer filled with a solid RGBA color.
// Returned pointer is owned by the caller; cudaFree it when done.
void* make_solid_color_buffer(uint32_t width, uint32_t height, Rgba color)
{
    std::vector<Rgba> host(static_cast<size_t>(width) * height, color);
    void* dev = nullptr;
    if (cudaMalloc(&dev, host.size() * sizeof(Rgba)) != cudaSuccess)
    {
        throw std::runtime_error("cudaMalloc failed");
    }
    if (cudaMemcpy(dev, host.data(), host.size() * sizeof(Rgba), cudaMemcpyHostToDevice) != cudaSuccess)
    {
        cudaFree(dev);
        throw std::runtime_error("cudaMemcpy failed");
    }
    return dev;
}

void submit_solid(viz::QuadLayer& layer, void* dev_ptr, uint32_t w, uint32_t h)
{
    viz::VizBuffer src{};
    src.data = dev_ptr;
    src.width = w;
    src.height = h;
    src.format = viz::PixelFormat::kRGBA8;
    src.pitch = static_cast<size_t>(w) * 4;
    src.space = viz::MemorySpace::kDevice;
    layer.submit(src);
}

} // namespace

int main()
{
    constexpr uint32_t kWindowW = 1024;
    constexpr uint32_t kWindowH = 768;
    constexpr uint32_t kQuadW = 256;
    constexpr uint32_t kQuadH = 256;

    viz::VizSession::Config cfg{};
    cfg.mode = viz::DisplayMode::kWindow;
    cfg.window_width = kWindowW;
    cfg.window_height = kWindowH;
    cfg.app_name = "viz_window_smoke";
    // Dark grey clear so letterbox margins are visible against the quads.
    cfg.clear_color[0] = 0.1f;
    cfg.clear_color[1] = 0.1f;
    cfg.clear_color[2] = 0.1f;
    cfg.clear_color[3] = 1.0f;

    std::unique_ptr<viz::VizSession> session;
    try
    {
        session = viz::VizSession::create(cfg);
    }
    catch (const std::exception& e)
    {
        std::fprintf(stderr, "VizSession::create failed: %s\n", e.what());
        return EXIT_FAILURE;
    }

    const viz::VkContext* ctx = session->get_vk_context();
    const VkRenderPass render_pass = session->get_render_pass();

    // Four QuadLayers, one per palette entry. Each is a 256x256 solid
    // color CUDA texture; the compositor tiles them 2x2 in the window.
    const std::array<Rgba, 4> palette = { {
        { 220, 60, 60, 255 }, // red
        { 60, 220, 60, 255 }, // green
        { 60, 100, 220, 255 }, // blue
        { 220, 220, 220, 255 }, // white
    } };

    std::vector<void*> device_buffers;
    device_buffers.reserve(palette.size());
    for (size_t i = 0; i < palette.size(); ++i)
    {
        viz::QuadLayer::Config layer_cfg;
        layer_cfg.name = "smoke_quad_" + std::to_string(i);
        layer_cfg.resolution = { kQuadW, kQuadH };
        auto* layer = session->add_layer<viz::QuadLayer>(*ctx, render_pass, layer_cfg);

        void* dev = make_solid_color_buffer(kQuadW, kQuadH, palette[i]);
        device_buffers.push_back(dev);
        submit_solid(*layer, dev, kQuadW, kQuadH);
    }

    // Run until the user closes the window.
    while (!session->should_close())
    {
        session->render();
    }

    // Tear down the session before freeing CUDA buffers — the layers
    // hold no references to the user-owned device pointers (submit()
    // copies into the layer's mailbox), but draining the device on
    // session destroy keeps the order clean.
    session.reset();
    for (void* dev : device_buffers)
    {
        cudaFree(dev);
    }
    return EXIT_SUCCESS;
}
