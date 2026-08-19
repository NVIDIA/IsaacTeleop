// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "gl_readback.hpp"

#include <cuda_gl_interop.h>
#include <cuda_runtime.h>
#include <stdexcept>
#include <string>
#include <vector>

namespace mujoco_xr
{

using namespace gl;

namespace
{

void check_cuda(cudaError_t err, const char* what)
{
    if (err != cudaSuccess)
    {
        throw std::runtime_error(std::string("mujoco_xr: ") + what + " failed: " + cudaGetErrorString(err));
    }
}

// gl_VertexID -> one viewport-covering triangle, so there is no vertex buffer.
constexpr const char* kVertexSource = R"glsl(
#version 330 core
out vec2 vUv;
void main()
{
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    vUv = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
)glsl";

// The two conversions the XR layer needs, in the one place they happen.
constexpr const char* kFragmentSource = R"glsl(
#version 330 core
uniform sampler2D uColor;
uniform sampler2D uDepth;
in vec2 vUv;
layout(location = 0) out vec4 oColor;
layout(location = 1) out float oDepth;
void main()
{
    vec2 uv = vec2(vUv.x, 1.0 - vUv.y);      // GL bottom-up -> XR top-down
    oColor = texture(uColor, uv);
    oDepth = 1.0 - texture(uDepth, uv).r;    // mjr_render reverse Z -> near 0, far 1
}
)glsl";

GLuint compile(GLenum stage, const char* source)
{
    const GLuint shader = CreateShader(stage);
    ShaderSource(shader, 1, &source, nullptr);
    CompileShader(shader);
    GLint ok = GL_FALSE;
    GetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (ok != static_cast<GLint>(GL_TRUE))
    {
        GLint len = 0;
        GetShaderiv(shader, GL_INFO_LOG_LENGTH, &len);
        std::string log(static_cast<size_t>(len > 0 ? len : 1), '\0');
        GetShaderInfoLog(shader, len, nullptr, log.data());
        DeleteShader(shader);
        throw std::runtime_error("mujoco_xr: readback shader failed to compile: " + log);
    }
    return shader;
}

GLuint make_texture(GLenum internal_format, GLenum format, GLenum type, uint32_t width, uint32_t height)
{
    GLuint tex = 0;
    GenTextures(1, &tex);
    BindTexture(GL_TEXTURE_2D, tex);
    TexImage2D(GL_TEXTURE_2D, 0, static_cast<GLint>(internal_format), static_cast<GLsizei>(width),
               static_cast<GLsizei>(height), 0, format, type, nullptr);
    TexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    TexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    TexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    TexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    BindTexture(GL_TEXTURE_2D, 0);
    return tex;
}

// A pack buffer and its CUDA registration. ReadOnly: submit() only reads it.
void make_pbo(size_t size_bytes, GLuint* out_pbo, void** out_resource)
{
    GenBuffers(1, out_pbo);
    BindBuffer(GL_PIXEL_PACK_BUFFER, *out_pbo);
    BufferData(GL_PIXEL_PACK_BUFFER, static_cast<GLsizeiptr>(size_bytes), nullptr, GL_STREAM_READ);
    BindBuffer(GL_PIXEL_PACK_BUFFER, 0);
    check("pixel pack buffer allocation");

    cudaGraphicsResource_t res = nullptr;
    check_cuda(cudaGraphicsGLRegisterBuffer(&res, *out_pbo, cudaGraphicsRegisterFlagsReadOnly),
               "cudaGraphicsGLRegisterBuffer");
    *out_resource = res;
}

// `src_fbo`'s depth format, as the triple a matching texture needs.
struct DepthFormat
{
    GLenum internal_format;
    GLenum format;
    GLenum type;
};

// Restores the draw-framebuffer binding this object was constructed under.
struct ScopedDrawFramebuffer
{
    GLint previous = 0;

    ScopedDrawFramebuffer()
    {
        GetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &previous);
    }
    ~ScopedDrawFramebuffer()
    {
        BindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(previous));
    }

    ScopedDrawFramebuffer(const ScopedDrawFramebuffer&) = delete;
    ScopedDrawFramebuffer& operator=(const ScopedDrawFramebuffer&) = delete;
};

DepthFormat depth_format_of(GLuint src_fbo)
{
    BindFramebuffer(GL_READ_FRAMEBUFFER, src_fbo);
    GLint component_type = 0;
    GetFramebufferAttachmentParameteriv(
        GL_READ_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_FRAMEBUFFER_ATTACHMENT_COMPONENT_TYPE, &component_type);
    BindFramebuffer(GL_READ_FRAMEBUFFER, 0);
    check("querying the MuJoCo offscreen depth format");

    if (static_cast<GLenum>(component_type) == GL_FLOAT)
    {
        return { GL_DEPTH32F_STENCIL8, GL_DEPTH_STENCIL, GL_FLOAT_32_UNSIGNED_INT_24_8_REV };
    }
    return { GL_DEPTH24_STENCIL8, GL_DEPTH_STENCIL, GL_UNSIGNED_INT_24_8 };
}

} // namespace

