// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Minimal kXr demo: opens an OpenXR session against whatever runtime
// is on the host (CloudXR / Monado / SteamVR), pushes a single 1024x1024
// RGBA8 QuadLayer fed by a CUDA producer that animates a gradient with
// a moving stripe each frame. Renders mono content; the runtime
// duplicates it across both eyes via two ProjectionViews built by
// XrBackend::end_frame.
//
// Run as: ./viz_xr_smoke
// Exits cleanly when the runtime asks the session to exit (user removes
// HMD, runtime sends LOSS_PENDING, etc.) or on Ctrl-C.
//
// Bails out with EXIT_SUCCESS only when no OpenXR runtime is configured
// on the host (xrCreateInstance fails). Any other failure during session
// creation — Vulkan setup, session/swapchain errors, programming bugs —
// returns EXIT_FAILURE so real problems surface during development.

#include <viz/core/vk_context.hpp>
#include <viz/layers/quad_layer.hpp>
#include <viz/session/viz_session.hpp>

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cuda_runtime.h>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace
{

struct Rgba
{
    uint8_t r, g, b, a;
};

struct CudaDeviceBuffer
{
    void* ptr = nullptr;
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
};

// Gradient + an animated vertical stripe. The stripe sweeps left→right
// each frame so a human watching the headset gets an obvious motion
// reference for smoothness — judder shows up immediately as a stutter
// in the stripe's travel. Re-filled host-side every frame; cost is
// trivial for 1024×1024 RGBA8.
void fill_animated_pattern(std::vector<Rgba>& host, uint32_t w, uint32_t h, uint64_t frame_index)
{
    // ~2 second cycle at 60 Hz (120 frames per sweep). Modulate stripe
    // position; everything else stays put so the gradient anchors the eye.
    const uint32_t cycle_frames = 120;
    const uint32_t stripe_center = static_cast<uint32_t>((frame_index % cycle_frames) * w / cycle_frames);
    const uint32_t stripe_half = w / 64;
    for (uint32_t y = 0; y < h; ++y)
    {
        for (uint32_t x = 0; x < w; ++x)
        {
            const uint8_t r = static_cast<uint8_t>((x * 255u) / w);
            const uint8_t g = static_cast<uint8_t>((y * 255u) / h);
            const uint8_t b = 64;
            const bool in_stripe =
                x + stripe_half >= stripe_center && x < stripe_center + stripe_half && stripe_center >= stripe_half;
            host[y * w + x] = in_stripe ? Rgba{ 255, 255, 255, 255 } : Rgba{ r, g, b, 255 };
        }
    }
}

void submit_pattern(viz::QuadLayer& layer, void* dev_ptr, uint32_t w, uint32_t h)
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

std::atomic<bool> g_stop{ false };
void on_signal(int)
{
    g_stop.store(true, std::memory_order_release);
}

} // namespace

