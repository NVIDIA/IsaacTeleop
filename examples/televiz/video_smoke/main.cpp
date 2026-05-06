// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Plays an H.264 file into a Televiz QuadLayer:
//   ./viz_video_smoke /path/to/video.h264

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

// Block until the decoder produces at least one queued frame OR
// the stream ends. NvDecoder needs to see SPS/PPS + an IDR before
// it can emit anything, which can take many NAL units.
std::unique_ptr<viz_smoke::DecodedFrame> prime_first_frame(std::ifstream& f, viz_smoke::NvdecPlayer& player)
{
    std::vector<uint8_t> chunk(kChunkBytes);
    while (player.queued_frame_count() == 0 && f)
    {
        f.read(reinterpret_cast<char*>(chunk.data()), chunk.size());
        const auto got = static_cast<size_t>(f.gcount());
        if (got == 0)
        {
            break;
        }
        player.feed(chunk.data(), got);
    }
    return player.try_pop();
}

} // namespace

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
        std::ifstream file(argv[1], std::ios::binary);
        if (!file)
        {
            throw std::runtime_error(std::string("cannot open ") + argv[1]);
        }
        viz_smoke::NvdecPlayer player;

        auto first = prime_first_frame(file, player);
        if (first == nullptr)
        {
            throw std::runtime_error("never produced a decoded frame; bad input?");
        }

        viz::VizSession::Config cfg{};
        cfg.mode = viz::DisplayMode::kWindow;
        cfg.window_width = first->width;
        cfg.window_height = first->height;
        cfg.app_name = "viz_video_smoke";

        auto session = viz::VizSession::create(cfg);
        viz::QuadLayer::Config layer_cfg;
        layer_cfg.name = "video";
        layer_cfg.resolution = { first->width, first->height };
        auto* layer =
            session->add_layer<viz::QuadLayer>(*session->get_vk_context(), session->get_render_pass(), layer_cfg);

        submit_to_layer(*layer, *first);
        // Hold the most recently submitted buffer alive across one full
        // render cycle. QuadLayer::submit issues an async cudaMemcpy from
        // it that must complete before cudaFree (in ~DecodedFrame).
        std::unique_ptr<viz_smoke::DecodedFrame> in_flight = std::move(first);

        std::vector<uint8_t> chunk(kChunkBytes);
        while (!session->should_close())
        {
            // Top up the decoder until it has at least one queued frame.
            // Bound the inner loop so a malformed file can't trap us.
            // EOF handling: a read that hits EOF can return PARTIAL
            // bytes and still leave the stream in a failed state, so
            // we always rewind after a failed read regardless of how
            // many bytes came back.
            for (int safety = 0; safety < 256 && player.queued_frame_count() == 0; ++safety)
            {
                file.read(reinterpret_cast<char*>(chunk.data()), chunk.size());
                const auto got = static_cast<size_t>(file.gcount());
                if (got > 0)
                {
                    player.feed(chunk.data(), got);
                }
                if (!file)
                {
                    file.clear();
                    file.seekg(0);
                }
            }

            if (auto next = player.try_pop())
            {
                submit_to_layer(*layer, *next);
                in_flight = std::move(next);
            }

            const auto info = session->render();
            if (info.frame_index > 0 && info.frame_index % 60 == 0)
            {
                const auto stats = session->get_frame_timing_stats();
                std::printf("frame %llu: %.1f fps (%.2f ms/frame, decoded queue=%zu)\n",
                            static_cast<unsigned long long>(info.frame_index), stats.render_fps,
                            stats.avg_frame_time_ms, player.queued_frame_count());
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
