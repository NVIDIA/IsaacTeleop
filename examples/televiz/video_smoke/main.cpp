// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Plays one or more H.264 files into a Televiz window. Multiple inputs
// tile row-major (compositor's tile_layout handles aspect-fit):
//   ./viz_video_smoke /path/to/a.h264 [/path/to/b.h264 ...]

#include "nvdec_player.hpp"

#include <viz/core/vk_context.hpp>
#include <viz/layers/quad_layer.hpp>
#include <viz/session/viz_session.hpp>

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <memory>
#include <string>
#include <thread>
#include <vector>

namespace
{

struct Video
{
    std::string path;
    // Heap-allocated because NvdecPlayer's CUDA device id isn't
    // known until after VizSession is created (multi-GPU systems
    // require matching the Vulkan-chosen device). The player owns
    // its own worker thread that reads the file + decodes; main
    // only needs try_pop().
    std::unique_ptr<viz_smoke::NvdecPlayer> player;
    viz::QuadLayer* layer = nullptr;
    // Most recently submitted frame; held alive across one render cycle
    // so QuadLayer::submit's async cudaMemcpy can complete before the
    // ~DecodedFrame cudaFree.
    std::unique_ptr<viz_smoke::DecodedFrame> in_flight;
    // First decoded frame, captured during prime() before the session
    // exists. Submitted on the first render iteration.
    std::unique_ptr<viz_smoke::DecodedFrame> first_frame;
    // Presentation pacing: only pop a new frame from the player's
    // queue when the source's frame period has elapsed. Prevents
    // 25 fps content from playing back at 60 fps just because the
    // window backend is rendering at monitor refresh.
    std::chrono::nanoseconds frame_period{ 0 };
    std::chrono::steady_clock::time_point next_present{};
};

void submit_to_layer(viz::QuadLayer& layer, const viz_smoke::DecodedFrame& f, cudaStream_t stream)
{
    viz::VizBuffer src{};
    src.data = f.data;
    src.width = f.width;
    src.height = f.height;
    src.format = viz::PixelFormat::kRGBA8;
    src.pitch = static_cast<size_t>(f.width) * 4;
    src.space = viz::MemorySpace::kDevice;
    layer.submit(src, stream);
}

} // namespace

