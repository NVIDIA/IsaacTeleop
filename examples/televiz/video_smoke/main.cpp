// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Plays an H.264 Annex B file into a Televiz QuadLayer:
//   ./viz_video_smoke /path/to/video.h264
// The example loops the stream on EOF.

#include "h264_file_reader.hpp"
#include "nvdec_player.hpp"

#include <viz/core/vk_context.hpp>
#include <viz/layers/quad_layer.hpp>
#include <viz/session/viz_session.hpp>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <memory>
#include <string>

int main(int argc, char** argv)
{
    if (argc < 2)
    {
        std::fprintf(stderr,
                     "usage: %s <video.h264>\n"
                     "  Input must be raw H.264 Annex B. To convert from MP4:\n"
                     "    ffmpeg -i in.mp4 -c:v copy -bsf:v h264_mp4toannexb -f h264 out.h264\n",
                     argv[0]);
        return EXIT_FAILURE;
    }

    try
    {
        viz_smoke::H264FileReader reader(argv[1]);
        viz_smoke::NvdecPlayer player;

        // Decode SPS/PPS + first IDR up front so we know the stream's
        // resolution before the QuadLayer is sized.
        viz_smoke::NvdecPlayer::DecodedFrame first{};
        for (int safety = 0; safety < 2048; ++safety)
        {
            const uint8_t* nalu = nullptr;
            size_t nalu_size = 0;
            if (!reader.next_nalu(&nalu, &nalu_size))
            {
                break;
            }
            if (player.feed(nalu, nalu_size))
            {
                first = player.current_frame();
                break;
            }
        }
        if (first.data == nullptr)
        {
            throw std::runtime_error("video_smoke: never produced a decoded frame; bad input?");
        }

        viz::VizSession::Config cfg{};
        cfg.mode = viz::DisplayMode::kWindow;
        cfg.window_width = first.width;
        cfg.window_height = first.height;
        cfg.app_name = "viz_video_smoke";
        cfg.clear_color[0] = 0.0f;
        cfg.clear_color[1] = 0.0f;
        cfg.clear_color[2] = 0.0f;
        cfg.clear_color[3] = 1.0f;

        auto session = viz::VizSession::create(cfg);
        const viz::VkContext* ctx = session->get_vk_context();
        const VkRenderPass render_pass = session->get_render_pass();

        viz::QuadLayer::Config layer_cfg;
        layer_cfg.name = "video";
        layer_cfg.resolution = { first.width, first.height };
        auto* layer = session->add_layer<viz::QuadLayer>(*ctx, render_pass, layer_cfg);

        auto submit = [&](const viz_smoke::NvdecPlayer::DecodedFrame& f)
        {
            viz::VizBuffer src{};
            src.data = const_cast<uint8_t*>(f.data);
            src.width = f.width;
            src.height = f.height;
            src.format = viz::PixelFormat::kRGBA8;
            src.pitch = f.pitch;
            src.space = viz::MemorySpace::kDevice;
            layer->submit(src);
        };
        submit(first);

        while (!session->should_close())
        {
            // Pull one fresh decoded frame per render iteration. If
            // the demuxer finished a packet that didn't yield a
            // frame (SPS/PPS, end-of-GOP markers), keep pulling.
            for (int safety = 0; safety < 64; ++safety)
            {
                const uint8_t* nalu = nullptr;
                size_t nalu_size = 0;
                if (!reader.next_nalu(&nalu, &nalu_size))
                {
                    break;
                }
                if (player.feed(nalu, nalu_size))
                {
                    submit(player.current_frame());
                    break;
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