Readback::~Readback()
{
    destroy();
}

void Readback::build_program()
{
    const GLuint vs = compile(GL_VERTEX_SHADER, kVertexSource);
    const GLuint fs = compile(GL_FRAGMENT_SHADER, kFragmentSource);
    program_ = CreateProgram();
    AttachShader(program_, vs);
    AttachShader(program_, fs);
    LinkProgram(program_);
    DeleteShader(vs);
    DeleteShader(fs);

    GLint ok = GL_FALSE;
    GetProgramiv(program_, GL_LINK_STATUS, &ok);
    if (ok != static_cast<GLint>(GL_TRUE))
    {
        GLint len = 0;
        GetProgramiv(program_, GL_INFO_LOG_LENGTH, &len);
        std::string log(static_cast<size_t>(len > 0 ? len : 1), '\0');
        GetProgramInfoLog(program_, len, nullptr, log.data());
        throw std::runtime_error("mujoco_xr: readback program failed to link: " + log);
    }

    UseProgram(program_);
    Uniform1i(GetUniformLocation(program_, "uColor"), 0);
    Uniform1i(GetUniformLocation(program_, "uDepth"), 1);
    UseProgram(0);
    check("readback program setup");
}

void Readback::create(uint32_t width, uint32_t height, uint32_t view_count, GLuint src_fbo)
{
    if (width == 0 || height == 0 || view_count == 0)
    {
        throw std::invalid_argument("mujoco_xr: readback needs a non-empty size and at least one view");
    }
    load();
    width_ = width;
    height_ = height;

    const ScopedDrawFramebuffer restore_binding;

    build_program();
    GenVertexArrays(1, &vao_);

    const DepthFormat depth = depth_format_of(src_fbo);
    views_.resize(view_count);
    for (View& v : views_)
    {
        v.blit_color = make_texture(GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE, width, height);
        v.blit_depth = make_texture(depth.internal_format, depth.format, depth.type, width, height);
        GenFramebuffers(1, &v.blit_fbo);
        BindFramebuffer(GL_FRAMEBUFFER, v.blit_fbo);
        FramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, v.blit_color, 0);
        FramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_TEXTURE_2D, v.blit_depth, 0);
        if (CheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
        {
            throw std::runtime_error("mujoco_xr: the readback blit framebuffer is incomplete");
        }

        v.out_color = make_texture(GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE, width, height);
        v.out_depth = make_texture(GL_R32F, GL_RED, GL_FLOAT, width, height);
        GenFramebuffers(1, &v.out_fbo);
        BindFramebuffer(GL_FRAMEBUFFER, v.out_fbo);
        FramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, v.out_color, 0);
        FramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT1, GL_TEXTURE_2D, v.out_depth, 0);
        if (CheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
        {
            throw std::runtime_error("mujoco_xr: the readback output framebuffer is incomplete");
        }

        const size_t pixels = static_cast<size_t>(width) * height;
        make_pbo(pixels * 4, &v.color_pbo, &v.color_resource);
        make_pbo(pixels * sizeof(float), &v.depth_pbo, &v.depth_resource);
    }
    check("readback resource creation");
}

void Readback::unmap(View& v, bool throw_on_error)
{
    if (!v.mapped)
    {
        return;
    }
    cudaGraphicsResource_t resources[2] = { static_cast<cudaGraphicsResource_t>(v.color_resource),
                                            static_cast<cudaGraphicsResource_t>(v.depth_resource) };
    const cudaError_t err = cudaGraphicsUnmapResources(2, resources, nullptr);
    v.mapped = false;
    v.color_device_ptr = nullptr;
    v.depth_device_ptr = nullptr;
    if (throw_on_error)
    {
        check_cuda(err, "cudaGraphicsUnmapResources");
    }
}

