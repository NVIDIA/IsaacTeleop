// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "image_layer_base.hpp"

#include <viz/core/device_image.hpp>
#include <viz/core/viz_buffer.hpp>
#include <viz/core/viz_types.hpp>
#include <vulkan/vulkan.h>

#include <array>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <string>

namespace viz
{

class VkContext;

// QuadLayer: renders a CUDA-fed RGBA8 texture, either fullscreen
// (window/offscreen — quad fills the layer's tile) or as a world-space
// rectangle (kXr — Config::placement required).
//
// The image mailbox (submit / slot promotion / CUDA semaphores) lives in
// ImageLayerBase; this class adds the draw path into the shared render
// target plus the optional native XrCompositionLayerQuad path.
//
// Stereo: in kXr, record() binds the left descriptor for view 0 and the
// right for view 1; window/offscreen (single view) draws the left buffer
// only. See ImageLayerBase for the paired-mailbox submit contract.
class QuadLayer : public ImageLayerBase
{
public:
    struct Config
    {
        std::string name = "QuadLayer";
        Resolution resolution{};
        PixelFormat format = PixelFormat::kRGBA8;

        // 3D placement in the session's reference space (OpenXR LOCAL
        // or STAGE). size_meters is width × height; both components
        // must be > 0 (validated at construction).
        struct Placement
        {
            Pose3D pose{};
            glm::vec2 size_meters{ 0.0f, 0.0f };
        };

        // window/offscreen ignore this. kXr REQUIRES it: stretching a
        // fullscreen quad across stereo eyes is never the right thing.
        // record() throws std::logic_error on kXr + nullopt.
        std::optional<Placement> placement;

        // Allocate a small mip chain on each DeviceImage slot and
        // regenerate it via vkCmdBlitImage in record_pre_render_pass.
        // Sampler switches to LINEAR mip filtering. Capped internally
        // at kMaxMipLevels (smallest level is 1/8 linear dims for the
        // typical 1080p / 4K source) — past that the cost outpaces the
        // visual win for our XR distance-view use cases.
        // On by default: the per-frame cost is sub-millisecond and the
        // aliasing it removes is very visible in XR / multi-tile grids.
        // Set to false to save the ~33% extra image memory on layers
        // that are always sampled at native resolution.
        bool generate_mipmaps = true;

        // Stereo mode. When true, the layer owns a paired left+right
        // mailbox; submit MUST be called with both buffers. In kXr,
        // view 0 (left eye) samples the left buffer and view 1 (right
        // eye) the right. In window/offscreen the left buffer is drawn
        // and the right is allocated but unused. Memory doubles.
        bool stereo = false;

        // Horizontal disparity between the left-plane (in the left eye)
        // and the right-plane (in the right eye), in millimeters along
        // the placement's local +x axis. Each eye's quad center is
        // shifted by ±stereo_baseline_mm/2 (left eye: −, right eye: +).
        // 0 means both eyes see the same world-space quad; all stereo
        // cues come from the captured images. Positive values let the
        // planes splay outward (virtual screen further back); negative
        // makes them cross (closer to viewer). Ignored when stereo is
        // false or outside kXr. mm-scale chosen because typical real-
        // world IPDs and camera baselines are 50–80 mm.
        float stereo_baseline_mm = 0.0f;

        // WHO composites this quad in kXr. true (the DEFAULT): the OpenXR
        // runtime — the quad is submitted as an XrCompositionLayerQuad and
        // the runtime places + samples it directly, enabling its layer
        // fast path (and, for frames where every visible layer is
        // runtime-composited, client-reconstructed streaming — the shared
        // projection layer is dropped). Stereo emits one quad per eye via
        // eyeVisibility. Ignored outside kXr (window/offscreen are always
        // composited by Televiz).
        //
        // false: Televiz's built-in compositor draws the quad into the
        // shared render target, where 3D-placed quads depth-test against
        // each other — a runtime-composited quad carries NO depth (OpenXR
        // quad layers have none), so it's a flat billboard ordered by
        // submission. Also the escape hatch for runtimes that mishandle
        // quad layers. QuadLayer is the only shape with this choice:
        // CylinderLayer / EquirectLayer are runtime-composited always.
        // ``generate_mipmaps`` only applies on the compositor path (the
        // runtime samples native quads). Requires ``placement`` at record
        // time either way, same as any kXr quad.
        bool openxr_composition = true;

        // Composite honoring the texture's alpha channel. Native path:
        // sets XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT on the
        // submitted XrCompositionLayerQuad. Off by default: camera feeds
        // are opaque, and alpha-free layers keep the frame eligible for
        // the runtime's client-reconstructed streaming (which excludes
        // source-alpha layers). Turn on for translucent content (HUDs).
        // Compositor path: currently ignored (the draw pipeline blends
        // per the shared render target setup).
        bool alpha_blend = false;
    };

