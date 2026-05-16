// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <viz/core/render_target.hpp>
#include <viz/core/vk_context.hpp>
#include <viz/layers/projection_layer.hpp>
#include <viz/session/viz_session.hpp>
#include <viz/shaders/projection_layer.frag.spv.h>
#include <viz/shaders/projection_layer.vert.spv.h>
#include <viz/shaders/projection_layer_no_depth.frag.spv.h>

#include <algorithm>
#include <cstring>
#include <stdexcept>
#include <utility>

namespace viz
{

namespace
{

void check_vk(VkResult result, const char* what)
{
    if (result != VK_SUCCESS)
    {
        throw std::runtime_error(std::string("ProjectionLayer: ") + what + " failed: VkResult=" + std::to_string(result));
    }
}

void check_cuda(cudaError_t result, const char* what)
{
    if (result != cudaSuccess)
    {
        throw std::runtime_error(std::string("ProjectionLayer: ") + what + " failed: " + cudaGetErrorString(result));
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

ProjectionLayer::ProjectionLayer(const VkContext& ctx, VkRenderPass render_pass, Config config)
    : LayerBase(config.name), ctx_(&ctx), render_pass_(render_pass), config_(std::move(config))
{
    if (!ctx.is_initialized())
    {
        throw std::invalid_argument("ProjectionLayer: VkContext not initialized");
    }
    if (render_pass == VK_NULL_HANDLE)
    {
        throw std::invalid_argument("ProjectionLayer: render_pass is VK_NULL_HANDLE");
    }
    if (config_.view_resolution.width == 0 || config_.view_resolution.height == 0)
    {
        throw std::invalid_argument("ProjectionLayer: view_resolution must be non-zero");
    }
    if (config_.color_format != PixelFormat::kRGBA8)
    {
        throw std::invalid_argument("ProjectionLayer: color_format must be kRGBA8");
    }
    if (config_.depth_format.has_value() && config_.depth_format.value() != PixelFormat::kD32F)
    {
        throw std::invalid_argument("ProjectionLayer: depth_format must be kD32F or nullopt");
    }
    view_count_ = config_.stereo ? 2u : 1u;
    has_depth_ = config_.depth_format.has_value();
    for (auto& slot : in_use_)
    {
        slot.store(kSlotNone, std::memory_order_relaxed);
    }
    init();
}

ProjectionLayer::~ProjectionLayer()
{
    destroy();
}

void ProjectionLayer::init()
{
    try
    {
        for (uint32_t s = 0; s < kSlotCount; ++s)
        {
            slots_color_[s].reserve(view_count_);
            for (uint32_t v = 0; v < view_count_; ++v)
            {
                slots_color_[s].push_back(DeviceImage::create(*ctx_, config_.view_resolution, config_.color_format, 1));
            }
            if (has_depth_)
            {
                slots_depth_[s].reserve(view_count_);
                for (uint32_t v = 0; v < view_count_; ++v)
                {
                    slots_depth_[s].push_back(
                        DeviceImage::create(*ctx_, config_.view_resolution, *config_.depth_format, 1));
                }
            }
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

void ProjectionLayer::destroy()
{
    // Drain pending GPU work before tearing down resources the
    // compositor's command buffers reference.
    if (ctx_ != nullptr && ctx_->device() != VK_NULL_HANDLE)
    {
        (void)vkDeviceWaitIdle(ctx_->device());
    }

    const VkDevice device = (ctx_ != nullptr) ? ctx_->device() : VK_NULL_HANDLE;
    if (device != VK_NULL_HANDLE)
    {
        if (pipeline_with_depth_ != VK_NULL_HANDLE)
        {
            vkDestroyPipeline(device, pipeline_with_depth_, nullptr);
            pipeline_with_depth_ = VK_NULL_HANDLE;
        }
        if (pipeline_no_depth_ != VK_NULL_HANDLE)
        {
            vkDestroyPipeline(device, pipeline_no_depth_, nullptr);
            pipeline_no_depth_ = VK_NULL_HANDLE;
        }
        if (pipeline_layout_ != VK_NULL_HANDLE)
        {
            vkDestroyPipelineLayout(device, pipeline_layout_, nullptr);
            pipeline_layout_ = VK_NULL_HANDLE;
        }
        if (descriptor_pool_ != VK_NULL_HANDLE)
        {
            vkDestroyDescriptorPool(device, descriptor_pool_, nullptr);
            descriptor_pool_ = VK_NULL_HANDLE;
        }
        for (auto& sets : descriptor_sets_)
        {
            sets.clear();
        }
        if (descriptor_set_layout_ != VK_NULL_HANDLE)
        {
            vkDestroyDescriptorSetLayout(device, descriptor_set_layout_, nullptr);
            descriptor_set_layout_ = VK_NULL_HANDLE;
        }
        if (color_sampler_ != VK_NULL_HANDLE)
        {
            vkDestroySampler(device, color_sampler_, nullptr);
            color_sampler_ = VK_NULL_HANDLE;
        }
        if (depth_sampler_ != VK_NULL_HANDLE)
        {
            vkDestroySampler(device, depth_sampler_, nullptr);
            depth_sampler_ = VK_NULL_HANDLE;
        }
    }
    for (uint32_t s = 0; s < kSlotCount; ++s)
    {
        slots_color_[s].clear();
        slots_depth_[s].clear();
    }
}

// ─── Vulkan setup ────────────────────────────────────────────────────

void ProjectionLayer::create_sampler()
{
    const VkDevice device = ctx_->device();

    VkSamplerCreateInfo color_info{};
    color_info.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO;
    color_info.magFilter = VK_FILTER_LINEAR;
    color_info.minFilter = VK_FILTER_LINEAR;
    color_info.mipmapMode = VK_SAMPLER_MIPMAP_MODE_NEAREST;
    color_info.addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    color_info.addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    color_info.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    color_info.borderColor = VK_BORDER_COLOR_FLOAT_TRANSPARENT_BLACK;
    check_vk(vkCreateSampler(device, &color_info, nullptr, &color_sampler_), "vkCreateSampler(color)");

    VkSamplerCreateInfo depth_info = color_info;
    depth_info.magFilter = VK_FILTER_NEAREST;
    depth_info.minFilter = VK_FILTER_NEAREST;
    check_vk(vkCreateSampler(device, &depth_info, nullptr, &depth_sampler_), "vkCreateSampler(depth)");
}

void ProjectionLayer::create_descriptor_set_layout()
{
    // Binding 0: color, Binding 1: depth.
    // When has_depth_ is false the descriptor at binding 1 still gets
    // written (with the color image) so the layout shape stays uniform
    // across both pipeline variants; the no_depth fragment shader
    // doesn't sample it.
    std::array<VkDescriptorSetLayoutBinding, 2> bindings{};
    bindings[0].binding = 0;
    bindings[0].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    bindings[0].descriptorCount = 1;
    bindings[0].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;
    bindings[1].binding = 1;
    bindings[1].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    bindings[1].descriptorCount = 1;
    bindings[1].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;

    VkDescriptorSetLayoutCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
    info.bindingCount = static_cast<uint32_t>(bindings.size());
    info.pBindings = bindings.data();
    check_vk(vkCreateDescriptorSetLayout(ctx_->device(), &info, nullptr, &descriptor_set_layout_),
             "vkCreateDescriptorSetLayout");
}

void ProjectionLayer::create_pipeline_layout()
{
    VkPipelineLayoutCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    info.setLayoutCount = 1;
    info.pSetLayouts = &descriptor_set_layout_;
    check_vk(vkCreatePipelineLayout(ctx_->device(), &info, nullptr, &pipeline_layout_), "vkCreatePipelineLayout");
}

void ProjectionLayer::create_pipeline()
{
    const VkDevice device = ctx_->device();

    VkShaderModule vert =
        create_shader_module(device, viz::shaders::kProjectionLayerVertSpv, viz::shaders::kProjectionLayerVertSpvSize);

    struct ShaderGuard
    {
        VkDevice device;
        VkShaderModule vert;
        VkShaderModule frag_with_depth;
        VkShaderModule frag_no_depth;
        ~ShaderGuard()
        {
            for (auto m : { vert, frag_with_depth, frag_no_depth })
            {
                if (m != VK_NULL_HANDLE)
                {
                    vkDestroyShaderModule(device, m, nullptr);
                }
            }
        }
    } guard{ device, vert, VK_NULL_HANDLE, VK_NULL_HANDLE };
    guard.frag_with_depth =
        create_shader_module(device, viz::shaders::kProjectionLayerFragSpv, viz::shaders::kProjectionLayerFragSpvSize);
    guard.frag_no_depth = create_shader_module(
        device, viz::shaders::kProjectionLayerFragNoDepthSpv, viz::shaders::kProjectionLayerFragNoDepthSpvSize);

    auto make_pipeline = [&](VkShaderModule frag_module, bool depth_write, VkPipeline* out)
    {
        VkPipelineShaderStageCreateInfo stages[2]{};
        stages[0].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
        stages[0].stage = VK_SHADER_STAGE_VERTEX_BIT;
        stages[0].module = vert;
        stages[0].pName = "main";
        stages[1].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
        stages[1].stage = VK_SHADER_STAGE_FRAGMENT_BIT;
        stages[1].module = frag_module;
        stages[1].pName = "main";

        VkPipelineVertexInputStateCreateInfo vertex_input{};
        vertex_input.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;

        VkPipelineInputAssemblyStateCreateInfo input_assembly{};
        input_assembly.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
        input_assembly.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP;

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

        // depth_write true: frag writes gl_FragDepth from the sampled
        // depth texture. depth_write false: rasterized z = 1.0 (far)
        // from the vertex shader; doesn't affect subsequent layers.
        VkPipelineDepthStencilStateCreateInfo depth_stencil{};
        depth_stencil.sType = VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO;
        depth_stencil.depthTestEnable = VK_TRUE;
        depth_stencil.depthWriteEnable = depth_write ? VK_TRUE : VK_FALSE;
        depth_stencil.depthCompareOp = VK_COMPARE_OP_LESS_OR_EQUAL;

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

        check_vk(vkCreateGraphicsPipelines(device, ctx_->pipeline_cache(), 1, &info, nullptr, out),
                 "vkCreateGraphicsPipelines");
    };

    make_pipeline(guard.frag_with_depth, /*depth_write=*/true, &pipeline_with_depth_);
    make_pipeline(guard.frag_no_depth, /*depth_write=*/false, &pipeline_no_depth_);
}

void ProjectionLayer::create_descriptor_pool()
{
    const uint32_t set_count = kSlotCount * view_count_;
    // Two combined samplers per set (color + depth slot, even when
    // depth disabled — descriptor count must match the layout).
    VkDescriptorPoolSize pool_size{};
    pool_size.type = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    pool_size.descriptorCount = set_count * 2u;

    VkDescriptorPoolCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
    info.maxSets = set_count;
    info.poolSizeCount = 1;
    info.pPoolSizes = &pool_size;
    check_vk(vkCreateDescriptorPool(ctx_->device(), &info, nullptr, &descriptor_pool_), "vkCreateDescriptorPool");
}

void ProjectionLayer::allocate_descriptor_sets()
{
    std::vector<VkDescriptorSetLayout> layouts(view_count_, descriptor_set_layout_);
    for (uint32_t s = 0; s < kSlotCount; ++s)
    {
        descriptor_sets_[s].resize(view_count_);
        VkDescriptorSetAllocateInfo info{};
        info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
        info.descriptorPool = descriptor_pool_;
        info.descriptorSetCount = view_count_;
        info.pSetLayouts = layouts.data();
        check_vk(vkAllocateDescriptorSets(ctx_->device(), &info, descriptor_sets_[s].data()), "vkAllocateDescriptorSets");
    }
}

void ProjectionLayer::update_descriptor_sets()
{
    const VkDevice device = ctx_->device();
    std::vector<VkWriteDescriptorSet> writes;
    std::vector<VkDescriptorImageInfo> infos;
    writes.reserve(kSlotCount * view_count_ * 2u);
    infos.reserve(kSlotCount * view_count_ * 2u);

    for (uint32_t s = 0; s < kSlotCount; ++s)
    {
        for (uint32_t v = 0; v < view_count_; ++v)
        {
            VkDescriptorImageInfo color_info{};
            color_info.sampler = color_sampler_;
            color_info.imageView = slots_color_[s][v]->vk_image_view();
            color_info.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
            infos.push_back(color_info);
            VkWriteDescriptorSet w{};
            w.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
            w.dstSet = descriptor_sets_[s][v];
            w.dstBinding = 0;
            w.descriptorCount = 1;
            w.descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
            w.pImageInfo = &infos.back();
            writes.push_back(w);

            VkDescriptorImageInfo depth_info{};
            depth_info.sampler = has_depth_ ? depth_sampler_ : color_sampler_;
            depth_info.imageView = has_depth_ ? slots_depth_[s][v]->vk_image_view() : slots_color_[s][v]->vk_image_view();
            depth_info.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
            infos.push_back(depth_info);
            VkWriteDescriptorSet w2 = w;
            w2.dstBinding = 1;
            w2.pImageInfo = &infos.back();
            writes.push_back(w2);
        }
    }
    vkUpdateDescriptorSets(device, static_cast<uint32_t>(writes.size()), writes.data(), 0, nullptr);
}

// ─── Submit ──────────────────────────────────────────────────────────

void ProjectionLayer::validate_submit_buffer(const VizBuffer& buf, PixelFormat expected_format, const char* label) const
{
    if (buf.data == nullptr)
    {
        throw std::invalid_argument(std::string("ProjectionLayer: ") + label + ": data is null");
    }
    if (buf.space != MemorySpace::kDevice)
    {
        throw std::invalid_argument(std::string("ProjectionLayer: ") + label + ": MemorySpace must be kDevice");
    }
    if (buf.format != expected_format)
    {
        throw std::invalid_argument(std::string("ProjectionLayer: ") + label + ": pixel format mismatch");
    }
    if (buf.width != config_.view_resolution.width || buf.height != config_.view_resolution.height)
    {
        throw std::invalid_argument(std::string("ProjectionLayer: ") + label + ": resolution mismatch");
    }
}

void ProjectionLayer::enqueue_copy(const VizBuffer& src, DeviceImage& dst, cudaStream_t stream) const
{
    const size_t row_bytes = static_cast<size_t>(src.width) * bytes_per_pixel(src.format);
    const size_t src_pitch = (src.pitch != 0) ? src.pitch : row_bytes;
    check_cuda(cudaMemcpy2DToArrayAsync(dst.cuda_array(),
                                        /*wOffset=*/0,
                                        /*hOffset=*/0, src.data, src_pitch, row_bytes, src.height,
                                        cudaMemcpyDeviceToDevice, stream),
               "cudaMemcpy2DToArrayAsync");
}

uint8_t ProjectionLayer::pick_free_slot() const noexcept
{
    const uint8_t latest = latest_.load(std::memory_order_acquire);
    for (uint8_t s = 0; s < static_cast<uint8_t>(kSlotCount); ++s)
    {
        if (s == latest)
        {
            continue;
        }
        bool used = false;
        for (const auto& a : in_use_)
        {
            if (a.load(std::memory_order_acquire) == s)
            {
                used = true;
                break;
            }
        }
        if (!used)
        {
            return s;
        }
    }
    return kSlotNone;
}

void ProjectionLayer::submit(const VizBuffer& left_color,
                             const VizBuffer* left_depth,
                             const VizBuffer* right_color,
                             const VizBuffer* right_depth,
                             cudaStream_t stream)
{
    // ── Validate config / call shape ─────────────────────────────────
    validate_submit_buffer(left_color, config_.color_format, "submit(left_color)");

    const bool stereo = config_.stereo;
    if (stereo)
    {
        if (right_color == nullptr)
        {
            throw std::invalid_argument("ProjectionLayer: stereo layer requires right_color");
        }
        validate_submit_buffer(*right_color, config_.color_format, "submit(right_color)");
    }
    else
    {
        if (right_color != nullptr || right_depth != nullptr)
        {
            throw std::invalid_argument("ProjectionLayer: mono layer must not pass right buffers");
        }
    }

    if (has_depth_)
    {
        if (left_depth == nullptr)
        {
            throw std::invalid_argument("ProjectionLayer: depth-enabled layer requires left_depth");
        }
        validate_submit_buffer(*left_depth, PixelFormat::kD32F, "submit(left_depth)");
        if (stereo)
        {
            if (right_depth == nullptr)
            {
                throw std::invalid_argument("ProjectionLayer: stereo + depth requires right_depth");
            }
            validate_submit_buffer(*right_depth, PixelFormat::kD32F, "submit(right_depth)");
        }
    }
    else
    {
        if (left_depth != nullptr || right_depth != nullptr)
        {
            throw std::invalid_argument("ProjectionLayer: depth-disabled layer must not pass depth buffers");
        }
    }

    // ── Pick a free slot ─────────────────────────────────────────────
    const uint8_t slot = pick_free_slot();
    if (slot == kSlotNone)
    {
        // Should be unreachable given the kSlotCount invariant
        // (kMaxFramesInFlight + 2 ≥ worst-case forbidden set + 1).
        // Treat as a drop: producer's frame is lost; renderer keeps
        // sampling the previous publish.
        throw std::runtime_error("ProjectionLayer: no free mailbox slot — sizing invariant violated");
    }

    // ── Copy + signal ────────────────────────────────────────────────
    enqueue_copy(left_color, *slots_color_[slot][0], stream);
    if (has_depth_)
    {
        enqueue_copy(*left_depth, *slots_depth_[slot][0], stream);
    }
    if (stereo)
    {
        enqueue_copy(*right_color, *slots_color_[slot][1], stream);
        if (has_depth_)
        {
            enqueue_copy(*right_depth, *slots_depth_[slot][1], stream);
        }
    }

    // One semaphore signal per CUDA-mapped image we wrote. The compositor
    // waits on the in-use slot's set of cuda_done_writing values before
    // the fragment shader samples them (get_wait_semaphores).
    slots_color_[slot][0]->cuda_signal_write_done(stream);
    if (has_depth_)
    {
        slots_depth_[slot][0]->cuda_signal_write_done(stream);
    }
    if (stereo)
    {
        slots_color_[slot][1]->cuda_signal_write_done(stream);
        if (has_depth_)
        {
            slots_depth_[slot][1]->cuda_signal_write_done(stream);
        }
    }

    // BLOCK on stream completion so the caller can re-use src buffers
    // immediately. Same contract as QuadLayer::submit. ~sub-ms cost.
    check_cuda(cudaStreamSynchronize(stream), "cudaStreamSynchronize");

    latest_.store(slot, std::memory_order_release);
    submitted_this_frame_.store(true, std::memory_order_release);
}

// ─── Render path ─────────────────────────────────────────────────────

void ProjectionLayer::on_frame_begin()
{
    // VizSession's begin_frame calls this on every layer. Clearing
    // the flag here means a layer that fails to submit between
    // begin_frame and end_frame will be skipped at record() time in
    // kXr (see record() below).
    submitted_this_frame_.store(false, std::memory_order_release);
}

void ProjectionLayer::record_pre_render_pass(VkCommandBuffer /*cmd*/, uint32_t in_flight_slot)
{
    if (in_flight_slot >= kMaxFramesInFlight)
    {
        throw std::logic_error("ProjectionLayer: in_flight_slot exceeds kMaxFramesInFlight");
    }
    const uint8_t latest = latest_.load(std::memory_order_acquire);
    if (latest != kSlotNone)
    {
        in_use_[in_flight_slot].store(latest, std::memory_order_release);
    }
    last_in_use_slot_.store(in_use_[in_flight_slot].load(std::memory_order_acquire), std::memory_order_release);
}

void ProjectionLayer::record(VkCommandBuffer cmd,
                             const std::vector<ViewInfo>& views,
                             const RenderTarget& /*target*/,
                             uint32_t in_flight_slot)
{
    if (in_flight_slot >= kMaxFramesInFlight)
    {
        throw std::logic_error("ProjectionLayer: in_flight_slot exceeds kMaxFramesInFlight");
    }
    const uint8_t cur = in_use_[in_flight_slot].load(std::memory_order_acquire);
    if (cur == kSlotNone)
    {
        return;
    }

    // In kXr, a layer whose renderer didn't submit for THIS frame
    // must not contribute stale RGBD under a new projection-layer
    // pose. Skip the draw — the layer's region of the shared RT
    // keeps the clear color. kWindow / kOffscreen don't have an XR
    // pose, so the freshness gate is off (latest-wins semantics
    // match QuadLayer).
    const bool xr_mode = session() != nullptr && session()->is_xr_mode();
    if (xr_mode && !submitted_this_frame_.load(std::memory_order_acquire))
    {
        return;
    }

    VkPipeline pipeline = has_depth_ ? pipeline_with_depth_ : pipeline_no_depth_;
    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline);

    for (size_t view_idx = 0; view_idx < views.size(); ++view_idx)
    {
        const auto& view = views[view_idx];
        bind_view_viewport(cmd, view);

        // Stereo + kXr: view 0 → LEFT slot, view 1 → RIGHT slot.
        // Otherwise: always LEFT (mono content broadcast to both eyes
        // in stereo + window/offscreen).
        const bool sample_right = xr_mode && config_.stereo && view_idx == 1 && view_count_ >= 2;
        const uint32_t slot_view = sample_right ? 1u : 0u;
        VkDescriptorSet ds = descriptor_sets_[cur][slot_view];
        vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline_layout_, 0, 1, &ds, 0, nullptr);

        // 3-vertex oversized fullscreen triangle (same trick as
        // textured_quad.vert's mode == 0 branch).
        vkCmdDraw(cmd, 3, 1, 0, 0);
    }
}

std::vector<LayerBase::WaitSemaphore> ProjectionLayer::get_wait_semaphores() const
{
    std::vector<WaitSemaphore> waits;
    const uint8_t cur = last_in_use_slot_.load(std::memory_order_acquire);
    if (cur == kSlotNone)
    {
        return waits;
    }
    const auto add = [&](const DeviceImage& img)
    {
        const uint64_t value = img.cuda_done_writing_value();
        if (value == 0)
        {
            return;
        }
        WaitSemaphore w{};
        w.semaphore = img.cuda_done_writing();
        w.value = value;
        w.wait_stage = VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT;
        waits.push_back(w);
    };
    for (uint32_t v = 0; v < view_count_; ++v)
    {
        if (slots_color_[cur].size() > v && slots_color_[cur][v])
        {
            add(*slots_color_[cur][v]);
        }
        if (has_depth_ && slots_depth_[cur].size() > v && slots_depth_[cur][v])
        {
            add(*slots_depth_[cur][v]);
        }
    }
    return waits;
}

// ─── Accessors ───────────────────────────────────────────────────────

Resolution ProjectionLayer::view_resolution() const noexcept
{
    return config_.view_resolution;
}

PixelFormat ProjectionLayer::color_format() const noexcept
{
    return config_.color_format;
}

std::optional<PixelFormat> ProjectionLayer::depth_format() const noexcept
{
    return config_.depth_format;
}

bool ProjectionLayer::is_stereo() const noexcept
{
    return config_.stereo;
}

uint32_t ProjectionLayer::view_count() const noexcept
{
    return view_count_;
}

const DeviceImage* ProjectionLayer::color_image(uint32_t slot, uint32_t view) const noexcept
{
    if (slot >= kSlotCount || view >= view_count_ || slots_color_[slot].size() <= view)
    {
        return nullptr;
    }
    return slots_color_[slot][view].get();
}

const DeviceImage* ProjectionLayer::depth_image(uint32_t slot, uint32_t view) const noexcept
{
    if (!has_depth_ || slot >= kSlotCount || view >= view_count_ || slots_depth_[slot].size() <= view)
    {
        return nullptr;
    }
    return slots_depth_[slot][view].get();
}

} // namespace viz