int main()
{
    std::signal(SIGINT, on_signal);
    std::signal(SIGTERM, on_signal);

    constexpr uint32_t kQuadW = 1024;
    constexpr uint32_t kQuadH = 1024;

    viz::VizSession::Config cfg{};
    cfg.mode = viz::DisplayMode::kXr;
    cfg.app_name = "viz_xr_smoke";
    // Fully transparent background. On a passthrough-capable runtime
    // (env blend mode = ALPHA_BLEND), the camera feed shows through
    // wherever we write alpha=0 — the placed quad writes alpha=1
    // inside its geometry, everything else stays at the clear color's
    // alpha=0. On a pure-VR runtime (OPAQUE), alpha is ignored and
    // background reads as black; the quad still renders correctly.
    cfg.clear_color[0] = 0.0f;
    cfg.clear_color[1] = 0.0f;
    cfg.clear_color[2] = 0.0f;
    cfg.clear_color[3] = 0.0f;
    // CloudXR / streaming runtimes return XR_ERROR_FORM_FACTOR_UNAVAILABLE
    // until a headset client connects. Negative = wait forever — start
    // this binary, then connect the CloudXR client at any time. Ctrl-C
    // breaks the wait.
    cfg.xr_system_wait_seconds = -1;

    std::unique_ptr<viz::VizSession> session;
    try
    {
        session = viz::VizSession::create(cfg);
    }
    catch (const std::exception& e)
    {
        // The XR wrapper raises std::runtime_error for every failure, so
        // we discriminate by message. The ONLY case that legitimately
        // means "skip this run" is the OpenXR loader failing to create
        // an instance (no runtime configured on the host) — message
        // signature "xrCreateInstance failed". Everything else (Vulkan
        // setup, session creation, validation layer asserts, programming
        // errors) is a real failure that should not be silenced.
        const std::string_view msg(e.what());
        const bool no_runtime = msg.find("xrCreateInstance failed") != std::string_view::npos;
        if (no_runtime)
        {
            std::fprintf(stderr,
                         "viz_xr_smoke: no OpenXR runtime reachable (%s). Skipping (expected on dev "
                         "machines without an OpenXR loader).\n",
                         e.what());
            return EXIT_SUCCESS;
        }
        std::fprintf(stderr, "viz_xr_smoke: VizSession::create failed: %s\n", e.what());
        return EXIT_FAILURE;
    }

    try
    {
        const viz::VkContext* ctx = session->get_vk_context();
        const VkRenderPass render_pass = session->get_render_pass();

        viz::QuadLayer::Config layer_cfg;
        layer_cfg.name = "xr_smoke_quad";
        layer_cfg.resolution = { kQuadW, kQuadH };
        // 3D placement: 1.0 m wide square plane, 1.5 m in front of the
        // origin (OpenXR LOCAL space: forward = -Z). With this set, the
        // quad renders as a real plane in space — the user can lean
        // around it, walk closer, etc. In window/offscreen modes the
        // QuadLayer falls back to fullscreen rendering when its session
        // isn't kXr.
        layer_cfg.placement_pose = viz::Pose3D{
            glm::vec3(0.0f, 0.0f, -1.5f), // 1.5 m forward
            glm::quat(1.0f, 0.0f, 0.0f, 0.0f), // identity orientation (facing toward viewer)
        };
        layer_cfg.placement_size_meters = glm::vec2(1.0f, 1.0f);
        auto* layer = session->add_layer<viz::QuadLayer>(*ctx, render_pass, layer_cfg);

        CudaDeviceBuffer device_buffer(static_cast<size_t>(kQuadW) * kQuadH * sizeof(Rgba));
        std::vector<Rgba> host_pattern(static_cast<size_t>(kQuadW) * kQuadH);

        std::printf("viz_xr_smoke: session up, awaiting runtime READY...\n");
        std::fflush(stdout);

        const auto start_time = std::chrono::steady_clock::now();
        bool announced_running = false;
        uint64_t loop_counter = 0;

        while (!g_stop.load(std::memory_order_acquire) && !session->should_close())
        {
            // Re-fill + re-submit each frame so the stripe animates.
            // Cheap: 4 MB H2D + 4 MB on-CPU fill at 60 Hz. The stripe
            // motion is the smoothness gauge — judder shows up as a
            // stutter in its sweep across the quad.
            fill_animated_pattern(host_pattern, kQuadW, kQuadH, loop_counter);
            if (cudaMemcpy(device_buffer.ptr, host_pattern.data(), host_pattern.size() * sizeof(Rgba),
                           cudaMemcpyHostToDevice) != cudaSuccess)
            {
                throw std::runtime_error("cudaMemcpy(host->device) failed");
            }
            submit_pattern(*layer, device_buffer.ptr, kQuadW, kQuadH);
            ++loop_counter;

            const auto info = session->begin_frame();
            session->end_frame();

            if (!announced_running && info.frame_index > 0)
            {
                std::printf("viz_xr_smoke: rendering...\n");
                std::fflush(stdout);
                announced_running = true;
            }
            if (info.frame_index > 0 && info.frame_index % 60 == 0)
            {
                const auto stats = session->get_frame_timing_stats();
                std::printf("frame %llu: %.1f fps (%.2f ms/frame)\n", static_cast<unsigned long long>(info.frame_index),
                            stats.render_fps, stats.avg_frame_time_ms);
                std::fflush(stdout);
            }
        }

        const auto elapsed = std::chrono::duration<float>(std::chrono::steady_clock::now() - start_time).count();
        std::printf("viz_xr_smoke: exit after %.1fs\n", elapsed);
        session.reset();
    }
    catch (const std::exception& e)
    {
        std::fprintf(stderr, "viz_xr_smoke: %s\n", e.what());
        return EXIT_FAILURE;
    }
    return EXIT_SUCCESS;
}