    // Hard cap on the mip chain when generate_mipmaps is enabled.
    // Smallest level is 1/(2^(kMaxMipLevels-1)) of the linear extent;
    // at 4 that's 1/8 (240x135 from 1080p, 480x270 from 4K).
    static constexpr uint32_t kMaxMipLevels = 4;

    // Builds the mailbox DeviceImages + pipeline up front. Throws
    // std::invalid_argument on bad config; std::runtime_error on
    // Vulkan / CUDA failure.
    QuadLayer(const VkContext& ctx, VkRenderPass render_pass, Config config);

    ~QuadLayer() override;
    void destroy();

    // Pre-pass slot: promote latest_ -> in_use_[in_flight_slot] AND
    // (when generate_mipmaps is on) emit the mip-chain blits on the
    // in-use slot. record() reads the already-promoted slot, so both
    // calls must agree on in_flight_slot for the same frame.
    void record_pre_render_pass(VkCommandBuffer cmd, uint32_t in_flight_slot) override;

    // Skips the draw before the first submit (slot kSlotNone) — RT
    // keeps its clear value. in_flight_slot identifies which of the
    // up to kMaxFramesInFlight in-flight frames is being recorded;
    // this slot's in_use_ entry is updated to the current latest_.
    void record(VkCommandBuffer cmd,
                const std::vector<ViewInfo>& views,
                const RenderTarget& target,
                uint32_t in_flight_slot) override;

    // Native OpenXR quad path. is_native_layer() is true only when
    // openxr_composition is on (the default) AND this layer is in a kXr
    // session (so window/offscreen keep using record()).
    // acquire_native_layer() promotes the mailbox slot (like record()'s
    // consumer side) and returns the per-eye source images + placement for
    // the backend to blit into its quad swapchain. See
    // Config::openxr_composition.
    bool is_native_layer() const noexcept override;
    std::optional<NativeLayerView> acquire_native_layer(uint32_t in_flight_slot) override;

    // Drives aspect-fit letterbox in window mode; ignored in kXr.
    std::optional<float> aspect_ratio() const noexcept override;

    // Atomic placement swap, thread-safe vs record(). nullopt switches
    // to fullscreen mode (kXr will throw on next record). Validates the
    // same invariants as construction (size_meters > 0); throws
    // std::invalid_argument.
    void set_placement(std::optional<Config::Placement> placement);
    std::optional<Config::Placement> placement() const noexcept;

protected:
    // Native quad: first GPU read is the backend's copy into the quad
    // swapchain (TRANSFER). Composited-with-mips: the mip-gen blit chain
    // reads level 0 at TRANSFER first. Plain composited: the fragment
    // sampler is the first read.
    VkPipelineStageFlags first_read_stage() const noexcept override;

private:
    void init();

    void create_sampler();
    void create_descriptor_set_layout();
    void create_pipeline_layout();
    void create_pipeline();
    void create_descriptor_pool();
    void allocate_descriptor_sets();
    void update_descriptor_sets();

    // True when this layer should composite as a native OpenXR quad:
    // the flag is set AND the attached session is kXr. Non-XR sessions
    // (and a detached layer) fall back to the record() draw path.
    bool native_active() const noexcept;

    // Emit a full mip-chain regeneration for ``image`` via
    // vkCmdBlitImage. Assumes the image is currently in
    // VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL and returns it to the
    // same layout. Only called when Config::generate_mipmaps is true.
    void record_mip_generation(VkCommandBuffer cmd, DeviceImage& image);

    VkRenderPass render_pass_ = VK_NULL_HANDLE; // borrowed from compositor
    Config config_;
    // Number of mip levels per DeviceImage slot. 1 when mips disabled.
    uint32_t mip_levels_ = 1;

    VkSampler sampler_ = VK_NULL_HANDLE;
    VkDescriptorSetLayout descriptor_set_layout_ = VK_NULL_HANDLE;
    VkPipelineLayout pipeline_layout_ = VK_NULL_HANDLE;
    VkPipeline pipeline_ = VK_NULL_HANDLE;

    VkDescriptorPool descriptor_pool_ = VK_NULL_HANDLE;
    // One descriptor set per slot — record() binds the one for in_use_.
    // ``descriptor_sets_right_`` is only populated when Config::stereo.
    std::array<VkDescriptorSet, kSlotCount> descriptor_sets_{};
    std::array<VkDescriptorSet, kSlotCount> descriptor_sets_right_{};

    // Live placement; lock for set_placement / record() snapshot.
    mutable std::mutex placement_mutex_;
    std::optional<Config::Placement> placement_;
};

} // namespace viz
