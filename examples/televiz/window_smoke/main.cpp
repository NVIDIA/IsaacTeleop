// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Minimal kWindow demo: opens a 1024x768 GLFW window, fills four
// QuadLayers with solid RGBA patterns tiled 2x2, runs the render
// loop until the window closes.

#include <viz/core/vk_context.hpp>
#include <viz/layers/quad_layer.hpp>
#include <viz/session/viz_session.hpp>

#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cuda_runtime.h>
#include <memory>
#include <stdexcept>
#include <vector>

namespace
{

struct Rgba
{
    uint8_t r, g, b, a;
};

// RAII wrapper around a cudaMalloc'd buffer.
struct CudaDeviceBuffer
{
    void* ptr = nullptr;
    CudaDeviceBuffer() = default;
    explicit CudaDeviceBuffer(size_t bytes)
    {
        if (cudaMalloc(&ptr, bytes) != cudaSuccess)
        {
            ptr = nullptr;
            throw std::runtime_error("cudaMalloc failed");
        }
    }
    ~CudaDeviceBuffer()
    {
        if (ptr != nullptr)
        {
            cudaFree(ptr);
        }
    }
    CudaDeviceBuffer(const CudaDeviceBuffer&) = delete;
    CudaDeviceBuffer& operator=(const CudaDeviceBuffer&) = delete;
    CudaDeviceBuffer(CudaDeviceBuffer&& o) noexcept : ptr(o.ptr)
    {
        o.ptr = nullptr;
    }
    CudaDeviceBuffer& operator=(CudaDeviceBuffer&& o) noexcept
    {
        if (this != &o)
        {
            if (ptr != nullptr)
            {
                cudaFree(ptr);
            }
            ptr = o.ptr;
            o.ptr = nullptr;
        }
        return *this;
    }
};

CudaDeviceBuffer make_solid_color_buffer(uint32_t width, uint32_t height, Rgba color)
{
    std::vector<Rgba> host(static_cast<size_t>(width) * height, color);
    CudaDeviceBuffer buf(host.size() * sizeof(Rgba));
    if (cudaMemcpy(buf.ptr, host.data(), host.size() * sizeof(Rgba), cudaMemcpyHostToDevice) != cudaSuccess)
    {
        throw std::runtime_error("cudaMemcpy failed");
    }
    return buf;
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

    try
    {
        auto session = viz::VizSession::create(cfg);
        const viz::VkContext* ctx = session->get_vk_context();
        const VkRenderPass render_pass = session->get_render_pass();

        const std::array<Rgba, 4> palette = { {
            { 220, 60, 60, 255 }, // red
            { 60, 220, 60, 255 }, // green
            { 60, 100, 220, 255 }, // blue
            { 220, 220, 220, 255 }, // white
        } };

        // RAII: buffers freed on scope exit (normal or exception).
        // Outlive the session — submit() copies into the mailbox, so
        // the device pointers can be freed any time after.
        std::vector<CudaDeviceBuffer> device_buffers;
        device_buffers.reserve(palette.size());
        for (size_t i = 0; i < palette.size(); ++i)
        {
            viz::QuadLayer::Config layer_cfg;
            layer_cfg.name = "smoke_quad_" + std::to_string(i);
            layer_cfg.resolution = { kQuadW, kQuadH };
            auto* layer = session->add_layer<viz::QuadLayer>(*ctx, render_pass, layer_cfg);

            device_buffers.push_back(make_solid_color_buffer(kQuadW, kQuadH, palette[i]));
            submit_solid(*layer, device_buffers.back().ptr, kQuadW, kQuadH);
        }

        // Print fps once per second (60 frames at 60Hz) so resize /
        // move stalls show up as drops in the terminal output.
        while (!session->should_close())
        {
            const auto info = session->render();
            if (info.frame_index > 0 && info.frame_index % 60 == 0)
            {
                const auto stats = session->get_frame_timing_stats();
                std::printf("frame %llu: %.1f fps (%.2f ms/frame)\n", static_cast<unsigned long long>(info.frame_index),
                            stats.render_fps, stats.avg_frame_time_ms);
                std::fflush(stdout);
            }
        }

        session.reset(); // tear down before buffers go out of scope
    }
    catch (const std::exception& e)
    {
        std::fprintf(stderr, "viz_window_smoke: %s\n", e.what());
        return EXIT_FAILURE;
    }
    return EXIT_SUCCESS;
}
