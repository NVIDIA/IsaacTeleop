// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/device_image.hpp>
#include <viz/core/viz_buffer.hpp>
#include <viz/core/viz_types.hpp>
#include <viz/session/layer_base.hpp>
#include <vulkan/vulkan.h>

#include <array>
#include <atomic>
#include <cstdint>
#include <cuda_runtime.h>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace viz
{

class VkContext;

// ProjectionLayer: a full-view RGBD layer for renderers (gsplat, nvblox,
// neural reconstruction) that produce (color, depth) buffers per frame.
//
// DIRECT-PRESENT ONLY. Unlike QuadLayer, this layer is never composited
// into the shared render target. Its per-eye (color, depth) images are
// copied STRAIGHT into the presentation swapchains by the backend
// (vkCmdCopyImage, verbatim) — exactly like holohub xr_gsplat. In kXr
// that means the renderer's depth lands in the XR depth swapchain with no
// gl_FragDepth round-trip, so CloudXR positional reprojection gets exact
// depth. Consequently a VizSession holds EITHER one ProjectionLayer OR
// any number of QuadLayers, never both (enforced by VizSession). Because
// the copy is 1:1, ``view_resolution`` MUST equal the swapchain per-view
// size (use VizSession::get_recommended_resolution()).
//
// Frame loop contract — IMPORTANT:
//
//     info = session.begin_frame()                    // xrLocateViews
//     color, depth = renderer.render(info.views)      // render against THIS frame's views
//     layer.submit(color, depth)                      // publish for THIS frame
//     session.end_frame()                             // copy to swapchain + xrEndFrame
//
// ``submit()`` MUST be called between ``begin_frame()`` and
// ``end_frame()``. The renderer MUST render against ``info.views[i].pose``
// (the predicted-display-time pose for this frame). The runtime / CloudXR
// paces the app via xrWaitFrame and reprojects the last submitted frame
// at display rate if the renderer is slower.
//
// In ``kXr``, a visible ProjectionLayer that does NOT receive a
// ``submit()`` for the current frame presents nothing (the backend clears
// the swapchains) rather than hand the runtime yesterday's RGBD under
// today's pose. In ``kWindow`` / ``kOffscreen`` the freshness gate is off
// — the most recent publish stays on screen until replaced.
//
// Mailbox: kSlotCount per-eye (color, depth) DeviceImage pairs. submit()
// picks a slot that's neither ``latest_`` nor in any ``in_use_`` entry,
// memcpys + signals cuda_done_writing on the caller's stream, blocks on
// cudaStreamSynchronize so the caller can re-use source buffers
// immediately, then atomically promotes the slot to ``latest_``.
// acquire_direct_views() promotes ``latest_`` to ``in_use_[slot]`` and
// returns that slot's images for the backend copy.
//
// Stereo: when Config::stereo is true, the layer allocates paired
// (left, right) storage per slot. submit() must ship both eyes on a
// single CUDA stream; stream ordering keeps the pair atomic. In kXr
// view 0 (left eye) → left buffer, view 1 (right eye) → right.
//
// Memory (per layer):
//   mono   1024² RGBA8+D32F: 7 slots × 1024² × 8 B    ≈  56 MB
//   stereo 1024² RGBA8+D32F:                          ≈ 112 MB
//   stereo 2048² RGBA8+D32F:                          ≈ 448 MB
class ProjectionLayer : public LayerBase
{
public:
    // Sized to cover backend image counts up to 5, leave one free slot.
    static constexpr uint32_t kMaxFramesInFlight = 5;
    static constexpr uint32_t kSlotCount = kMaxFramesInFlight + 2;

    struct Config
    {
        std::string name = "ProjectionLayer";
        Resolution view_resolution{};
        PixelFormat color_format = PixelFormat::kRGBA8;

        // nullopt → no depth buffer allocated; ProjectionLayer always
        // writes gl_FragDepth = 1.0 (far). Without depth, this layer
        // loses Z-compositing with QuadLayer. Useful for renderers that
        // genuinely have no depth (sky / background fills).
        std::optional<PixelFormat> depth_format = PixelFormat::kD32F;

        // true → per-eye paired storage. submit MUST ship both eyes.
        // In kWindow / kOffscreen the LEFT buffer is sampled; in kXr
        // view 0 → LEFT, view 1 → RIGHT.
        bool stereo = false;
    };

    ProjectionLayer(const VkContext& ctx, Config config);
    ~ProjectionLayer() override;
    void destroy();

    ProjectionLayer(const ProjectionLayer&) = delete;
    ProjectionLayer& operator=(const ProjectionLayer&) = delete;

    // Publish a frame. Each buffer is a CUDA-linear VizBuffer (kDevice
    // space) matching the layer's resolution and the relevant format
    // (color → color_format, depth → kD32F). Validated against the
    // config; mismatch throws std::invalid_argument.
    //
    // Mono no-depth:           submit(color)
    // Mono with depth:         submit(color, &depth)
    // Stereo no-depth:         submit(left_color, nullptr, &right_color, nullptr)
    // Stereo with depth:       submit(left_color, &left_depth, &right_color, &right_depth)
    //
    // submit() does one cudaMemcpy2DToArrayAsync per provided buffer
    // on ``stream``, signals cuda_done_writing on the same stream, then
    // BLOCKS on cudaStreamSynchronize so the caller can re-use source
    // buffers immediately. Cost: ~0.5 ms / 1024² color + depth on a
    // discrete GPU.
    //
    // Marks the layer "fresh for this frame" so record() will draw it.
    // VizSession::begin_frame clears the flag at the start of each
    // frame; a renderer that doesn't submit will see its content
    // skipped in kXr.
    //
    // GIL: pybind binding releases the GIL across this whole call.
    void submit(const VizBuffer& left_color,
                const VizBuffer* left_depth = nullptr,
                const VizBuffer* right_color = nullptr,
                const VizBuffer* right_depth = nullptr,
                cudaStream_t stream = 0);

    // LayerBase contract.
    void on_frame_begin() override; // clears submitted_this_frame_ flag

    // Direct-present-only: never drawn into the shared render pass, so
    // record() is a no-op. The compositor always takes the direct path
    // (acquire_direct_views) for this layer.
    void record(VkCommandBuffer /*cmd*/,
                const std::vector<ViewInfo>& /*views*/,
                const RenderTarget& /*target*/,
                uint32_t /*in_flight_slot*/) override
    {
    }

    // cuda_done_writing waits (TRANSFER stage — the backend copies these
    // images) for color + depth of every active view in the in-use slot.
    // kSlotNone → empty vector.
    std::vector<LayerBase::WaitSemaphore> get_wait_semaphores() const override;

    bool is_projection_layer() const noexcept override
    {
        return true;
    }
    bool supports_direct_present() const noexcept override
    {
        return true;
    }
    std::vector<DirectPresentView> acquire_direct_views(uint32_t in_flight_slot) override;

    // Direct-present requires a 1:1 swapchain copy, so view_resolution must
    // equal the backend's per-view size, a stereo display needs a stereo
    // (>= view-count) layer, and the backend's in-flight image count must fit
    // the mailbox. Throws std::invalid_argument on any mismatch.
    void validate_backend_compatibility(Resolution recommended_view_resolution,
                                        uint32_t backend_view_count,
                                        uint32_t backend_image_count) const override;

    // Accessors.
    Resolution view_resolution() const noexcept;
    PixelFormat color_format() const noexcept;
    std::optional<PixelFormat> depth_format() const noexcept;
    bool is_stereo() const noexcept;
    uint32_t view_count() const noexcept;

    // Diagnostic — nullptr outside valid ranges.
    const DeviceImage* color_image(uint32_t slot, uint32_t view) const noexcept;
    const DeviceImage* depth_image(uint32_t slot, uint32_t view) const noexcept;

private:
    static constexpr uint8_t kSlotNone = 0xFF;

    void init();
    uint8_t pick_free_slot() const noexcept;
    void validate_submit_buffer(const VizBuffer& buf, PixelFormat expected_format, const char* label) const;
    void enqueue_copy(const VizBuffer& src, DeviceImage& dst, cudaStream_t stream) const;

    const VkContext* ctx_ = nullptr;
    Config config_;
    uint32_t view_count_ = 1;
    bool has_depth_ = true;

    // Per-eye (color, depth) mailbox storage. CUDA-mapped DeviceImages the
    // backend copies straight to the swapchains.
    std::array<std::vector<std::unique_ptr<DeviceImage>>, kSlotCount> slots_color_;
    std::array<std::vector<std::unique_ptr<DeviceImage>>, kSlotCount> slots_depth_;

    // Mailbox.
    std::atomic<uint8_t> latest_{ kSlotNone };
    std::array<std::atomic<uint8_t>, kMaxFramesInFlight> in_use_{};
    std::atomic<uint8_t> last_in_use_slot_{ kSlotNone };

    // Set by submit(), cleared by on_frame_begin(). acquire_direct_views()
    // consults this in kXr to gate stale-RGBD-under-new-pose presents.
    std::atomic<bool> submitted_this_frame_{ false };
};

} // namespace viz
