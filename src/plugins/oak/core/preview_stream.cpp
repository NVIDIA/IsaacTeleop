// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "preview_stream.hpp"

#include <SDL.h>
#include <iostream>
#include <stdexcept>

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

    std::shared_ptr<dai::MessageQueue> queue;

    ~Impl()
    {
        if (texture)
            SDL_DestroyTexture(texture);
        if (renderer)
            SDL_DestroyRenderer(renderer);
        if (window)
            SDL_DestroyWindow(window);
        SDL_QuitSubSystem(SDL_INIT_VIDEO);
    }
};

PreviewStream::~PreviewStream() = default;

std::unique_ptr<PreviewStream> PreviewStream::create(const std::string& name, dai::Pipeline& pipeline)
{
    // Find existing Camera on CAM_A, or create one
    std::shared_ptr<dai::node::Camera> camRgb;
    for (auto& node : pipeline.getAllNodes())
    {
        auto cam = std::dynamic_pointer_cast<dai::node::Camera>(node);
        if (cam && cam->getBoardSocket() == dai::CameraBoardSocket::CAM_A)
        {
            camRgb = cam;
            break;
        }
    }

    if (!camRgb)
    {
        camRgb = pipeline.create<dai::node::Camera>();
        camRgb->build(dai::CameraBoardSocket::CAM_A);
    }

    constexpr int preview_w = 640;
    constexpr int preview_h = 400;
    auto previewOutput = camRgb->requestOutput(std::make_pair(preview_w, preview_h), dai::ImgFrame::Type::BGR888i);

    if (SDL_Init(SDL_INIT_VIDEO) != 0)
        throw std::runtime_error(std::string("Preview: SDL_Init failed: ") + SDL_GetError());

    auto impl = std::make_unique<Impl>();

    impl->window = SDL_CreateWindow(
        name.c_str(), SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, preview_w, preview_h, SDL_WINDOW_SHOWN);

    if (!impl->window)
        throw std::runtime_error(std::string("Preview: SDL_CreateWindow failed: ") + SDL_GetError());

    impl->renderer = SDL_CreateRenderer(impl->window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!impl->renderer)
        impl->renderer = SDL_CreateRenderer(impl->window, -1, 0);

    if (!impl->renderer)
        throw std::runtime_error(std::string("Preview: SDL_CreateRenderer failed: ") + SDL_GetError());

    impl->queue = previewOutput->createOutputQueue();

    auto stream = std::unique_ptr<PreviewStream>(new PreviewStream());
    stream->m_impl = std::move(impl);

    std::cout << "Color preview enabled (" << preview_w << "x" << preview_h << ")" << std::endl;
    return stream;
}

void PreviewStream::update()
{
    if (!m_impl->queue)
        return;

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
}

} // namespace oak
} // namespace plugins