int main(int argc, char** argv)
{
    float lod_bias = 0.0f;
    bool static_mode = false;
    std::vector<const char*> paths;
    for (int i = 1; i < argc; ++i)
    {
        const std::string a = argv[i];
        const std::string lod_prefix = "--lod-bias=";
        if (a.rfind(lod_prefix, 0) == 0)
        {
            lod_bias = std::stof(a.substr(lod_prefix.size()));
        }
        else if (a == "--static")
        {
            static_mode = true;
        }
        else
        {
            paths.push_back(argv[i]);
        }
    }
    if (paths.empty())
    {
        std::fprintf(stderr,
                     "usage: %s [--lod-bias=N] [--static] <video.h264> [<video.h264> ...]\n"
                     "  --lod-bias=N : sampler mipLodBias (default 0). Positive values\n"
                     "                 bias toward blurrier mip levels — try 0.5..1.5\n"
                     "                 to reduce shimmer on fine detail.\n"
                     "  --static     : decode only the first frame of each input, then\n"
                     "                 reuse it for the rest of the run. Isolates\n"
                     "                 Televiz render cost from NVDEC + color-convert\n"
                     "                 cost when stress-testing tile counts.\n"
                     "  Inputs must be raw H.264 Annex B. To convert from MP4:\n"
                     "    ffmpeg -i in.mp4 -c:v copy -bsf:v h264_mp4toannexb -f h264 out.h264\n",
                     argv[0]);
        return EXIT_FAILURE;
    }

    try
    {
        std::vector<std::unique_ptr<Video>> videos;
        videos.reserve(paths.size());
        for (const char* p : paths)
        {
            auto v = std::make_unique<Video>();
            v->path = p;
            videos.push_back(std::move(v));
        }
        std::printf("lod_bias = %.2f, static = %d\n", lod_bias, static_mode ? 1 : 0);

        // Open the window first so we can read VkContext::cuda_device_id
        // and use it for the players. On multi-GPU systems Vulkan may
        // pick a non-zero device; the QuadLayer's external semaphore is
        // imported into THAT device's primary CUDA context, and player
        // streams must match or cudaSignalExternalSemaphoresAsync fails.
        // Default size = 1920x1080; user can resize.
        viz::VizSession::Config cfg{};
        cfg.mode = viz::DisplayMode::kWindow;
        cfg.window_width = 1920;
        cfg.window_height = 1080;
        cfg.app_name = "viz_video_smoke";

        auto session = viz::VizSession::create(cfg);
        const viz::VkContext* ctx = session->get_vk_context();
        const VkRenderPass render_pass = session->get_render_pass();
        const int cuda_device_id = ctx->cuda_device_id();
        std::printf("vulkan + cuda device id = %d\n", cuda_device_id);

        // Each player owns a worker thread that reads its file and
        // produces decoded RGBA8 frames into its queue. Spawning all
        // 9 in parallel lets cuvidMapVideoFrame's blocking waits run
        // concurrently across decoders instead of serializing on the
        // main thread.
        for (auto& v : videos)
        {
            v->player = std::make_unique<viz_smoke::NvdecPlayer>(cuda_device_id, v->path);
        }

        // Wait for each worker to produce its first frame so we know
        // a decoder is healthy before adding the layer.
        for (auto& v : videos)
        {
            for (int safety = 0; safety < 10000; ++safety)
            {
                v->first_frame = v->player->try_pop();
                if (v->first_frame != nullptr)
                {
                    break;
                }
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
            }
            if (v->first_frame == nullptr)
            {
                throw std::runtime_error("never produced a decoded frame for " + v->path);
            }
        }

        // One QuadLayer per input, in argv order. Compositor tiles
        // row-major in insertion order.
        const auto t0 = std::chrono::steady_clock::now();
        for (size_t i = 0; i < videos.size(); ++i)
        {
            viz::QuadLayer::Config layer_cfg;
            layer_cfg.name = "video_" + std::to_string(i);
            layer_cfg.resolution = { videos[i]->first_frame->width, videos[i]->first_frame->height };
            layer_cfg.mip_lod_bias = lod_bias;
            videos[i]->layer = session->add_layer<viz::QuadLayer>(*ctx, render_pass, layer_cfg);
            submit_to_layer(*videos[i]->layer, *videos[i]->first_frame, videos[i]->player->stream());
            videos[i]->in_flight = std::move(videos[i]->first_frame);

            // Pull source FPS from the H.264 VUI; fall back to 30 if
            // the encoder didn't emit timing_info.
            const double period = videos[i]->player->frame_period_seconds();
            videos[i]->frame_period =
                std::chrono::nanoseconds(static_cast<int64_t>((period > 0.0 ? period : 1.0 / 30.0) * 1e9));
            videos[i]->next_present = t0 + videos[i]->frame_period;
            std::printf("video %zu: %s @ %.3f fps\n", i, videos[i]->path.c_str(), period > 0.0 ? 1.0 / period : 30.0);
        }
        std::fflush(stdout);

        while (!session->should_close())
        {
            const auto now = std::chrono::steady_clock::now();
            // Workers populate the queues asynchronously. Main only
            // pops + submits when the per-video presentation deadline
            // has elapsed; the QuadLayer mailbox keeps the previously
            // submitted frame visible between presentations. --static
            // skips this entirely — the first-frame submit above is
            // the only submit, the mailbox shows it forever.
            if (!static_mode)
            {
                for (auto& v : videos)
                {
                    if (now >= v->next_present)
                    {
                        if (auto next = v->player->try_pop())
                        {
                            submit_to_layer(*v->layer, *next, v->player->stream());
                            v->in_flight = std::move(next);
                        }
                        v->next_present += v->frame_period;
                        // Don't accumulate debt if we fell behind (e.g.
                        // window was hidden / frozen). Snap to wall clock.
                        if (v->next_present < now)
                        {
                            v->next_present = now + v->frame_period;
                        }
                    }
                }
            }

            const auto info = session->render();
            if (info.frame_index > 0 && info.frame_index % 60 == 0)
            {
                const auto stats = session->get_frame_timing_stats();
                std::printf("frame %llu: %.1f fps (%.2f ms/frame)\n", static_cast<unsigned long long>(info.frame_index),
                            stats.render_fps, stats.avg_frame_time_ms);
                std::fflush(stdout);
            }
        }

        session.reset();
    }
    catch (const std::exception& e)
    {
        std::fprintf(stderr, "viz_video_smoke: %s\n", e.what());
        return EXIT_FAILURE;
    }
    return EXIT_SUCCESS;
}
