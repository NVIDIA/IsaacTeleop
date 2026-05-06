// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Plays one or more H.264 files into a Televiz window. Multiple inputs
// tile row-major (compositor's tile_layout handles aspect-fit):
//   ./viz_video_smoke /path/to/a.h264 [/path/to/b.h264 ...]

#include "nvdec_player.hpp"

#include <viz/core/vk_context.hpp>
#include <viz/layers/quad_layer.hpp>
#include <viz/session/viz_session.hpp>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

namespace
{

constexpr size_t kChunkBytes = 64 * 1024;

struct Video
{
    std::string path;
    std::ifstream file;
    viz_smoke::NvdecPlayer player;
    viz::QuadLayer* layer = nullptr;
    // Most recently submitted frame; held alive across one render cycle
    // so QuadLayer::submit's async cudaMemcpy can complete before the
    // ~DecodedFrame cudaFree.
    std::unique_ptr<viz_smoke::DecodedFrame> in_flight;
    // First decoded frame, captured during prime() before the session
    // exists. Submitted on the first render iteration.
    std::unique_ptr<viz_smoke::DecodedFrame> first_frame;
};

void submit_to_layer(viz::QuadLayer& layer, const viz_smoke::DecodedFrame& f)
{
    viz::VizBuffer src{};
    src.data = f.data;
    src.width = f.width;
    src.height = f.height;
    src.format = viz::PixelFormat::kRGBA8;
    src.pitch = static_cast<size_t>(f.width) * 4;
    src.space = viz::MemorySpace::kDevice;
    layer.submit(src);
}

// Drain one chunk of the file and feed it. Rewinds on EOF (a read
// that hits EOF can return partial bytes AND fail the stream).
void feed_one_chunk(Video& v, std::vector<uint8_t>& chunk)
{
    v.file.read(reinterpret_cast<char*>(chunk.data()), chunk.size());
    const auto got = static_cast<size_t>(v.file.gcount());
    if (got > 0)
    {
        v.player.feed(chunk.data(), got);
    }
    if (!v.file)
    {
        v.file.clear();
        v.file.seekg(0);
    }
}

} // namespace

int main(int argc, char** argv)
{
    if (argc < 2)
    {
        std::fprintf(stderr,
                     "usage: %s <video.h264> [<video.h264> ...]\n"
                     "  Each input must be raw H.264 Annex B. To convert from MP4:\n"
                     "    ffmpeg -i in.mp4 -c:v copy -bsf:v h264_mp4toannexb -f h264 out.h264\n",
                     argv[0]);
        return EXIT_FAILURE;
    }

    try
    {
        const int n = argc - 1;
        std::vector<std::unique_ptr<Video>> videos;
        videos.reserve(n);
        for (int i = 0; i < n; ++i)
        {
            auto v = std::make_unique<Video>();
            v->path = argv[i + 1];
            v->file.open(v->path, std::ios::binary);
            if (!v->file)
            {
                throw std::runtime_error("cannot open " + v->path);
            }
            videos.push_back(std::move(v));
        }

        // Prime each player to its first frame so we know the resolutions
        // before sizing the window + layers.
        std::vector<uint8_t> chunk(kChunkBytes);
        for (auto& v : videos)
        {
            for (int safety = 0; safety < 4096 && v->player.queued_frame_count() == 0 && v->file; ++safety)
            {
                feed_one_chunk(*v, chunk);
            }
            v->first_frame = v->player.try_pop();
            if (v->first_frame == nullptr)
            {
                throw std::runtime_error("never produced a decoded frame for " + v->path);
            }
        }

        // Open the window wide enough to hold all videos side-by-side at
        // their native heights. tile_layout handles letterbox if user
        // resizes or aspects differ.
        uint32_t total_w = 0;
        uint32_t max_h = 0;
        for (const auto& v : videos)
        {
            total_w += v->first_frame->width;
            if (v->first_frame->height > max_h)
            {
                max_h = v->first_frame->height;
            }
        }

        viz::VizSession::Config cfg{};
        cfg.mode = viz::DisplayMode::kWindow;
        cfg.window_width = total_w;
        cfg.window_height = max_h;
        cfg.app_name = "viz_video_smoke";

        auto session = viz::VizSession::create(cfg);
        const viz::VkContext* ctx = session->get_vk_context();
        const VkRenderPass render_pass = session->get_render_pass();

        // One QuadLayer per input, in argv order. Compositor tiles
        // row-major in insertion order.
        for (size_t i = 0; i < videos.size(); ++i)
        {
            viz::QuadLayer::Config layer_cfg;
            layer_cfg.name = "video_" + std::to_string(i);
            layer_cfg.resolution = { videos[i]->first_frame->width, videos[i]->first_frame->height };
            videos[i]->layer = session->add_layer<viz::QuadLayer>(*ctx, render_pass, layer_cfg);
            submit_to_layer(*videos[i]->layer, *videos[i]->first_frame);
            videos[i]->in_flight = std::move(videos[i]->first_frame);
        }

        while (!session->should_close())
        {
            // Top up each decoder, then submit any newly available frame.
            for (auto& v : videos)
            {
                for (int safety = 0; safety < 256 && v->player.queued_frame_count() == 0; ++safety)
                {
                    feed_one_chunk(*v, chunk);
                }
                if (auto next = v->player.try_pop())
                {
                    submit_to_layer(*v->layer, *next);
                    v->in_flight = std::move(next);
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
