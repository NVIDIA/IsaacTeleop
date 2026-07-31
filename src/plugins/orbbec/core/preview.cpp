// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "preview.hpp"

#include <SDL.h>
extern "C"
{
#include <libavcodec/avcodec.h>
#include <libavutil/imgutils.h>
#include <libswscale/swscale.h>
}
#include <libobsensor/ObSensor.hpp>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <utility>

namespace plugins::orbbec
{
namespace
{

struct RgbFrame
{
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<uint8_t> pixels;
};

class Decoder
{
public:
    explicit Decoder(core::OrbbecPixelFormat format) : format_(format)
    {
        if (format_ == core::OrbbecPixelFormat_Mjpg)
        {
            converter_ = std::make_unique<ob::FormatConvertFilter>();
            converter_->setFormatConvertType(FORMAT_MJPG_TO_RGB);
            return;
        }
        const auto codec_id = format_ == core::OrbbecPixelFormat_H264 ? AV_CODEC_ID_H264 : AV_CODEC_ID_HEVC;
        const AVCodec* codec = avcodec_find_decoder(codec_id);
        if (!codec)
            throw std::runtime_error("FFmpeg decoder unavailable for Orbbec preview");
        codec_ = avcodec_alloc_context3(codec);
        if (!codec_ || avcodec_open2(codec_, codec, nullptr) < 0)
            throw std::runtime_error("Unable to open FFmpeg Orbbec preview decoder");
        decoded_ = av_frame_alloc();
        if (!decoded_)
            throw std::runtime_error("Unable to allocate FFmpeg preview frame");
    }

    ~Decoder()
    {
        sws_freeContext(sws_);
        av_frame_free(&decoded_);
        avcodec_free_context(&codec_);
    }

    bool decode(const PreviewFrame& input, RgbFrame& output)
    {
        if (format_ == core::OrbbecPixelFormat_Mjpg)
        {
            auto source = ob::FrameFactory::createVideoFrameFromBuffer(
                input.stream == core::OrbbecCameraStream_ColorLeft ? OB_FRAME_COLOR_LEFT : OB_FRAME_COLOR_RIGHT,
                OB_FORMAT_MJPG, input.width, input.height, const_cast<uint8_t*>(input.encoded.data()), [](uint8_t*) {},
                static_cast<uint32_t>(input.encoded.size()));
            const auto rgb = converter_->process(source)->as<ob::VideoFrame>();
            output.width = rgb->getWidth();
            output.height = rgb->getHeight();
            output.pixels.assign(rgb->getData(), rgb->getData() + rgb->getDataSize());
            return true;
        }

        AVPacket packet{};
        packet.data = const_cast<uint8_t*>(input.encoded.data());
        packet.size = static_cast<int>(input.encoded.size());
        if (avcodec_send_packet(codec_, &packet) < 0 || avcodec_receive_frame(codec_, decoded_) < 0)
            return false;
        output.width = static_cast<uint32_t>(decoded_->width);
        output.height = static_cast<uint32_t>(decoded_->height);
        output.pixels.resize(static_cast<size_t>(output.width) * output.height * 3);
        sws_ = sws_getCachedContext(sws_, decoded_->width, decoded_->height,
                                    static_cast<AVPixelFormat>(decoded_->format), decoded_->width, decoded_->height,
                                    AV_PIX_FMT_RGB24, SWS_FAST_BILINEAR, nullptr, nullptr, nullptr);
        uint8_t* destinations[] = { output.pixels.data() };
        int strides[] = { decoded_->width * 3 };
        sws_scale(sws_, decoded_->data, decoded_->linesize, 0, decoded_->height, destinations, strides);
        return true;
    }

private:
    core::OrbbecPixelFormat format_;
    std::unique_ptr<ob::FormatConvertFilter> converter_;
    AVCodecContext* codec_ = nullptr;
    AVFrame* decoded_ = nullptr;
    SwsContext* sws_ = nullptr;
};

} // namespace

class Preview::Impl
{
public:
    Impl() : worker_([this] { run(); })
    {
    }
    ~Impl()
    {
        stop_.store(true);
        wake_.notify_all();
        if (worker_.joinable())
            worker_.join();
    }

    void submit(PreviewFrame frame)
    {
        std::lock_guard<std::mutex> lock(mutex_);
        latest_[frame.stream] = std::move(frame);
        wake_.notify_one();
    }

    bool closed() const
    {
        return closed_.load();
    }

private:
    void run()
    {
        if (SDL_Init(SDL_INIT_VIDEO) != 0)
        {
            closed_.store(true);
            return;
        }
        SDL_Window* window = SDL_CreateWindow(
            "Orbbec Ego Preview", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, 1280, 520, SDL_WINDOW_RESIZABLE);
        SDL_Renderer* renderer = window ? SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED) : nullptr;
        if (!window || !renderer)
        {
            if (renderer)
                SDL_DestroyRenderer(renderer);
            if (window)
                SDL_DestroyWindow(window);
            SDL_QuitSubSystem(SDL_INIT_VIDEO);
            closed_.store(true);
            return;
        }
        std::map<core::OrbbecCameraStream, std::unique_ptr<Decoder>> decoders;
        std::map<core::OrbbecCameraStream, RgbFrame> images;
        while (!stop_.load())
        {
            SDL_Event event;
            while (SDL_PollEvent(&event))
            {
                if (event.type == SDL_QUIT)
                {
                    closed_.store(true);
                    stop_.store(true);
                }
            }
            std::map<core::OrbbecCameraStream, PreviewFrame> frames;
            {
                std::unique_lock<std::mutex> lock(mutex_);
                wake_.wait_for(lock, std::chrono::milliseconds(10), [this] { return stop_.load() || !latest_.empty(); });
                frames.swap(latest_);
            }
            for (const auto& [stream, frame] : frames)
            {
                auto it = decoders.find(stream);
                if (it == decoders.end())
                    it = decoders.emplace(stream, std::make_unique<Decoder>(frame.format)).first;
                it->second->decode(frame, images[stream]);
            }
            SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
            SDL_RenderClear(renderer);
            int window_width = 0;
            int window_height = 0;
            SDL_GetRendererOutputSize(renderer, &window_width, &window_height);
            int index = 0;
            for (const auto& [_, image] : images)
            {
                SDL_Texture* texture = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_RGB24, SDL_TEXTUREACCESS_STREAMING,
                                                         static_cast<int>(image.width), static_cast<int>(image.height));
                if (texture)
                {
                    SDL_UpdateTexture(texture, nullptr, image.pixels.data(), static_cast<int>(image.width * 3));
                    const int count = static_cast<int>(images.size());
                    SDL_Rect target{ index * window_width / count, 0, window_width / count, window_height };
                    SDL_RenderCopy(renderer, texture, nullptr, &target);
                    SDL_DestroyTexture(texture);
                }
                ++index;
            }
            SDL_RenderPresent(renderer);
        }
        SDL_DestroyRenderer(renderer);
        SDL_DestroyWindow(window);
        SDL_QuitSubSystem(SDL_INIT_VIDEO);
    }

    std::atomic<bool> stop_{ false };
    std::atomic<bool> closed_{ false };
    mutable std::mutex mutex_;
    std::condition_variable wake_;
    std::map<core::OrbbecCameraStream, PreviewFrame> latest_;
    std::thread worker_;
};

Preview::Preview() : impl_(std::make_unique<Impl>())
{
}
Preview::~Preview() = default;
void Preview::submit(PreviewFrame frame)
{
    impl_->submit(std::move(frame));
}
bool Preview::closed() const
{
    return impl_->closed();
}

} // namespace plugins::orbbec
