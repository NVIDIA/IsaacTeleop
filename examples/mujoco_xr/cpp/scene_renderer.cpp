// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "scene_renderer.hpp"

#include "frames.hpp"

#include <mujoco_xr/shaders/scene.frag.spv.h>
#include <mujoco_xr/shaders/scene.vert.spv.h>

#include <cmath>
#include <cstring>
#include <stdexcept>
#include <string>

namespace mujoco_xr
{

namespace
{

// mjvScene capacity. Not a knob: the only failure mode is "the scene has more
// geoms than this", which is a hard error rather than something to tune at
// runtime, and 20k is ~30x what a tabletop scene produces.
constexpr int kMaxGeom = 20000;

// check_vk() and find_memory_type() come from render_target.hpp. That header
// is included by scene_renderer.hpp and NOT redundantly: BorrowedDevice
// (scene_renderer.hpp:118, by value) and ViewTarget (:134, inside a vector)
// both need to be complete there.

// Well inside the 128-byte Vulkan-guaranteed push-constant budget. No separate
// normal matrix: every geom drawn here is a mesh, whose mjvGeom.mat is a pure
// rotation, so model's upper 3x3 transforms normals unchanged.
struct PushConstants
{
    float model[16]; // column-major world-from-local (rotation, pos)
    float color[4];
};
static_assert(sizeof(PushConstants) <= 128, "push constant budget");

struct EyeUbo
{
    float viewproj[16];
    float light_dir[4];
};

// out = a * b, column-major 4x4.
void mat4_mul(float out[16], const float a[16], const float b[16])
{
    float r[16];
    for (int c = 0; c < 4; ++c)
    {
        for (int row = 0; row < 4; ++row)
        {
            r[c * 4 + row] = a[0 * 4 + row] * b[c * 4 + 0] + a[1 * 4 + row] * b[c * 4 + 1] +
                             a[2 * 4 + row] * b[c * 4 + 2] + a[3 * 4 + row] * b[c * 4 + 3];
        }
    }
    std::memcpy(out, r, sizeof(r));
}

// Vulkan-convention projection (y-down clip, depth 0..1) from an OpenXR-style
// asymmetric fov. Algebraically identical to glm::frustumRH_ZO on
// l = n*tan(angleLeft), r = n*tan(angleRight), b = n*tan(angleUp),
// t = n*tan(angleDown) -- note the DELIBERATE angleUp -> bottom swap, which is
// what viz itself does in src/viz/session/cpp/xr_backend.cpp's
// fov_to_projection_matrix. That swap is the y flip; the renderer must NOT
// flip y a second time.
//
// Consequences, all asserted per frame on the Python side:
//   out[0]  = P[0][0] > 0
//   out[5]  = P[1][1] < 0     <- the load-bearing one; it drives winding
//   out[10] = P[2][2] < 0, out[11] = P[2][3] == -1, out[14] = P[3][2] < 0
//             i.e. STANDARD Z (z_view = -near -> 0.0, -far -> 1.0), not
//             reverse-Z, whatever two stale viz doc comments claim.
void proj_from_fov(const float fov_lrud[4], float near_z, float far_z, float out[16])
{
    const float tl = std::tan(fov_lrud[0]);
    const float tr = std::tan(fov_lrud[1]);
    const float tu = std::tan(fov_lrud[2]);
    const float td = std::tan(fov_lrud[3]);
    std::memset(out, 0, 16 * sizeof(float));
    out[0] = 2.0f / (tr - tl);
    out[8] = (tr + tl) / (tr - tl);
    out[5] = 2.0f / (td - tu); // (td - tu) < 0 flips y for Vulkan clip space
    out[9] = (td + tu) / (td - tu);
    out[10] = far_z / (near_z - far_z);
    out[14] = (far_z * near_z) / (near_z - far_z);
    out[11] = -1.0f;
}

// Inverse of a rigid pose (the view pose is eye-in-reference-space):
// V = [R^T | -R^T t]. Quaternion arrives as wxyz, matching viz::Pose3D.
void view_from_pose(const float pos[3], const float q_wxyz[4], float out[16])
{
    const float w = q_wxyz[0];
    const float x = q_wxyz[1];
    const float y = q_wxyz[2];
    const float z = q_wxyz[3];
    // Row-major R from quaternion.
    const float R[9] = { 1 - 2 * (y * y + z * z), 2 * (x * y - w * z),     2 * (x * z + w * y),
                         2 * (x * y + w * z),     1 - 2 * (x * x + z * z), 2 * (y * z - w * x),
                         2 * (x * z - w * y),     2 * (y * z + w * x),     1 - 2 * (x * x + y * y) };
    std::memset(out, 0, 16 * sizeof(float));
    // Column-major out: rotation part = R^T -> out[c*4 + r] = R^T[r][c] = R[c*3 + r].
    for (int r = 0; r < 3; ++r)
    {
        for (int c = 0; c < 3; ++c)
        {
            out[c * 4 + r] = R[c * 3 + r];
        }
    }
    for (int r = 0; r < 3; ++r)
    {
        out[12 + r] = -(R[0 * 3 + r] * pos[0] + R[1 * 3 + r] * pos[1] + R[2 * 3 + r] * pos[2]);
    }
    out[15] = 1.0f;
}

void create_host_buffer(const BorrowedDevice& dev,
                        VkDeviceSize size,
                        VkBufferUsageFlags usage,
                        VkBuffer* out_buffer,
                        VkDeviceMemory* out_memory)
{
    VkBufferCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    info.size = size;
    info.usage = usage;
    info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    check_vk(vkCreateBuffer(dev.device, &info, nullptr, out_buffer), "vkCreateBuffer");

    VkMemoryRequirements reqs;
    vkGetBufferMemoryRequirements(dev.device, *out_buffer, &reqs);
    VkMemoryAllocateInfo alloc{};
    alloc.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    alloc.allocationSize = reqs.size;
    alloc.memoryTypeIndex = find_memory_type(dev.physical_device, reqs.memoryTypeBits,
                                             VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    check_vk(vkAllocateMemory(dev.device, &alloc, nullptr, out_memory), "vkAllocateMemory");
    check_vk(vkBindBufferMemory(dev.device, *out_buffer, *out_memory, 0), "vkBindBufferMemory");
}

VkShaderModule make_shader_module(VkDevice device, const unsigned char* code, size_t size_bytes)
{
    VkShaderModuleCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
    info.codeSize = size_bytes;
    info.pCode = reinterpret_cast<const uint32_t*>(code);
    VkShaderModule module = VK_NULL_HANDLE;
    check_vk(vkCreateShaderModule(device, &info, nullptr, &module), "vkCreateShaderModule");
    return module;
}

} // namespace

std::array<float, 16> projection_from_fov(const std::array<float, 4>& fov_lrud, float near_z, float far_z)
{
    if (!(near_z > 0.0f) || !(far_z > near_z))
    {
        throw std::invalid_argument("mujoco_xr: require 0 < near_z < far_z");
    }
    if (fov_lrud[1] <= fov_lrud[0] || fov_lrud[2] <= fov_lrud[3])
    {
        throw std::invalid_argument(
            "mujoco_xr: degenerate fov (need angle_right > angle_left and angle_up > angle_down). A "
            "default-constructed viz::Fov is four zeros, and rendering one yields P[0][0] = +inf with a "
            "NaN column -- a blank headset and no error. Fix the FrameInfo.views the session handed over; "
            "do not relax this check.");
    }
    std::array<float, 16> out{};
    proj_from_fov(fov_lrud.data(), near_z, far_z, out.data());
    return out;
}

SceneRenderer::SceneRenderer(const BorrowedDevice& dev, const Config& config, const mjModel* model)
    : dev_(dev), config_(config)
{
    if (config_.width == 0 || config_.height == 0)
    {
        throw std::invalid_argument("mujoco_xr: renderer resolution must be non-zero");
    }
    if (config_.view_count != 2)
    {
        throw std::invalid_argument("mujoco_xr: view_count must be 2 (stereo); mono is not supported");
    }
    if (!(config_.near_z > 0.0f) || !(config_.far_z > config_.near_z))
    {
        throw std::invalid_argument("mujoco_xr: require 0 < near_z < far_z (pass the app's single near/far pair)");
    }
    if (model == nullptr)
    {
        throw std::invalid_argument("mujoco_xr: model address is null");
    }

    try
    {
        xr_from_mj_mat4(xr_from_mj_);

        mjv_defaultOption(&scene_option_);
        mjv_defaultFreeCamera(model, &camera_);
        mjv_defaultScene(&scene_);
        mjv_makeScene(model, &scene_, kMaxGeom);
        scene_made_ = true;

        render_pass_ = create_scene_render_pass(dev_.device);
        upload_geometry(model);
        create_pipeline();
        create_uniforms();

        view_targets_ = std::vector<ViewTarget>(config_.view_count);
        projections_.assign(config_.view_count, std::array<float, 16>{});
        for (uint32_t i = 0; i < config_.view_count; ++i)
        {
            view_targets_[i].create(dev_, render_pass_, config_.width, config_.height);
        }
    }
    catch (...)
    {
        destroy();
        throw;
    }
}

SceneRenderer::~SceneRenderer()
{
    destroy();
}

void SceneRenderer::destroy()
{
    if (dev_.device != VK_NULL_HANDLE)
    {
        (void)vkDeviceWaitIdle(dev_.device);
    }
    // View targets first: they hold CUDA imports of exported memory, and the
    // VkDeviceMemory must outlive the mapping.
    view_targets_.clear();

    if (dev_.device != VK_NULL_HANDLE)
    {
        for (size_t i = 0; i < ubos_.size(); ++i)
        {
            if (ubo_mapped_[i] != nullptr)
            {
                vkUnmapMemory(dev_.device, ubo_memory_[i]);
            }
            if (ubos_[i] != VK_NULL_HANDLE)
            {
                vkDestroyBuffer(dev_.device, ubos_[i], nullptr);
            }
            if (ubo_memory_[i] != VK_NULL_HANDLE)
            {
                vkFreeMemory(dev_.device, ubo_memory_[i], nullptr);
            }
        }
        ubos_.clear();
        ubo_memory_.clear();
        ubo_mapped_.clear();
        descriptor_sets_.clear();

        if (fence_ != VK_NULL_HANDLE)
        {
            vkDestroyFence(dev_.device, fence_, nullptr);
            fence_ = VK_NULL_HANDLE;
        }
        if (command_pool_ != VK_NULL_HANDLE)
        {
            vkDestroyCommandPool(dev_.device, command_pool_, nullptr);
            command_pool_ = VK_NULL_HANDLE;
            command_buffer_ = VK_NULL_HANDLE;
        }
        if (vertex_buffer_ != VK_NULL_HANDLE)
        {
            vkDestroyBuffer(dev_.device, vertex_buffer_, nullptr);
            vertex_buffer_ = VK_NULL_HANDLE;
        }
        if (vertex_memory_ != VK_NULL_HANDLE)
        {
            vkFreeMemory(dev_.device, vertex_memory_, nullptr);
            vertex_memory_ = VK_NULL_HANDLE;
        }
        if (index_buffer_ != VK_NULL_HANDLE)
        {
            vkDestroyBuffer(dev_.device, index_buffer_, nullptr);
            index_buffer_ = VK_NULL_HANDLE;
        }
        if (index_memory_ != VK_NULL_HANDLE)
        {
            vkFreeMemory(dev_.device, index_memory_, nullptr);
            index_memory_ = VK_NULL_HANDLE;
        }
        if (pipeline_ != VK_NULL_HANDLE)
        {
            vkDestroyPipeline(dev_.device, pipeline_, nullptr);
            pipeline_ = VK_NULL_HANDLE;
        }
        if (pipeline_layout_ != VK_NULL_HANDLE)
        {
            vkDestroyPipelineLayout(dev_.device, pipeline_layout_, nullptr);
            pipeline_layout_ = VK_NULL_HANDLE;
        }
        if (descriptor_pool_ != VK_NULL_HANDLE)
        {
            vkDestroyDescriptorPool(dev_.device, descriptor_pool_, nullptr);
            descriptor_pool_ = VK_NULL_HANDLE;
        }
        if (dsl_ != VK_NULL_HANDLE)
        {
            vkDestroyDescriptorSetLayout(dev_.device, dsl_, nullptr);
            dsl_ = VK_NULL_HANDLE;
        }
        if (render_pass_ != VK_NULL_HANDLE)
        {
            vkDestroyRenderPass(dev_.device, render_pass_, nullptr);
            render_pass_ = VK_NULL_HANDLE;
        }
    }

    if (scene_made_)
    {
        mjv_freeScene(&scene_);
        scene_made_ = false;
    }
    // The geometry index is NOT a Vulkan handle and is the other half of the
    // same bug: leaving stale ranges here would let a draw index into a
    // destroyed buffer -- in bounds, entirely wrong, and invisible to the
    // validation layers.
    mesh_ranges_.clear();
}

void SceneRenderer::upload_geometry(const mjModel* model)
{
    MeshBuffers mb;
    build_mesh_buffers(model, &mb);
    mesh_ranges_ = mb.meshes;

    const VkDeviceSize vsize = mb.verts.size() * sizeof(Vertex);
    const VkDeviceSize isize = mb.indices.size() * sizeof(uint32_t);
    if (vsize == 0 || isize == 0)
    {
        throw std::runtime_error("mujoco_xr: model produced no renderable geometry");
    }
    create_host_buffer(dev_, vsize, VK_BUFFER_USAGE_VERTEX_BUFFER_BIT, &vertex_buffer_, &vertex_memory_);
    create_host_buffer(dev_, isize, VK_BUFFER_USAGE_INDEX_BUFFER_BIT, &index_buffer_, &index_memory_);

    void* map = nullptr;
    check_vk(vkMapMemory(dev_.device, vertex_memory_, 0, vsize, 0, &map), "vkMapMemory(vertex)");
    std::memcpy(map, mb.verts.data(), vsize);
    vkUnmapMemory(dev_.device, vertex_memory_);
    check_vk(vkMapMemory(dev_.device, index_memory_, 0, isize, 0, &map), "vkMapMemory(index)");
    std::memcpy(map, mb.indices.data(), isize);
    vkUnmapMemory(dev_.device, index_memory_);
}

void SceneRenderer::create_pipeline()
{
    VkDescriptorSetLayoutBinding binding{};
    binding.binding = 0;
    binding.descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER;
    binding.descriptorCount = 1;
    binding.stageFlags = VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT;
    VkDescriptorSetLayoutCreateInfo dsl_info{};
    dsl_info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
    dsl_info.bindingCount = 1;
    dsl_info.pBindings = &binding;
    check_vk(vkCreateDescriptorSetLayout(dev_.device, &dsl_info, nullptr, &dsl_), "vkCreateDescriptorSetLayout");

    VkPushConstantRange pc_range{ VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof(PushConstants) };
    VkPipelineLayoutCreateInfo pl_info{};
    pl_info.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    pl_info.setLayoutCount = 1;
    pl_info.pSetLayouts = &dsl_;
    pl_info.pushConstantRangeCount = 1;
    pl_info.pPushConstantRanges = &pc_range;
    check_vk(vkCreatePipelineLayout(dev_.device, &pl_info, nullptr, &pipeline_layout_), "vkCreatePipelineLayout");

    VkShaderModule vs = make_shader_module(dev_.device, shaders::kSceneVertSpv, shaders::kSceneVertSpvSize);
    VkShaderModule fs = make_shader_module(dev_.device, shaders::kSceneFragSpv, shaders::kSceneFragSpvSize);

    VkPipelineShaderStageCreateInfo stages[2]{};
    stages[0].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[0].stage = VK_SHADER_STAGE_VERTEX_BIT;
    stages[0].module = vs;
    stages[0].pName = "main";
    stages[1].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[1].stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    stages[1].module = fs;
    stages[1].pName = "main";

    VkVertexInputBindingDescription vbind{ 0, sizeof(Vertex), VK_VERTEX_INPUT_RATE_VERTEX };
    VkVertexInputAttributeDescription vattrs[2] = { { 0, 0, VK_FORMAT_R32G32B32_SFLOAT, offsetof(Vertex, pos) },
                                                    { 1, 0, VK_FORMAT_R32G32B32_SFLOAT, offsetof(Vertex, normal) } };
    VkPipelineVertexInputStateCreateInfo vin{};
    vin.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;
    vin.vertexBindingDescriptionCount = 1;
    vin.pVertexBindingDescriptions = &vbind;
    vin.vertexAttributeDescriptionCount = 2;
    vin.pVertexAttributeDescriptions = vattrs;

    VkPipelineInputAssemblyStateCreateInfo ia{};
    ia.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
    ia.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;

    VkPipelineViewportStateCreateInfo vp{};
    vp.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
    vp.viewportCount = 1;
    vp.scissorCount = 1;

    VkPipelineRasterizationStateCreateInfo rs{};
    rs.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
    rs.polygonMode = VK_POLYGON_MODE_FILL;
    // CULLING IS OFF DURING BRING-UP, and that is a decision, not an omission.
    // MuJoCo geoms are CCW, and the projection above already flips y (P[1][1]
    // < 0), which inverts the effective winding. Get that wrong with culling
    // ON and the scene renders BLACK, which is routinely misdiagnosed as a
    // depth or a submit bug. MuJoCo's mesh assets also mix winding across
    // OBJ/STL sources. Turn this on only once a headset has confirmed the
    // scene is visible, and only together with frontFace.
    rs.cullMode = VK_CULL_MODE_NONE;
    rs.frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE;
    rs.lineWidth = 1.0f;

    VkPipelineMultisampleStateCreateInfo ms{};
    ms.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
    ms.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;

    VkPipelineDepthStencilStateCreateInfo ds{};
    ds.sType = VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO;
    ds.depthTestEnable = VK_TRUE;
    ds.depthWriteEnable = VK_TRUE;
    ds.depthCompareOp = VK_COMPARE_OP_LESS_OR_EQUAL;
    ds.maxDepthBounds = 1.0f;

    // The alpha channel is the AR passthrough mask, so alpha composites
    // (A = A_src + (1 - A_src) * A_dst) rather than being replaced: with
    // dstAlpha = ZERO a translucent geom drawn over an opaque one would drop
    // that pixel's alpha and the compositor would blend passthrough through the
    // robot. The result is PREMULTIPLIED, which is what viz's layers declare --
    // it never sets XR_COMPOSITION_LAYER_UNPREMULTIPLIED_ALPHA_BIT. The comment
    // at src/viz/session/cpp/xr_backend.cpp:1202-1203 claims straight alpha
    // while the code beside it sets no such bit; believe the code.
    VkPipelineColorBlendAttachmentState blend{};
    blend.blendEnable = VK_TRUE; // the scene XML may set an rgba alpha < 1
    blend.srcColorBlendFactor = VK_BLEND_FACTOR_SRC_ALPHA;
    blend.dstColorBlendFactor = VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA;
    blend.colorBlendOp = VK_BLEND_OP_ADD;
    blend.srcAlphaBlendFactor = VK_BLEND_FACTOR_ONE;
    blend.dstAlphaBlendFactor = VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA;
    blend.alphaBlendOp = VK_BLEND_OP_ADD;
    blend.colorWriteMask =
        VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT | VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT;
    VkPipelineColorBlendStateCreateInfo cb{};
    cb.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
    cb.attachmentCount = 1;
    cb.pAttachments = &blend;

    VkDynamicState dyn_states[2] = { VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR };
    VkPipelineDynamicStateCreateInfo dyn{};
    dyn.sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO;
    dyn.dynamicStateCount = 2;
    dyn.pDynamicStates = dyn_states;

    VkGraphicsPipelineCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
    info.stageCount = 2;
    info.pStages = stages;
    info.pVertexInputState = &vin;
    info.pInputAssemblyState = &ia;
    info.pViewportState = &vp;
    info.pRasterizationState = &rs;
    info.pMultisampleState = &ms;
    info.pDepthStencilState = &ds;
    info.pColorBlendState = &cb;
    info.pDynamicState = &dyn;
    info.layout = pipeline_layout_;
    info.renderPass = render_pass_;
    info.subpass = 0;

    const VkResult r = vkCreateGraphicsPipelines(dev_.device, VK_NULL_HANDLE, 1, &info, nullptr, &pipeline_);
    vkDestroyShaderModule(dev_.device, vs, nullptr);
    vkDestroyShaderModule(dev_.device, fs, nullptr);
    check_vk(r, "vkCreateGraphicsPipelines");
}

void SceneRenderer::create_uniforms()
{
    VkDescriptorPoolSize pool_size{ VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, config_.view_count };
    VkDescriptorPoolCreateInfo pool_info{};
    pool_info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
    pool_info.maxSets = config_.view_count;
    pool_info.poolSizeCount = 1;
    pool_info.pPoolSizes = &pool_size;
    check_vk(vkCreateDescriptorPool(dev_.device, &pool_info, nullptr, &descriptor_pool_), "vkCreateDescriptorPool");

    ubos_.assign(config_.view_count, VK_NULL_HANDLE);
    ubo_memory_.assign(config_.view_count, VK_NULL_HANDLE);
    ubo_mapped_.assign(config_.view_count, nullptr);
    descriptor_sets_.assign(config_.view_count, VK_NULL_HANDLE);

    for (uint32_t i = 0; i < config_.view_count; ++i)
    {
        create_host_buffer(dev_, sizeof(EyeUbo), VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT, &ubos_[i], &ubo_memory_[i]);
        check_vk(vkMapMemory(dev_.device, ubo_memory_[i], 0, sizeof(EyeUbo), 0, &ubo_mapped_[i]), "vkMapMemory(ubo)");

        VkDescriptorSetAllocateInfo alloc{};
        alloc.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
        alloc.descriptorPool = descriptor_pool_;
        alloc.descriptorSetCount = 1;
        alloc.pSetLayouts = &dsl_;
        check_vk(vkAllocateDescriptorSets(dev_.device, &alloc, &descriptor_sets_[i]), "vkAllocateDescriptorSets");

        VkDescriptorBufferInfo buf{ ubos_[i], 0, sizeof(EyeUbo) };
        VkWriteDescriptorSet write{};
        write.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        write.dstSet = descriptor_sets_[i];
        write.dstBinding = 0;
        write.descriptorCount = 1;
        write.descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER;
        write.pBufferInfo = &buf;
        vkUpdateDescriptorSets(dev_.device, 1, &write, 0, nullptr);
    }

    VkCommandPoolCreateInfo pool{};
    pool.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    pool.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    pool.queueFamilyIndex = dev_.queue_family_index;
    check_vk(vkCreateCommandPool(dev_.device, &pool, nullptr, &command_pool_), "vkCreateCommandPool");

    VkCommandBufferAllocateInfo cmd_alloc{};
    cmd_alloc.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    cmd_alloc.commandPool = command_pool_;
    cmd_alloc.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    cmd_alloc.commandBufferCount = 1;
    check_vk(vkAllocateCommandBuffers(dev_.device, &cmd_alloc, &command_buffer_), "vkAllocateCommandBuffers");

    VkFenceCreateInfo fence_info{};
    fence_info.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
    check_vk(vkCreateFence(dev_.device, &fence_info, nullptr, &fence_), "vkCreateFence");
}

int SceneRenderer::update_scene(const mjModel* model, mjData* data)
{
    if (model == nullptr || data == nullptr)
    {
        throw std::invalid_argument("mujoco_xr: update_scene got a null mjModel* / mjData*");
    }
    mjv_updateScene(model, data, &scene_option_, nullptr, &camera_, mjCAT_ALL, &scene_);
    return scene_.ngeom;
}

const std::array<float, 16>& SceneRenderer::projection(int view) const
{
    if (view < 0 || static_cast<uint32_t>(view) >= config_.view_count)
    {
        throw std::out_of_range("mujoco_xr: view index out of range");
    }
    return projections_[static_cast<size_t>(view)];
}

const ViewTarget& SceneRenderer::view_target(int view) const
{
    if (view < 0 || static_cast<uint32_t>(view) >= config_.view_count)
    {
        throw std::out_of_range("mujoco_xr: view index out of range");
    }
    return view_targets_[static_cast<size_t>(view)];
}

void SceneRenderer::render(const std::vector<float>& poses_xyz_qwxyz, const std::vector<float>& fovs_lrud)
{
    const size_t n = config_.view_count;
    if (poses_xyz_qwxyz.size() != n * 7 || fovs_lrud.size() != n * 4)
    {
        throw std::invalid_argument(
            "mujoco_xr: render() expects view_count*7 pose floats and view_count*4 fov "
            "floats; the renderer's view_count must match len(FrameInfo.views)");
    }

    // Per-view uniforms first, so the whole command buffer can be recorded and
    // submitted once.
    float light[3];
    const float light_len = std::sqrt(kLightDirWorld[0] * kLightDirWorld[0] + kLightDirWorld[1] * kLightDirWorld[1] +
                                      kLightDirWorld[2] * kLightDirWorld[2]);
    for (int i = 0; i < 3; ++i)
    {
        light[i] = kLightDirWorld[i] / light_len;
    }

    for (size_t v = 0; v < n; ++v)
    {
        const float* pose = poses_xyz_qwxyz.data() + v * 7;
        const float* fov = fovs_lrud.data() + v * 4;
        float proj[16];
        float view[16];
        float pv[16];
        proj_from_fov(fov, config_.near_z, config_.far_z, proj);
        std::memcpy(projections_[v].data(), proj, sizeof(proj));
        view_from_pose(pose, pose + 3, view);
        mat4_mul(pv, proj, view);

        EyeUbo ubo{};
        mat4_mul(ubo.viewproj, pv, xr_from_mj_);
        ubo.light_dir[0] = light[0];
        ubo.light_dir[1] = light[1];
        ubo.light_dir[2] = light[2];
        ubo.light_dir[3] = 0.0f;
        std::memcpy(ubo_mapped_[v], &ubo, sizeof(ubo));
    }

    check_vk(vkResetCommandBuffer(command_buffer_, 0), "vkResetCommandBuffer");
    VkCommandBufferBeginInfo begin{};
    begin.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    check_vk(vkBeginCommandBuffer(command_buffer_, &begin), "vkBeginCommandBuffer");

    for (size_t v = 0; v < n; ++v)
    {
        // Alpha 0: AR passthrough shows wherever nothing was drawn.
        VkClearValue clears[2]{};
        clears[0].color = { { 0.0f, 0.0f, 0.0f, 0.0f } };
        clears[1].depthStencil = { 1.0f, 0 };

        VkRenderPassBeginInfo rp{};
        rp.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO;
        rp.renderPass = render_pass_;
        rp.framebuffer = view_targets_[v].framebuffer();
        rp.renderArea.extent = { config_.width, config_.height };
        rp.clearValueCount = 2;
        rp.pClearValues = clears;
        vkCmdBeginRenderPass(command_buffer_, &rp, VK_SUBPASS_CONTENTS_INLINE);

        // Standard (non-flipped) viewport: the y flip lives in the projection
        // and must not be applied twice.
        VkViewport viewport{ 0.0f, 0.0f, static_cast<float>(config_.width), static_cast<float>(config_.height),
                             0.0f, 1.0f };
        VkRect2D scissor{ { 0, 0 }, { config_.width, config_.height } };
        vkCmdSetViewport(command_buffer_, 0, 1, &viewport);
        vkCmdSetScissor(command_buffer_, 0, 1, &scissor);

        vkCmdBindPipeline(command_buffer_, VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline_);
        vkCmdBindDescriptorSets(
            command_buffer_, VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline_layout_, 0, 1, &descriptor_sets_[v], 0, nullptr);
        const VkDeviceSize zero = 0;
        vkCmdBindVertexBuffers(command_buffer_, 0, 1, &vertex_buffer_, &zero);
        vkCmdBindIndexBuffer(command_buffer_, index_buffer_, 0, VK_INDEX_TYPE_UINT32);

        for (int i = 0; i < scene_.ngeom; ++i)
        {
            const mjvGeom* g = scene_.geoms + i;
            // Meshes only. A plane, sphere or capsule in the scene XML renders
            // as nothing -- this is an AR scene and passthrough is the
            // background, so there is no ground plane to draw.
            if (g->type != mjGEOM_MESH)
            {
                continue;
            }
            // dataid = 2*meshid (mesh) or 2*meshid+1 (hull): even only.
            if (g->dataid < 0 || (g->dataid & 1) != 0)
            {
                continue;
            }
            const int meshid = g->dataid >> 1;
            if (meshid >= static_cast<int>(mesh_ranges_.size()))
            {
                continue;
            }
            const MeshRange& range = mesh_ranges_[static_cast<size_t>(meshid)];
            if (range.index_count == 0)
            {
                continue;
            }

            PushConstants pc{};
            // g->mat is row-major; column-major model[c*4 + r] = mat[r*3 + c].
            for (int c = 0; c < 3; ++c)
            {
                for (int r = 0; r < 3; ++r)
                {
                    pc.model[c * 4 + r] = g->mat[r * 3 + c];
                }
                pc.model[c * 4 + 3] = 0;
            }
            pc.model[12] = g->pos[0];
            pc.model[13] = g->pos[1];
            pc.model[14] = g->pos[2];
            pc.model[15] = 1;
            std::memcpy(pc.color, g->rgba, sizeof(pc.color));

            vkCmdPushConstants(command_buffer_, pipeline_layout_,
                               VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof(pc), &pc);
            vkCmdDrawIndexed(command_buffer_, range.index_count, 1, range.first_index, range.base_vertex, 0);
        }

        vkCmdEndRenderPass(command_buffer_);
        view_targets_[v].record_readback(command_buffer_);
    }

    check_vk(vkEndCommandBuffer(command_buffer_), "vkEndCommandBuffer");

    check_vk(vkResetFences(dev_.device, 1, &fence_), "vkResetFences");
    VkSubmitInfo submit{};
    submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &command_buffer_;
    check_vk(vkQueueSubmit(dev_.queue, 1, &submit, fence_), "vkQueueSubmit");
    // Host-side sync rather than an exported timeline semaphore. Coarse, but
    // correct and simple: once the fence signals, the readback copies have
    // retired and the exported memory is safe for CUDA to read. The
    // alternative (a Vulkan->CUDA semaphore) would only buy overlap that a
    // single-threaded frame loop cannot use, because
    // ProjectionLayer.submit() blocks on cudaStreamSynchronize anyway.
    check_vk(vkWaitForFences(dev_.device, 1, &fence_, VK_TRUE, UINT64_MAX), "vkWaitForFences");
}

} // namespace mujoco_xr
