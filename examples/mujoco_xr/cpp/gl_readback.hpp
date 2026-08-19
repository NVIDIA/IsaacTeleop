// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// MuJoCo's offscreen framebuffer -> the CUDA-linear buffers
// viz::ProjectionLayer.submit() consumes, with no host round trip. Stage by
// stage in README.md.
//
// Use cudaGraphicsGLRegisterBUFFER, never RegisterImage: RegisterImage takes no
// depth format and no multisampled renderbuffer, and mjrContext.offDepthStencil
// is both.

#include "gl.hpp"

#include <cstdint>
#include <vector>

namespace mujoco_xr
{

class Readback
{
public:
    Readback() = default;
    ~Readback();

    Readback(const Readback&) = delete;
    Readback& operator=(const Readback&) = delete;

    // `src_fbo` is mjrContext.offFBO. Needed here, not just in capture():
    // glBlitFramebuffer rejects a depth blit between differing formats, so the
    // blit target is matched to whichever depth format MuJoCo chose.
    void create(uint32_t width, uint32_t height, uint32_t view_count, GLuint src_fbo);
    void destroy();

    // Blit, convert and read back one view. Unmaps that view first, so a
    // pointer from color_ptr()/depth_ptr() lives only until the next capture().
    void capture(uint32_t view, GLuint src_fbo);

    // Map every view into CUDA. Once, after the frame's last capture().
    void map();

    void* color_ptr(uint32_t view) const;
    void* depth_ptr(uint32_t view) const;

    uint32_t width() const
    {
        return width_;
    }
    uint32_t height() const
    {
        return height_;
    }

private:
    struct View
    {
        GLuint blit_fbo = 0;
        GLuint blit_color = 0; // RGBA8 texture
        GLuint blit_depth = 0; // DEPTH24_STENCIL8 texture
        GLuint out_fbo = 0;
        GLuint out_color = 0; // RGBA8 texture
        GLuint out_depth = 0; // R32F texture
        GLuint color_pbo = 0;
        GLuint depth_pbo = 0;
        void* color_resource = nullptr; // cudaGraphicsResource_t
        void* depth_resource = nullptr;
        void* color_device_ptr = nullptr;
        void* depth_device_ptr = nullptr;
        bool mapped = false;
    };

    void build_program();
    // throw_on_error false on the teardown path, which is reached from a
    // destructor with the GL context possibly already gone.
    void unmap(View& v, bool throw_on_error);
    const View& at(uint32_t view) const;

    uint32_t width_ = 0;
    uint32_t height_ = 0;
    GLuint program_ = 0;
    GLuint vao_ = 0;
    std::vector<View> views_;
};

} // namespace mujoco_xr
