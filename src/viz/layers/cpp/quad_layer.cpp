// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/render_target.hpp>
#include <viz/core/vk_context.hpp>
#include <viz/layers/quad_layer.hpp>
#include <viz/shaders/textured_quad.frag.spv.h>
#include <viz/shaders/textured_quad.vert.spv.h>

#include <cuda_runtime.h>
#include <stdexcept>
#include <string>

namespace viz
{

namespace
{

void check_vk(VkResult result, const char* what)
{
    if (result != VK_SUCCESS)
    {
        throw std::runtime_error(std::string("QuadLayer: ") + what + " failed: VkResult=" + std::to_string(result));
    }
}

void check_cuda(cudaError_t result, const char* what)
{
    if (result != cudaSuccess)
    {
        throw std::runtime_error(std::string("QuadLayer: ") + what + " failed: " + cudaGetErrorString(result));
    }
}

VkShaderModule create_shader_module(VkDevice device, const unsigned char* spv, size_t size)
{
    VkShaderModuleCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
    info.codeSize = size;
    info.pCode = reinterpret_cast<const uint32_t*>(spv);
    VkShaderModule mod = VK_NULL_HANDLE;
    check_vk(vkCreateShaderModule(device, &info, nullptr, &mod), "vkCreateShaderModule");
    return mod;
}

} // namespace

QuadLayer::QuadLayer(const VkContext& ctx, VkRenderPass render_pass, Config config)
    : LayerBase(config.name), ctx_(&ctx), render_pass_(render_pass), config_(std::move(config))
{
    // Config-only checks first (cheapest, no Vulkan), then the
    // argument-shape check on render_pass, then the context-state
    // check. Ordered cheap-first so unit tests can exercise each
    // path by varying just the relevant argument with an
    // uninitialized VkContext.
    if (config_.format != PixelFormat::kRGBA8)
    {
        // textured_quad samples color; depth (kD32F) would create
        // a depth-aspect view that can't be sampled as color.
        throw std::invalid_argument("QuadLayer: only PixelFormat::kRGBA8 is supported");
    }
    if (config_.resolution.width == 0 || config_.resolution.height == 0)
    {
        throw std::invalid_argument("QuadLayer: resolution must be non-zero");
    }
    if (render_pass == VK_NULL_HANDLE)
    {
        throw std::invalid_argument("QuadLayer: render_pass must be non-null");
    }
    if (!ctx.is_initialized())
    {
        throw std::invalid_argument("QuadLayer: VkContext is not initialized");
    }
    init();
}

QuadLayer::~QuadLayer()
{
    destroy();
}

void QuadLayer::init()
{
    try
    {
        device_image_ = DeviceImage::create(*ctx_, config_.resolution, config_.format);
        create_sampler();
        create_descriptor_set_layout();
        create_pipeline_layout();
        create_pipeline();
        create_descriptor_pool();
        allocate_descriptor_set();
        update_descriptor_set();
    }
    catch (...)
    {
        destroy();
        throw;
    }
}

void QuadLayer::destroy()
{
    if (ctx_ == nullptr)
    {
        return;
    }
    const VkDevice device = ctx_->device();
    if (device == VK_NULL_HANDLE)
    {
        device_image_.reset();
        return;
    }
    if (descriptor_pool_ != VK_NULL_HANDLE)
    {
        // descriptor_set_ is freed implicitly with the pool.
        vkDestroyDescriptorPool(device, descriptor_pool_, nullptr);
        descriptor_pool_ = VK_NULL_HANDLE;
        descriptor_set_ = VK_NULL_HANDLE;
    }
    if (pipeline_ != VK_NULL_HANDLE)
    {
        vkDestroyPipeline(device, pipeline_, nullptr);
        pipeline_ = VK_NULL_HANDLE;
    }
    if (pipeline_layout_ != VK_NULL_HANDLE)
    {
        vkDestroyPipelineLayout(device, pipeline_layout_, nullptr);
        pipeline_layout_ = VK_NULL_HANDLE;
    }
    if (descriptor_set_layout_ != VK_NULL_HANDLE)
    {
        vkDestroyDescriptorSetLayout(device, descriptor_set_layout_, nullptr);
        descriptor_set_layout_ = VK_NULL_HANDLE;
    }
    if (sampler_ != VK_NULL_HANDLE)
    {
        vkDestroySampler(device, sampler_, nullptr);
        sampler_ = VK_NULL_HANDLE;
    }
    device_image_.reset();
}

Resolution QuadLayer::resolution() const noexcept
{
    return config_.resolution;
}

PixelFormat QuadLayer::format() const noexcept
{
    return config_.format;
}

namespace
{

// Guard for public methods that touch resources owned by init(): once
// destroy() has run, device_image_ is the canonical "alive" signal
// (it's the first thing init() builds and the last thing destroy()
// resets). Throwing logic_error converts use-after-destroy from a
// silent null-deref into a clean failure callers can catch in tests.
void require_alive(const std::unique_ptr<DeviceImage>& device_image, const char* what)
{
    if (!device_image)
    {
        throw std::logic_error(std::string("QuadLayer::") + what + " called after destroy()");
    }
}

} // namespace

void QuadLayer::submit(const VizBuffer& src, cudaStream_t stream)
{
    require_alive(device_image_, "submit");
    // Single-producer-thread contract (see header): a load suffices
    // because submit / acquire / release don't race against each
    // other — only against the render thread's record(), which
    // doesn't mutate this flag.
    if (acquired_.load(std::memory_order_acquire))
    {
        throw std::logic_error("QuadLayer::submit called while a Mode B acquire() is in flight");
    }
    if (src.space != MemorySpace::kDevice)
    {
        throw std::invalid_argument("QuadLayer::submit: src must be MemorySpace::kDevice");
    }
    if (src.width != config_.resolution.width || src.height != config_.resolution.height)
    {
        throw std::invalid_argument("QuadLayer::submit: src dimensions do not match layer resolution");
    }
    if (src.format != config_.format)
    {
        throw std::invalid_argument("QuadLayer::submit: src format does not match layer format");
    }
    if (src.data == nullptr)
    {
        throw std::invalid_argument("QuadLayer::submit: src.data is null");
    }

    // Pin the calling thread to ctx's CUDA device.
    check_cuda(cudaSetDevice(ctx_->cuda_device_id()), "cudaSetDevice");

    // wait → copy → signal, all on `stream`. With a non-default
    // stream the caller can interleave their own work on the same
    // stream and the signal will correctly land after it.
    device_image_->cuda_wait_for_vk_read(stream);

    const size_t row_bytes = static_cast<size_t>(src.width) * bytes_per_pixel(src.format);
    const size_t src_pitch = (src.pitch == 0) ? row_bytes : src.pitch;
    check_cuda(cudaMemcpy2DToArrayAsync(device_image_->cuda_array(), 0, 0, src.data, src_pitch, row_bytes, src.height,
                                        cudaMemcpyDeviceToDevice, stream),
               "cudaMemcpy2DToArrayAsync");

    device_image_->cuda_signal_write_done(stream);
}

VizCudaArray QuadLayer::acquire(cudaStream_t stream)
{
    require_alive(device_image_, "acquire");
    // Single-producer-thread contract: a load+store pair is safe.
    // Catches double-acquire as programmer error on this thread.
    if (acquired_.load(std::memory_order_acquire))
    {
        throw std::logic_error("QuadLayer::acquire called while a previous acquire() is still in flight");
    }
    check_cuda(cudaSetDevice(ctx_->cuda_device_id()), "cudaSetDevice");

    // Queue the wait on `stream` so the caller's first cuda* call
    // afterwards is correctly ordered after the previous render.
    // Only flip acquired_ AFTER the wait has been queued so a wait
    // failure doesn't leave the state machine in the "acquired but
    // not actually wired" state.
    device_image_->cuda_wait_for_vk_read(stream);
    acquired_.store(true, std::memory_order_release);

    VizCudaArray view{};
    view.array = device_image_->cuda_array();
    view.width = config_.resolution.width;
    view.height = config_.resolution.height;
    view.format = config_.format;
    return view;
}

void QuadLayer::release(cudaStream_t stream)
{
    require_alive(device_image_, "release");
    if (!acquired_.load(std::memory_order_acquire))
    {
        throw std::logic_error("QuadLayer::release called without a prior acquire()");
    }
    check_cuda(cudaSetDevice(ctx_->cuda_device_id()), "cudaSetDevice");
    // Signal first so the cuda_done_writing counter advances only
    // after the signal is actually queued. If the signal call
    // throws, leave acquired_=true so the caller can retry release()
    // or call destroy(); the state machine stays consistent.
    device_image_->cuda_signal_write_done(stream);
    acquired_.store(false, std::memory_order_release);
}

std::vector<LayerBase::WaitSemaphore> QuadLayer::get_wait_semaphores() const
{
    if (!device_image_)
    {
        return {};
    }
    // Wait for cuda_done_writing >= the value CUDA last committed.
    return {
        WaitSemaphore{
            device_image_->cuda_done_writing(),
            device_image_->cuda_done_writing_value(),
            VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,
        },
    };
}

std::vector<LayerBase::SignalSemaphore> QuadLayer::get_signal_semaphores()
{
    if (!device_image_)
    {
        return {};
    }
    // Reserve a vk_done_reading value but DON'T commit yet — only
    // commit_pending_signals() (called by VizCompositor after a
    // successful vkQueueSubmit) advances the public timeline value.
    pending_vk_signal_value_ = device_image_->reserve_vk_done_reading();
    return {
        SignalSemaphore{
            device_image_->vk_done_reading(),
            pending_vk_signal_value_,
        },
    };
}

void QuadLayer::commit_pending_signals()
{
    if (!device_image_ || pending_vk_signal_value_ == 0)
    {
        return;
    }
    device_image_->commit_vk_done_reading(pending_vk_signal_value_);
    pending_vk_signal_value_ = 0;
}

void QuadLayer::record(VkCommandBuffer cmd, const std::vector<ViewInfo>& /*views*/, const RenderTarget& target)
{
    require_alive(device_image_, "record");
    if (acquired_.load(std::memory_order_acquire))
    {
        throw std::logic_error(
            "QuadLayer::record called while a Mode B acquire() is in flight; "
            "caller must release() before render()");
    }
    const Resolution res = target.resolution();

    VkViewport viewport{};
    viewport.x = 0.0f;
    viewport.y = 0.0f;
    viewport.width = static_cast<float>(res.width);
    viewport.height = static_cast<float>(res.height);
    viewport.minDepth = 0.0f;
    viewport.maxDepth = 1.0f;
    vkCmdSetViewport(cmd, 0, 1, &viewport);

    VkRect2D scissor{};
    scissor.offset = { 0, 0 };
    scissor.extent = { res.width, res.height };
    vkCmdSetScissor(cmd, 0, 1, &scissor);

    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline_);
    vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline_layout_, 0, 1, &descriptor_set_, 0, nullptr);

    // 3 vertices, no vertex buffer — vertex shader emits a fullscreen
    // triangle from gl_VertexIndex.
    vkCmdDraw(cmd, 3, 1, 0, 0);
}

