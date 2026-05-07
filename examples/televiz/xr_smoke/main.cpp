// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Minimal kXr demo. One 1024×1024 RGBA8 QuadLayer with an animated
// stripe pattern. Exits on runtime-requested session exit or Ctrl-C.
//
// Returns EXIT_SUCCESS only when xrCreateInstance fails (no runtime
// installed). Any other error is EXIT_FAILURE.

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
#include <optional>
#include <stdexcept>
#include <string>
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

// Stripe sweeps left→right so judder shows as stutter in its travel.
void fill_animated_pattern(std::vector<Rgba>& host, uint32_t w, uint32_t h, uint64_t frame_index)
{
    const uint32_t cycle_frames = 120; // ~2s at 60 Hz
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

bool parse_head_locked(int argc, char** argv)
{
    for (int i = 1; i < argc; ++i)
    {
        if (std::string_view(argv[i]) == "--head-locked")
        {
            return true;
        }
    }
    return false;
}

} // namespace

int main(int argc, char** argv)
{
    std::signal(SIGINT, on_signal);
    std::signal(SIGTERM, on_signal);

    // --head-locked: re-anchor placement to head pose each frame.
    // Default: world-locked at (0, 0, -1.5).
    bool head_locked = parse_head_locked(argc, argv);

    constexpr uint32_t kQuadW = 1024;
    constexpr uint32_t kQuadH = 1024;

    viz::VizSession::Config cfg{};
    cfg.mode = viz::DisplayMode::kXr;
    cfg.app_name = "viz_xr_smoke";
    // alpha=0 clear: on ALPHA_BLEND runtimes (passthrough), background
    // is transparent; on OPAQUE, ignored and reads as black.
    cfg.clear_color[0] = 0.0f;
    cfg.clear_color[1] = 0.0f;
    cfg.clear_color[2] = 0.0f;
    cfg.clear_color[3] = 0.0f;
    // Streaming runtimes (e.g. CloudXR) return FORM_FACTOR_UNAVAILABLE
    // until a headset client connects. -1 = wait forever (Ctrl-C breaks).
    cfg.xr_system_wait_seconds = -1;

    std::unique_ptr<viz::VizSession> session;
    try
    {
        session = viz::VizSession::create(cfg);
    }
    catch (const std::exception& e)
    {
        // The only "skip" case is the loader failing to create the
        // instance (no runtime installed). Discriminate by message —
        // the XR wrapper throws std::runtime_error for every failure.
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
        // 1 m × 1 m plane, 1.5 m forward (LOCAL space: -Z = forward).
        layer_cfg.placement = viz::QuadLayer::Config::Placement{
            viz::Pose3D{
                glm::vec3(0.0f, 0.0f, -1.5f),
                glm::quat(1.0f, 0.0f, 0.0f, 0.0f),
            },
            glm::vec2(1.0f, 1.0f),
        };
        auto* layer = session->add_layer<viz::QuadLayer>(*ctx, render_pass, layer_cfg);

        CudaDeviceBuffer device_buffer(static_cast<size_t>(kQuadW) * kQuadH * sizeof(Rgba));
        std::vector<Rgba> host_pattern(static_cast<size_t>(kQuadW) * kQuadH);

        // head_pose_now() needs XR_KHR_convert_timespec_time for the
        // steady_clock → XrTime conversion.
        if (head_locked && !session->has_xr_time_conversion())
        {
            std::fprintf(stderr,
                         "viz_xr_smoke: --head-locked requires XR_KHR_convert_timespec_time; "
                         "falling back to world-locked.\n");
            head_locked = false;
        }
        std::printf(
            "viz_xr_smoke: session up, awaiting runtime READY (%s)\n", head_locked ? "head-locked" : "world-locked");
        std::fflush(stdout);

        const auto start_time = std::chrono::steady_clock::now();
        bool announced_running = false;
        uint64_t loop_counter = 0;

        while (!g_stop.load(std::memory_order_acquire) && !session->should_close())
        {
            fill_animated_pattern(host_pattern, kQuadW, kQuadH, loop_counter);
            if (cudaMemcpy(device_buffer.ptr, host_pattern.data(), host_pattern.size() * sizeof(Rgba),
                           cudaMemcpyHostToDevice) != cudaSuccess)
            {
                throw std::runtime_error("cudaMemcpy(host->device) failed");
            }
            submit_pattern(*layer, device_buffer.ptr, kQuadW, kQuadH);
            ++loop_counter;

            // Anchor 1.5 m along head-forward (-Z). nullopt = tracking lost,
            // keep the previous placement.
            if (head_locked)
            {
                if (auto head = session->head_pose_now())
                {
                    const glm::vec3 forward = head->orientation * glm::vec3(0.0f, 0.0f, -1.5f);
                    viz::QuadLayer::Config::Placement placed;
                    placed.pose.position = head->position + forward;
                    placed.pose.orientation = head->orientation;
                    placed.size_meters = glm::vec2(1.0f, 1.0f);
                    layer->set_placement(placed);
                }
            }

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
