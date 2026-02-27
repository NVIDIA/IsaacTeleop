// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "preview_stream.hpp"

#include <SDL.h>
#include <iostream>

namespace plugins
{
namespace oak
{

struct PreviewStream::Impl
{
    SDL_Window* window = nullptr;
    SDL_Renderer* renderer = nullptr;
    SDL_Texture* texture = nullptr;
    int tex_width = 0;
    int tex_height = 0;

    std::shared_ptr<dai::DataOutputQueue> queue;

    ~Impl()
    {
        if (texture)
            SDL_DestroyTexture(texture);
        if (renderer)
            SDL_DestroyRenderer(renderer);
        if (window)
            SDL_DestroyWindow(window);
        SDL_Quit();
    }
};

PreviewStream::~PreviewStream() = default;

std::unique_ptr<PreviewStream> PreviewStream::try_create(const std::string& name,
                                                         dai::Pipeline& pipeline,
                                                         dai::ColorCameraProperties::SensorResolution resolution)
{
    // Find existing ColorCamera on CAM_A, or create one
    std::shared_ptr<dai::node::ColorCamera> camRgb;
    for (auto& node : pipeline.getAllNodes())
    {
        auto cam = std::dynamic_pointer_cast<dai::node::ColorCamera>(node);
        if (cam && cam->getBoardSocket() == dai::CameraBoardSocket::CAM_A)
        {
            camRgb = cam;
            break;
        }
    }

    if (!camRgb)
    {
        std::cout << "Creating new ColorCamera on CAM_A" << std::endl;
        camRgb = pipeline.create<dai::node::ColorCamera>();
        camRgb->setBoardSocket(dai::CameraBoardSocket::CAM_A);
        camRgb->setResolution(resolution);
        camRgb->setColorOrder(dai::ColorCameraProperties::ColorOrder::BGR);
    }

    int preview_w = 640;
    int preview_h = (resolution == dai::ColorCameraProperties::SensorResolution::THE_800_P) ? 400 : 360;

    camRgb->setPreviewSize(preview_w, preview_h);
    camRgb->setInterleaved(true);

    auto xout = pipeline.create<dai::node::XLinkOut>();
    xout->setStreamName(name);
    camRgb->preview.link(xout->input);

    if (SDL_Init(SDL_INIT_VIDEO) != 0)
    {
        std::cerr << "Preview: SDL_Init failed: " << SDL_GetError() << std::endl;
        return nullptr;
    }

    auto impl = std::make_unique<Impl>();

    impl->window = SDL_CreateWindow(
        name.c_str(), SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, preview_w, preview_h, SDL_WINDOW_SHOWN);

    if (!impl->window)
    {
        std::cerr << "Preview: SDL_CreateWindow failed: " << SDL_GetError() << std::endl;
        return nullptr;
    }

    impl->renderer = SDL_CreateRenderer(impl->window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!impl->renderer)
        impl->renderer = SDL_CreateRenderer(impl->window, -1, 0);

    if (!impl->renderer)
    {
        std::cerr << "Preview: SDL_CreateRenderer failed: " << SDL_GetError() << std::endl;
        return nullptr;
    }

    auto stream = std::unique_ptr<PreviewStream>(new PreviewStream());
    stream->m_impl = std::move(impl);

    std::cout << "Color preview enabled (" << preview_w << "x" << preview_h << ")" << std::endl;
    return stream;
}

void PreviewStream::setOutputQueue(std::shared_ptr<dai::DataOutputQueue> queue)
{
    m_impl->queue = std::move(queue);
}

void PreviewStream::update()
{
    auto frame = m_impl->queue->tryGet<dai::ImgFrame>();
    if (!frame)
        return;

    const auto* data = frame->getData().data();
    int width = frame->getWidth();
    int height = frame->getHeight();

    if (width != m_impl->tex_width || height != m_impl->tex_height)
    {
        if (m_impl->texture)
            SDL_DestroyTexture(m_impl->texture);

        m_impl->texture =
            SDL_CreateTexture(m_impl->renderer, SDL_PIXELFORMAT_BGR24, SDL_TEXTUREACCESS_STREAMING, width, height);

        if (!m_impl->texture)
        {
            std::cerr << "Preview: SDL_CreateTexture failed: " << SDL_GetError() << std::endl;
            return;
        }

        m_impl->tex_width = width;
        m_impl->tex_height = height;
    }

    SDL_UpdateTexture(m_impl->texture, nullptr, data, width * 3);
    SDL_RenderClear(m_impl->renderer);
    SDL_RenderCopy(m_impl->renderer, m_impl->texture, nullptr, nullptr);
    SDL_RenderPresent(m_impl->renderer);

    SDL_Event event;
    while (SDL_PollEvent(&event))
    {
        if (event.type == SDL_QUIT)
            return;
        if (event.type == SDL_KEYDOWN && (event.key.keysym.sym == SDLK_ESCAPE || event.key.keysym.sym == SDLK_q))
            return;
    }
}

} // namespace oak
} // namespace plugins
