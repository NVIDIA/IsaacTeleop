// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "gl_context.hpp"

#include <EGL/egl.h>
#include <EGL/eglext.h>

#include <dlfcn.h>
#include <stdexcept>
#include <string>
#include <vector>

namespace robot_twin
{
namespace
{

constexpr int kMaxDevices = 16;

using QueryDevicesFn = EGLBoolean (*)(EGLint, EGLDeviceEXT*, EGLint*);
using GetPlatformDisplayFn = EGLDisplay (*)(EGLenum, void*, const EGLAttrib*);

// libEGL, and the two EXT entry points that make a display out of a device rather than
// out of a window system. RTLD_NOLOAD first for the same reason gl.cpp does it: if the
// process already has a copy, that is the one whose dispatch table matters.
void* egl_handle()
{
    static void* handle = []
    {
        void* opened = dlopen("libEGL.so.1", RTLD_LAZY | RTLD_NOLOAD);
        if (opened == nullptr)
        {
            opened = dlopen("libEGL.so.1", RTLD_LAZY);
        }
        if (opened == nullptr)
        {
            throw std::runtime_error(
                "robot_twin: libEGL.so.1 is not available; the robot twin "
                "renders headless and needs it. Install libegl1.");
        }
        return opened;
    }();
    return handle;
}

template <typename Fn>
Fn egl_symbol(const char* name)
{
    void* symbol = dlsym(egl_handle(), name);
    if (symbol == nullptr)
    {
        throw std::runtime_error(std::string("robot_twin: libEGL has no ") + name);
    }
    return reinterpret_cast<Fn>(symbol);
}

// eglGetProcAddress rather than dlsym: EXT entry points live in the driver, not in the
// libglvnd stub, so dlsym finds nothing for them.
template <typename Fn>
Fn egl_extension(const char* name)
{
    auto get_proc = egl_symbol<__eglMustCastToProperFunctionPointerType (*)(const char*)>("eglGetProcAddress");
    void* symbol = reinterpret_cast<void*>(get_proc(name));
    if (symbol == nullptr)
    {
        throw std::runtime_error(std::string("robot_twin: this EGL implementation has no ") + name +
                                 ". A headless context needs EGL_EXT_platform_device; on NVIDIA that "
                                 "means the proprietary driver rather than Mesa's software EGL.");
    }
    return reinterpret_cast<Fn>(symbol);
}

std::vector<EGLDeviceEXT> devices()
{
    auto query = egl_extension<QueryDevicesFn>("eglQueryDevicesEXT");
    EGLDeviceEXT found[kMaxDevices] = { nullptr };
    EGLint count = 0;
    if (query(kMaxDevices, found, &count) != EGL_TRUE || count <= 0)
    {
        throw std::runtime_error("robot_twin: EGL reports no devices, so there is no GPU to render on");
    }
    return std::vector<EGLDeviceEXT>(found, found + count);
}

std::string egl_error()
{
    auto get_error = egl_symbol<EGLint (*)()>("eglGetError");
    return "EGL error 0x" + [&]
    {
        static const char kHex[] = "0123456789abcdef";
        const EGLint code = get_error();
        std::string out;
        for (int shift = 12; shift >= 0; shift -= 4)
        {
            out.push_back(kHex[(code >> shift) & 0xF]);
        }
        return out;
    }();
}

} // namespace

GlContext::GlContext(uint32_t width, uint32_t height, int device_index)
{
    const std::vector<EGLDeviceEXT> all = devices();
    if (device_index >= static_cast<int>(all.size()))
    {
        throw std::runtime_error("robot_twin: EGL device " + std::to_string(device_index) + " does not exist; " +
                                 std::to_string(all.size()) + " are present");
    }
    const int first = device_index < 0 ? 0 : device_index;
    const int last = device_index < 0 ? static_cast<int>(all.size()) - 1 : device_index;

    auto get_display = egl_extension<GetPlatformDisplayFn>("eglGetPlatformDisplayEXT");
    auto initialize = egl_symbol<EGLBoolean (*)(EGLDisplay, EGLint*, EGLint*)>("eglInitialize");
    auto choose = egl_symbol<EGLBoolean (*)(EGLDisplay, const EGLint*, EGLConfig*, EGLint, EGLint*)>("eglChooseConfig");
    auto bind_api = egl_symbol<EGLBoolean (*)(EGLenum)>("eglBindAPI");
    auto create_surface = egl_symbol<EGLSurface (*)(EGLDisplay, EGLConfig, const EGLint*)>("eglCreatePbufferSurface");
    auto create_context =
        egl_symbol<EGLContext (*)(EGLDisplay, EGLConfig, EGLContext, const EGLint*)>("eglCreateContext");

    // Depth and stencil are the offscreen framebuffer's, made by mjr_makeContext against
    // this context -- the config only has to be renderable.
    const EGLint config_attribs[] = { EGL_SURFACE_TYPE,
                                      EGL_PBUFFER_BIT,
                                      EGL_RENDERABLE_TYPE,
                                      EGL_OPENGL_BIT,
                                      EGL_RED_SIZE,
                                      8,
                                      EGL_GREEN_SIZE,
                                      8,
                                      EGL_BLUE_SIZE,
                                      8,
                                      EGL_ALPHA_SIZE,
                                      8,
                                      EGL_DEPTH_SIZE,
                                      24,
                                      EGL_NONE };
    const EGLint surface_attribs[] = { EGL_WIDTH, static_cast<EGLint>(width), EGL_HEIGHT, static_cast<EGLint>(height),
                                       EGL_NONE };

    for (int index = first; index <= last; ++index)
    {
        EGLDisplay display = get_display(EGL_PLATFORM_DEVICE_EXT, all[static_cast<size_t>(index)], nullptr);
        if (display == EGL_NO_DISPLAY || initialize(display, nullptr, nullptr) != EGL_TRUE)
        {
            continue;
        }
        EGLConfig config = nullptr;
        EGLint matched = 0;
        if (choose(display, config_attribs, &config, 1, &matched) != EGL_TRUE || matched < 1)
        {
            continue;
        }
        // Desktop OpenGL, not GL ES: MuJoCo's renderer is written against 1.5/3.3 core.
        if (bind_api(EGL_OPENGL_API) != EGL_TRUE)
        {
            continue;
        }
        EGLSurface surface = create_surface(display, config, surface_attribs);
        if (surface == EGL_NO_SURFACE)
        {
            continue;
        }
        EGLContext context = create_context(display, config, EGL_NO_CONTEXT, nullptr);
        if (context == EGL_NO_CONTEXT)
        {
            continue;
        }
        display_ = display;
        surface_ = surface;
        context_ = context;
        device_index_ = index;
        return;
    }
    throw std::runtime_error("robot_twin: no EGL device yielded an OpenGL context (" + egl_error() +
                             "). A headless context needs a driver with EGL_EXT_platform_device and "
                             "desktop OpenGL.");
}

void GlContext::make_current()
{
    auto make = egl_symbol<EGLBoolean (*)(EGLDisplay, EGLSurface, EGLSurface, EGLContext)>("eglMakeCurrent");
    if (make(display_, surface_, surface_, context_) != EGL_TRUE)
    {
        throw std::runtime_error("robot_twin: eglMakeCurrent failed (" + egl_error() + ")");
    }
}

GlContext::~GlContext()
{
    destroy();
}

void GlContext::destroy()
{
    if (display_ == nullptr)
    {
        return;
    }
    auto destroy_context = egl_symbol<EGLBoolean (*)(EGLDisplay, EGLContext)>("eglDestroyContext");
    auto destroy_surface = egl_symbol<EGLBoolean (*)(EGLDisplay, EGLSurface)>("eglDestroySurface");
    auto terminate = egl_symbol<EGLBoolean (*)(EGLDisplay)>("eglTerminate");
    auto make = egl_symbol<EGLBoolean (*)(EGLDisplay, EGLSurface, EGLSurface, EGLContext)>("eglMakeCurrent");

    make(display_, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    if (context_ != nullptr)
    {
        destroy_context(display_, context_);
    }
    if (surface_ != nullptr)
    {
        destroy_surface(display_, surface_);
    }
    terminate(display_);
    display_ = surface_ = context_ = nullptr;
}

} // namespace robot_twin
