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

// Once destroy() has run, slots_[0] is the canonical "alive" signal
// (it's the first thing init() builds and the last thing destroy()
// resets). Throwing logic_error converts use-after-destroy from a
// silent null-deref into a clean failure callers can catch in tests.
void require_alive(const std::unique_ptr<DeviceImage>& slot0, const char* what)
{
    if (!slot0)
    {
        throw std::logic_error(std::string("QuadLayer::") + what + " called after destroy()");
    }
}

} // namespace

QuadLayer::QuadLayer(const VkContext& ctx, VkRenderPass render_pass, Config config)
    : LayerBase(config.name), ctx_(&ctx), render_pass_(render_pass), config_(std::move(config))
{
    // Cheap-first config checks, then argument shape, then context
    // state. Tests can exercise each path by varying just the
    // relevant argument with an uninitialized VkContext.
    if (config_.format != PixelFormat::kRGBA8)
    {
        // textured_quad samples color; depth (kD32F) would create a
        // depth-aspect view that can't be sampled as color.
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
        for (auto& slot : slots_)
        {
            slot = DeviceImage::create(*ctx_, config_.resolution, config_.format);
        }
        create_sampler();
        create_descriptor_set_layout();
        create_pipeline_layout();
        create_pipeline();
        create_descriptor_pool();
        allocate_descriptor_sets();
        update_descriptor_sets();
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
        for (auto& slot : slots_)
        {
            slot.reset();
        }
        return;
    }
    if (descriptor_pool_ != VK_NULL_HANDLE)
    {
        // descriptor_sets_ are freed implicitly with the pool.
        vkDestroyDescriptorPool(device, descriptor_pool_, nullptr);
        descriptor_pool_ = VK_NULL_HANDLE;
        descriptor_sets_.fill(VK_NULL_HANDLE);
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
    for (auto& slot : slots_)
    {
        slot.reset();
    }
    latest_.store(kSlotNone, std::memory_order_release);
    in_use_.store(kSlotNone, std::memory_order_release);
}

Resolution QuadLayer::resolution() const noexcept
{
    return config_.resolution;
}

PixelFormat QuadLayer::format() const noexcept
{
    return config_.format;
}

const DeviceImage* QuadLayer::device_image(uint32_t slot) const noexcept
{
    if (slot >= kSlotCount)
    {
        return nullptr;
    }
    return slots_[slot].get();
}

uint8_t QuadLayer::pick_free_slot(uint8_t latest, uint8_t in_use) const noexcept
{
    // With kSlotCount=3, at most 2 slots are "claimed" (latest +
    // in_use). At least one of {0, 1, 2} is always free.
    static_assert(kSlotCount == 3, "pick_free_slot assumes 3 slots");
    for (uint8_t i = 0; i < kSlotCount; ++i)
    {
        if (i != latest && i != in_use)
        {
            return i;
        }
    }
    return 0; // unreachable for kSlotCount >= 2
}

void QuadLayer::submit(const VizBuffer& src, cudaStream_t stream)
{
    require_alive(slots_[0], "submit");
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

    // Pick a free slot — neither the most recent publish nor the
    // slot the renderer is currently using. With 3 slots there's
    // always one free, so this is wait-free.
    const uint8_t latest = latest_.load(std::memory_order_acquire);
    const uint8_t in_use = in_use_.load(std::memory_order_acquire);
    const uint8_t slot = pick_free_slot(latest, in_use);
    DeviceImage& image = *slots_[slot];

    check_cuda(cudaSetDevice(ctx_->cuda_device_id()), "cudaSetDevice");
    // Async copy on `stream`. Caller's prior work on the same stream
    // is naturally ordered before this; signal lands after the copy
    // completes on the GPU.
    const size_t row_bytes = static_cast<size_t>(src.width) * bytes_per_pixel(src.format);
    const size_t src_pitch = (src.pitch == 0) ? row_bytes : src.pitch;
    check_cuda(cudaMemcpy2DToArrayAsync(image.cuda_array(), 0, 0, src.data, src_pitch, row_bytes, src.height,
                                        cudaMemcpyDeviceToDevice, stream),
               "cudaMemcpy2DToArrayAsync");
    image.cuda_signal_write_done(stream);

    // Publish. The renderer's next record() will atomic-exchange
    // this into in_use_; the previous latest_ slot becomes free.
    // memory_order_release pairs with the renderer's acquire load.
    latest_.store(slot, std::memory_order_release);
}

void QuadLayer::record(VkCommandBuffer cmd, const std::vector<ViewInfo>& /*views*/, const RenderTarget& target)
{
    require_alive(slots_[0], "record");

    // Promote latest_ to in_use_. The previous in_use_ slot becomes
    // free for the next submit(). If no frame has been published yet
    // (latest_ == kSlotNone), we leave in_use_ as-is — if it's also
    // kSlotNone, we skip the draw and the framebuffer keeps its
    // clear value.
    const uint8_t latest = latest_.load(std::memory_order_acquire);
    if (latest != kSlotNone)
    {
        in_use_.store(latest, std::memory_order_release);
    }
    const uint8_t cur = in_use_.load(std::memory_order_acquire);
    if (cur == kSlotNone)
    {
        return;
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
    vkCmdBindDescriptorSets(
        cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline_layout_, 0, 1, &descriptor_sets_[cur], 0, nullptr);

    // 3 vertices, no vertex buffer — vertex shader emits a fullscreen
    // triangle from gl_VertexIndex.
    vkCmdDraw(cmd, 3, 1, 0, 0);
}

std::vector<LayerBase::WaitSemaphore> QuadLayer::get_wait_semaphores() const
{
    // VizCompositor calls record() first (which promotes latest_ ->
    // in_use_), then this. So in_use_ is the slot the draw will
    // sample, and that's what we need the GPU to wait on.
    const uint8_t cur = in_use_.load(std::memory_order_acquire);
    if (cur == kSlotNone || !slots_[cur])
    {
        return {};
    }
    const DeviceImage& image = *slots_[cur];
    const uint64_t value = image.cuda_done_writing_value();
    if (value == 0)
    {
        return {};
    }
    return {
        WaitSemaphore{
            image.cuda_done_writing(),
            value,
            VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,
        },
    };
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
    pool_size.descriptorCount = kSlotCount;

    VkDescriptorPoolCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
    info.maxSets = kSlotCount;
    info.poolSizeCount = 1;
    info.pPoolSizes = &pool_size;
    check_vk(vkCreateDescriptorPool(ctx_->device(), &info, nullptr, &descriptor_pool_), "vkCreateDescriptorPool");
}

void QuadLayer::allocate_descriptor_sets()
{
    std::array<VkDescriptorSetLayout, kSlotCount> layouts{};
    layouts.fill(descriptor_set_layout_);

    VkDescriptorSetAllocateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
    info.descriptorPool = descriptor_pool_;
    info.descriptorSetCount = kSlotCount;
    info.pSetLayouts = layouts.data();
    check_vk(vkAllocateDescriptorSets(ctx_->device(), &info, descriptor_sets_.data()), "vkAllocateDescriptorSets");
}

void QuadLayer::update_descriptor_sets()
{
    // One write per slot, each pointing at the slot's own image view.
    std::array<VkDescriptorImageInfo, kSlotCount> image_infos{};
    std::array<VkWriteDescriptorSet, kSlotCount> writes{};
    for (uint32_t i = 0; i < kSlotCount; ++i)
    {
        image_infos[i].sampler = sampler_;
        image_infos[i].imageView = slots_[i]->vk_image_view();
        image_infos[i].imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;

        writes[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        writes[i].dstSet = descriptor_sets_[i];
        writes[i].dstBinding = 0;
        writes[i].dstArrayElement = 0;
        writes[i].descriptorCount = 1;
        writes[i].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
        writes[i].pImageInfo = &image_infos[i];
    }
    vkUpdateDescriptorSets(ctx_->device(), kSlotCount, writes.data(), 0, nullptr);
}

} // namespace viz