void QuadLayer::create_sampler()
{
    VkSamplerCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO;
    info.magFilter = VK_FILTER_LINEAR;
    info.minFilter = VK_FILTER_LINEAR;
    info.mipmapMode = VK_SAMPLER_MIPMAP_MODE_NEAREST;
    info.addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    info.addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    info.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    info.anisotropyEnable = VK_FALSE; // enable later when XR distance views need it
    info.maxAnisotropy = 1.0f;
    info.borderColor = VK_BORDER_COLOR_INT_OPAQUE_BLACK;
    info.unnormalizedCoordinates = VK_FALSE;
    info.compareEnable = VK_FALSE;
    info.compareOp = VK_COMPARE_OP_ALWAYS;
    info.minLod = 0.0f;
    info.maxLod = 0.0f;
    check_vk(vkCreateSampler(ctx_->device(), &info, nullptr, &sampler_), "vkCreateSampler");
}

void QuadLayer::create_descriptor_set_layout()
{
    VkDescriptorSetLayoutBinding binding{};
    binding.binding = 0;
    binding.descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    binding.descriptorCount = 1;
    binding.stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;
    binding.pImmutableSamplers = nullptr;

    VkDescriptorSetLayoutCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
    info.bindingCount = 1;
    info.pBindings = &binding;
    check_vk(vkCreateDescriptorSetLayout(ctx_->device(), &info, nullptr, &descriptor_set_layout_),
             "vkCreateDescriptorSetLayout");
}

