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

void check_cuda(cudaError_t result, const char* what)
{
    if (result != cudaSuccess)
    {
        throw std::runtime_error(std::string("QuadLayer: ") + what + " failed: " + cudaGetErrorString(result));
    }
}

vk::raii::ShaderModule create_shader_module(const vk::raii::Device& device, const unsigned char* spv, size_t size)
{
    return vk::raii::ShaderModule{ device, vk::ShaderModuleCreateInfo{
                                               .codeSize = size,
                                               .pCode = reinterpret_cast<const uint32_t*>(spv),
                                           } };
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
    // Reverse of init(): descriptor sets back to the pool, pipeline
    // before its layout, sampler last. raii handles the actual
    // destruction order via reset-to-nullptr in declared order
    // (parent-first declaration → reverse runs child-first).
    descriptor_sets_ = nullptr;
    descriptor_pool_ = nullptr;
    pipeline_ = nullptr;
    pipeline_layout_ = nullptr;
    descriptor_set_layout_ = nullptr;
    sampler_ = nullptr;
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

std::optional<float> QuadLayer::aspect_ratio() const noexcept
{
    if (config_.resolution.height == 0)
    {
        return std::nullopt;
    }
    return static_cast<float>(config_.resolution.width) / static_cast<float>(config_.resolution.height);
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

void QuadLayer::record(VkCommandBuffer cmd, const std::vector<ViewInfo>& views, const RenderTarget& /*target*/)
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

    const vk::CommandBuffer cmd_hpp{ cmd };
    cmd_hpp.bindPipeline(vk::PipelineBindPoint::eGraphics, *pipeline_);
    cmd_hpp.bindDescriptorSets(vk::PipelineBindPoint::eGraphics, *pipeline_layout_, 0, *descriptor_sets_[cur], {});

    // 1 view in window/offscreen, 2 in XR stereo. Compositor pre-bound
    // the layer's scissor; we bind viewport per view and draw.
    for (const auto& view : views)
    {
        bind_view_viewport(cmd, view);
        // 3 vertices, no vertex buffer — vertex shader emits a
        // fullscreen triangle from gl_VertexIndex.
        cmd_hpp.draw(3, 1, 0, 0);
    }
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
    sampler_ = vk::raii::Sampler{ ctx_->raii_device(), vk::SamplerCreateInfo{
                                                           .magFilter = vk::Filter::eLinear,
                                                           .minFilter = vk::Filter::eLinear,
                                                           .mipmapMode = vk::SamplerMipmapMode::eNearest,
                                                           .addressModeU = vk::SamplerAddressMode::eClampToEdge,
                                                           .addressModeV = vk::SamplerAddressMode::eClampToEdge,
                                                           .addressModeW = vk::SamplerAddressMode::eClampToEdge,
                                                           .anisotropyEnable = VK_FALSE, // enable later when XR
                                                                                         // distance views need it
                                                           .maxAnisotropy = 1.0f,
                                                           .compareEnable = VK_FALSE,
                                                           .compareOp = vk::CompareOp::eAlways,
                                                           .minLod = 0.0f,
                                                           .maxLod = 0.0f,
                                                           .borderColor = vk::BorderColor::eIntOpaqueBlack,
                                                           .unnormalizedCoordinates = VK_FALSE,
                                                       } };
}

void QuadLayer::create_descriptor_set_layout()
{
    const vk::DescriptorSetLayoutBinding binding{
        .binding = 0,
        .descriptorType = vk::DescriptorType::eCombinedImageSampler,
        .descriptorCount = 1,
        .stageFlags = vk::ShaderStageFlagBits::eFragment,
        .pImmutableSamplers = nullptr,
    };
    descriptor_set_layout_ = vk::raii::DescriptorSetLayout{
        ctx_->raii_device(),
        vk::DescriptorSetLayoutCreateInfo{ .bindingCount = 1, .pBindings = &binding },
    };
}

void QuadLayer::create_pipeline_layout()
{
    const vk::DescriptorSetLayout layout = *descriptor_set_layout_;
    pipeline_layout_ = vk::raii::PipelineLayout{
        ctx_->raii_device(),
        vk::PipelineLayoutCreateInfo{
            .setLayoutCount = 1,
            .pSetLayouts = &layout,
            .pushConstantRangeCount = 0,
        },
    };
}

void QuadLayer::create_pipeline()
{
    const auto& device = ctx_->raii_device();

    const auto vert =
        create_shader_module(device, viz::shaders::kTexturedQuadVertSpv, viz::shaders::kTexturedQuadVertSpvSize);
    const auto frag =
        create_shader_module(device, viz::shaders::kTexturedQuadFragSpv, viz::shaders::kTexturedQuadFragSpvSize);

    const std::array<vk::PipelineShaderStageCreateInfo, 2> stages{
        vk::PipelineShaderStageCreateInfo{ .stage = vk::ShaderStageFlagBits::eVertex, .module = *vert, .pName = "main" },
        vk::PipelineShaderStageCreateInfo{ .stage = vk::ShaderStageFlagBits::eFragment, .module = *frag, .pName = "main" },
    };

    const vk::PipelineVertexInputStateCreateInfo vertex_input{};
    const vk::PipelineInputAssemblyStateCreateInfo input_assembly{ .topology = vk::PrimitiveTopology::eTriangleList };

    // Viewport / scissor are dynamic so one pipeline works across
    // resolutions.
    const vk::PipelineViewportStateCreateInfo viewport_state{ .viewportCount = 1, .scissorCount = 1 };

    const vk::PipelineRasterizationStateCreateInfo rasterizer{
        .polygonMode = vk::PolygonMode::eFill,
        .cullMode = vk::CullModeFlagBits::eNone,
        .frontFace = vk::FrontFace::eCounterClockwise,
        .lineWidth = 1.0f,
    };

    const vk::PipelineMultisampleStateCreateInfo multisample{ .rasterizationSamples = vk::SampleCountFlagBits::e1 };

    // Depth disabled — fullscreen blits don't need it.
    const vk::PipelineDepthStencilStateCreateInfo depth_stencil{
        .depthTestEnable = VK_FALSE,
        .depthWriteEnable = VK_FALSE,
    };

    const vk::PipelineColorBlendAttachmentState blend_attachment{
        .blendEnable = VK_FALSE,
        .colorWriteMask = vk::ColorComponentFlagBits::eR | vk::ColorComponentFlagBits::eG |
                          vk::ColorComponentFlagBits::eB | vk::ColorComponentFlagBits::eA,
    };

    const vk::PipelineColorBlendStateCreateInfo color_blend{
        .attachmentCount = 1,
        .pAttachments = &blend_attachment,
    };

    const std::array<vk::DynamicState, 2> dynamic_states{ vk::DynamicState::eViewport, vk::DynamicState::eScissor };
    const vk::PipelineDynamicStateCreateInfo dynamic{
        .dynamicStateCount = static_cast<uint32_t>(dynamic_states.size()),
        .pDynamicStates = dynamic_states.data(),
    };

    pipeline_ = vk::raii::Pipeline{ device, ctx_->raii_pipeline_cache(),
                                    vk::GraphicsPipelineCreateInfo{
                                        .stageCount = static_cast<uint32_t>(stages.size()),
                                        .pStages = stages.data(),
                                        .pVertexInputState = &vertex_input,
                                        .pInputAssemblyState = &input_assembly,
                                        .pViewportState = &viewport_state,
                                        .pRasterizationState = &rasterizer,
                                        .pMultisampleState = &multisample,
                                        .pDepthStencilState = &depth_stencil,
                                        .pColorBlendState = &color_blend,
                                        .pDynamicState = &dynamic,
                                        .layout = *pipeline_layout_,
                                        .renderPass = render_pass_,
                                        .subpass = 0,
                                    } };
}

void QuadLayer::create_descriptor_pool()
{
    const vk::DescriptorPoolSize pool_size{
        .type = vk::DescriptorType::eCombinedImageSampler,
        .descriptorCount = kSlotCount,
    };
    descriptor_pool_ = vk::raii::DescriptorPool{
        ctx_->raii_device(),
        vk::DescriptorPoolCreateInfo{
            // freeDescriptorSet bit not set: sets are freed implicitly
            // when the pool is destroyed (raii handles that).
            .maxSets = kSlotCount,
            .poolSizeCount = 1,
            .pPoolSizes = &pool_size,
        },
    };
}

void QuadLayer::allocate_descriptor_sets()
{
    std::array<vk::DescriptorSetLayout, kSlotCount> layouts{};
    layouts.fill(*descriptor_set_layout_);

    descriptor_sets_ = vk::raii::DescriptorSets{
        ctx_->raii_device(),
        vk::DescriptorSetAllocateInfo{
            .descriptorPool = *descriptor_pool_,
            .descriptorSetCount = kSlotCount,
            .pSetLayouts = layouts.data(),
        },
    };
}

void QuadLayer::update_descriptor_sets()
{
    // One write per slot, each pointing at the slot's own image view.
    std::array<vk::DescriptorImageInfo, kSlotCount> image_infos{};
    std::array<vk::WriteDescriptorSet, kSlotCount> writes{};
    for (uint32_t i = 0; i < kSlotCount; ++i)
    {
        image_infos[i] = vk::DescriptorImageInfo{
            .sampler = *sampler_,
            .imageView = slots_[i]->vk_image_view(),
            .imageLayout = vk::ImageLayout::eShaderReadOnlyOptimal,
        };
        writes[i] = vk::WriteDescriptorSet{
            .dstSet = *descriptor_sets_[i],
            .dstBinding = 0,
            .dstArrayElement = 0,
            .descriptorCount = 1,
            .descriptorType = vk::DescriptorType::eCombinedImageSampler,
            .pImageInfo = &image_infos[i],
        };
    }
    ctx_->raii_device().updateDescriptorSets(writes, {});
}

} // namespace viz
