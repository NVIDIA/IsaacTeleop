// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/viz_types.hpp>
#include <vulkan/vulkan.h>

#include <atomic>
#include <string>
#include <vector>

namespace viz
{

class RenderTarget;

// Abstract base class for content rendered by Televiz's compositor.
//
// A layer represents one piece of GPU content drawn into the active render
// pass. The compositor calls record() with the active command buffer (after
// vkCmdBeginRenderPass) and the per-view parameters; subclasses bind their
// pipeline / descriptor sets and issue draw calls.
//
// Subclassing contract:
//   - record() may issue any draws that fit inside the active render pass
//     (RGBA8_SRGB color + D32_SFLOAT depth, single-sample). It MUST NOT
//     end / re-begin the render pass and MUST NOT submit work itself.
//   - The compositor calls record() once per frame in insertion order and
//     skips invisible layers (is_visible() == false).
//   - Subclasses may safely cache per-target Vulkan resources keyed off the
//     RenderTarget handle, but must rebuild them if the target changes
//     (e.g. resolution change).
//
// LayerBase has no virtual init/destroy; resource lifetime is the
// subclass's concern. The compositor only ever calls record().
class LayerBase
{
public:
    explicit LayerBase(std::string name);
    virtual ~LayerBase() = default;

    LayerBase(const LayerBase&) = delete;
    LayerBase& operator=(const LayerBase&) = delete;

    // Issue draw commands inside the currently-active render pass.
    //   cmd:    the compositor's command buffer with the render pass active
    //   views:  per-view parameters (1 entry in window/offscreen, 2 in XR
    //           stereo). Indexable by view index for stereo viewport setup.
    //   target: the framebuffer dimensions and Vulkan handles the layer
    //           draws into; const so layers cannot modify the target.
    virtual void record(VkCommandBuffer cmd, const std::vector<ViewInfo>& views, const RenderTarget& target) = 0;

    const std::string& name() const noexcept;

    // Visibility flag is atomic so it can be toggled from any thread (UI
    // callback, Python control loop, hot-key handler) without racing the
    // compositor's per-frame is_visible() check on the render thread. Uses
    // relaxed ordering — the flag itself is the only state being published,
    // there's no other memory to synchronize through it. A toggle that
    // races a frame may be observed by the next frame instead of this one,
    // which is the desired semantics.
    bool is_visible() const noexcept;
    void set_visible(bool visible) noexcept;

private:
    std::string name_;
    std::atomic<bool> visible_{ true };
};

inline LayerBase::LayerBase(std::string name) : name_(std::move(name))
{
}

inline const std::string& LayerBase::name() const noexcept
{
    return name_;
}

inline bool LayerBase::is_visible() const noexcept
{
    return visible_.load(std::memory_order_relaxed);
}

inline void LayerBase::set_visible(bool visible) noexcept
{
    visible_.store(visible, std::memory_order_relaxed);
}

} // namespace viz