void QuadLayer::create_pipeline_layout()
{
    VkPipelineLayoutCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    info.setLayoutCount = 1;
    info.pSetLayouts = &descriptor_set_layout_;
    info.pushConstantRangeCount = 0;
    check_vk(vkCreatePipelineLayout(ctx_->device(), &info, nullptr, &pipeline_layout_), "vkCreatePipelineLayout");
}

void QuadLayer::create_pipeline()
{
    const VkDevice device = ctx_->device();

    VkShaderModule vert =
        create_shader_module(device, viz::shaders::kTexturedQuadVertSpv, viz::shaders::kTexturedQuadVertSpvSize);
    VkShaderModule frag =
        create_shader_module(device, viz::shaders::kTexturedQuadFragSpv, viz::shaders::kTexturedQuadFragSpvSize);

    // RAII: shader modules are only needed during pipeline creation.
    struct ShaderGuard
    {
        VkDevice device;
        VkShaderModule vert;
        VkShaderModule frag;
        ~ShaderGuard()
        {
            if (vert != VK_NULL_HANDLE)
            {
                vkDestroyShaderModule(device, vert, nullptr);
            }
            if (frag != VK_NULL_HANDLE)
            {
                vkDestroyShaderModule(device, frag, nullptr);
            }
        }
    } guard{ device, vert, frag };

    VkPipelineShaderStageCreateInfo stages[2]{};
    stages[0].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[0].stage = VK_SHADER_STAGE_VERTEX_BIT;
    stages[0].module = vert;
    stages[0].pName = "main";
    stages[1].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[1].stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    stages[1].module = frag;
    stages[1].pName = "main";

    VkPipelineVertexInputStateCreateInfo vertex_input{};
    vertex_input.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;

    VkPipelineInputAssemblyStateCreateInfo input_assembly{};
    input_assembly.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
    input_assembly.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;

    // Viewport / scissor are dynamic so one pipeline works across
    // resolutions.
    VkPipelineViewportStateCreateInfo viewport_state{};
    viewport_state.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
    viewport_state.viewportCount = 1;
    viewport_state.scissorCount = 1;

    VkPipelineRasterizationStateCreateInfo rasterizer{};
    rasterizer.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
    rasterizer.polygonMode = VK_POLYGON_MODE_FILL;
    rasterizer.cullMode = VK_CULL_MODE_NONE;
    rasterizer.frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE;
    rasterizer.lineWidth = 1.0f;

    VkPipelineMultisampleStateCreateInfo multisample{};
    multisample.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
    multisample.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;

    // Depth disabled — fullscreen blits don't need it.
    VkPipelineDepthStencilStateCreateInfo depth_stencil{};
    depth_stencil.sType = VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO;
    depth_stencil.depthTestEnable = VK_FALSE;
    depth_stencil.depthWriteEnable = VK_FALSE;

    VkPipelineColorBlendAttachmentState blend_attachment{};
    blend_attachment.blendEnable = VK_FALSE;
    blend_attachment.colorWriteMask =
        VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT | VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT;

    VkPipelineColorBlendStateCreateInfo color_blend{};
    color_blend.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
    color_blend.attachmentCount = 1;
    color_blend.pAttachments = &blend_attachment;

    const VkDynamicState dynamic_states[] = { VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR };
    VkPipelineDynamicStateCreateInfo dynamic{};
    dynamic.sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO;
    dynamic.dynamicStateCount = sizeof(dynamic_states) / sizeof(dynamic_states[0]);
    dynamic.pDynamicStates = dynamic_states;

    VkGraphicsPipelineCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
    info.stageCount = 2;
    info.pStages = stages;
    info.pVertexInputState = &vertex_input;
    info.pInputAssemblyState = &input_assembly;
    info.pViewportState = &viewport_state;
    info.pRasterizationState = &rasterizer;
    info.pMultisampleState = &multisample;
    info.pDepthStencilState = &depth_stencil;
    info.pColorBlendState = &color_blend;
    info.pDynamicState = &dynamic;
    info.layout = pipeline_layout_;
    info.renderPass = render_pass_;
    info.subpass = 0;

    check_vk(vkCreateGraphicsPipelines(device, ctx_->pipeline_cache(), 1, &info, nullptr, &pipeline_),
             "vkCreateGraphicsPipelines");
}

