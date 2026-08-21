// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// A headless OpenGL context, made through EGL's device platform so it needs no display,
// no X server and no Wayland compositor. It replaces `mujoco.GLContext`, whose only job
// here was this -- and which came attached to a whole `mujoco` wheel.
//
// EGL is reached through dlopen, like the GL entry points in gl.hpp: libEGL is already
// in the process on any machine that can run this, and a link-time dependency would put
// it on the wheel's NEEDED list for machines that cannot.

#include <cstdint>

namespace robot_twin
{

class GlContext
{
public:
    // `device_index` selects among the EGL devices, which on a multi-GPU machine is
    // which GPU. Negative means "the first that yields a context", which is right only
    // on a single-GPU machine -- SceneRenderer checks the choice against viz's CUDA
    // device and says so if they differ.
    GlContext(uint32_t width, uint32_t height, int device_index);
    ~GlContext();

    GlContext(const GlContext&) = delete;
    GlContext& operator=(const GlContext&) = delete;

    // Binds the context to the calling thread. A GL context is thread-affine: the
    // thread that renders must be the thread that called this.
    void make_current();

    // Which EGL device this context landed on.
    int device_index() const
    {
        return device_index_;
    }

private:
    void destroy();

    void* display_ = nullptr; // EGLDisplay
    void* surface_ = nullptr; // EGLSurface
    void* context_ = nullptr; // EGLContext
    int device_index_ = -1;
};

} // namespace robot_twin