void Readback::capture(uint32_t view, GLuint src_fbo)
{
    if (view >= views_.size())
    {
        throw std::out_of_range("mujoco_xr: readback view index out of range");
    }
    View& v = views_[view];
    // glReadPixels below is graphics access, illegal while CUDA holds them.
    unmap(v, /*throw_on_error=*/true);

    // mjr_render draws into whatever is bound when it is called. Leaving our
    // own framebuffer bound sends the NEXT frame to it, and the symptom is an
    // empty image with no GL error anywhere.
    const ScopedDrawFramebuffer restore_binding;

    const GLint w = static_cast<GLint>(width_);
    const GLint h = static_cast<GLint>(height_);

    BindFramebuffer(GL_READ_FRAMEBUFFER, src_fbo);
    BindFramebuffer(GL_DRAW_FRAMEBUFFER, v.blit_fbo);
    BlitFramebuffer(0, 0, w, h, 0, 0, w, h, GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT, GL_NEAREST);

    // MuJoCo leaves these on, and none may touch a pass that only moves pixels.
    // Not restored: mjr_render's initGL3 sets all four again every frame.
    Disable(GL_DEPTH_TEST);
    Disable(GL_CULL_FACE);
    Disable(GL_BLEND);
    Disable(GL_SCISSOR_TEST);

    BindFramebuffer(GL_FRAMEBUFFER, v.out_fbo);
    const GLenum targets[2] = { GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1 };
    DrawBuffers(2, targets);
    Viewport(0, 0, w, h);
    UseProgram(program_);
    ActiveTexture(GL_TEXTURE0);
    BindTexture(GL_TEXTURE_2D, v.blit_color);
    ActiveTexture(GL_TEXTURE1);
    BindTexture(GL_TEXTURE_2D, v.blit_depth);
    BindVertexArray(vao_);
    DrawArrays(GL_TRIANGLES, 0, 3);
    BindVertexArray(0);
    UseProgram(0);

    // Tight rows: VizBuffer's pitch is width * bpp, and the 4-byte default
    // alignment would pad an odd-width RGBA8 row.
    PixelStorei(GL_PACK_ALIGNMENT, 1);

    ReadBuffer(GL_COLOR_ATTACHMENT0);
    BindBuffer(GL_PIXEL_PACK_BUFFER, v.color_pbo);
    ReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);

    ReadBuffer(GL_COLOR_ATTACHMENT1);
    BindBuffer(GL_PIXEL_PACK_BUFFER, v.depth_pbo);
    ReadPixels(0, 0, w, h, GL_RED, GL_FLOAT, nullptr);

    BindBuffer(GL_PIXEL_PACK_BUFFER, 0);
    check("readback capture");
}

void Readback::map()
{
    for (View& v : views_)
    {
        if (v.mapped)
        {
            continue;
        }
        // Orders itself after this thread's GL work, so no glFinish is needed.
        cudaGraphicsResource_t resources[2] = { static_cast<cudaGraphicsResource_t>(v.color_resource),
                                                static_cast<cudaGraphicsResource_t>(v.depth_resource) };
        check_cuda(cudaGraphicsMapResources(2, resources, nullptr), "cudaGraphicsMapResources");
        v.mapped = true;

        size_t size = 0;
        check_cuda(cudaGraphicsResourceGetMappedPointer(&v.color_device_ptr, &size, resources[0]),
                   "cudaGraphicsResourceGetMappedPointer(color)");
        check_cuda(cudaGraphicsResourceGetMappedPointer(&v.depth_device_ptr, &size, resources[1]),
                   "cudaGraphicsResourceGetMappedPointer(depth)");
    }
}

const Readback::View& Readback::at(uint32_t view) const
{
    if (view >= views_.size())
    {
        throw std::out_of_range("mujoco_xr: readback view index out of range");
    }
    const View& v = views_[view];
    if (!v.mapped)
    {
        throw std::runtime_error("mujoco_xr: no rendered frame for this view yet -- call render() first");
    }
    return v;
}

void* Readback::color_ptr(uint32_t view) const
{
    return at(view).color_device_ptr;
}

void* Readback::depth_ptr(uint32_t view) const
{
    return at(view).depth_device_ptr;
}

void Readback::destroy()
{
    for (View& v : views_)
    {
        unmap(v, /*throw_on_error=*/false);
        if (v.color_resource != nullptr)
        {
            (void)cudaGraphicsUnregisterResource(static_cast<cudaGraphicsResource_t>(v.color_resource));
        }
        if (v.depth_resource != nullptr)
        {
            (void)cudaGraphicsUnregisterResource(static_cast<cudaGraphicsResource_t>(v.depth_resource));
        }
        // Only if the entry points were ever resolved. The caller owns the
        // ordering: Renderer.close() before mujoco.GLContext.free().
        if (loaded())
        {
            const GLuint buffers[2] = { v.color_pbo, v.depth_pbo };
            DeleteBuffers(2, buffers);
            const GLuint framebuffers[2] = { v.blit_fbo, v.out_fbo };
            DeleteFramebuffers(2, framebuffers);
            const GLuint textures[4] = { v.blit_color, v.blit_depth, v.out_color, v.out_depth };
            DeleteTextures(4, textures);
        }
    }
    views_.clear();

    if (loaded())
    {
        if (vao_ != 0)
        {
            DeleteVertexArrays(1, &vao_);
            vao_ = 0;
        }
        if (program_ != 0)
        {
            DeleteProgram(program_);
            program_ = 0;
        }
    }
    width_ = 0;
    height_ = 0;
}

} // namespace mujoco_xr