void QuadLayer::create_descriptor_pool()
{
    VkDescriptorPoolSize pool_size{};
    pool_size.type = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    pool_size.descriptorCount = 1;

    VkDescriptorPoolCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
    info.maxSets = 1;
    info.poolSizeCount = 1;
    info.pPoolSizes = &pool_size;
    check_vk(vkCreateDescriptorPool(ctx_->device(), &info, nullptr, &descriptor_pool_), "vkCreateDescriptorPool");
}

void QuadLayer::allocate_descriptor_set()
{
    VkDescriptorSetAllocateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
    info.descriptorPool = descriptor_pool_;
    info.descriptorSetCount = 1;
    info.pSetLayouts = &descriptor_set_layout_;
    check_vk(vkAllocateDescriptorSets(ctx_->device(), &info, &descriptor_set_), "vkAllocateDescriptorSets");
}

void QuadLayer::update_descriptor_set()
{
    VkDescriptorImageInfo image_info{};
    image_info.sampler = sampler_;
    image_info.imageView = device_image_->vk_image_view();
    image_info.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;

    VkWriteDescriptorSet write{};
    write.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
    write.dstSet = descriptor_set_;
    write.dstBinding = 0;
    write.dstArrayElement = 0;
    write.descriptorCount = 1;
    write.descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    write.pImageInfo = &image_info;

    vkUpdateDescriptorSets(ctx_->device(), 1, &write, 0, nullptr);
}

} // namespace viz
