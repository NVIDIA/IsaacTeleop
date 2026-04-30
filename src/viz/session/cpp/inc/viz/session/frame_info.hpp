// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/viz_types.hpp>

#include <cstdint>
#include <vector>

namespace viz
{

// Per-frame state surfaced to the caller of render() / begin_frame().
// Layers should not depend on this directly — it's plumbing for the
// application's frame loop (logging, stale-content detection, XR pose
// tracking).
struct FrameInfo
{
    uint64_t frame_index = 0; // Monotonic counter starting at 0
    int64_t predicted_display_time = 0; // XR time (ns); 0 in window/offscreen
    float delta_time = 0.0f; // CPU wall-clock seconds since last frame
    bool should_render = true; // false in kStopping or when XR runtime says skip
    std::vector<ViewInfo> views; // 1 in window/offscreen, 2 in XR stereo
    Resolution resolution{}; // Render-target resolution (per view in XR)
};

// Aggregated timing diagnostics for the most recent frame window.
// Updated each frame by the session; queried by app for HUD / logging.
struct FrameTimingStats
{
    float render_fps = 0.0f; // Smoothed frames-per-second over the recent window
    float target_fps = 0.0f; // Display target (60/72/90/120 in XR; vsync rate windowed)
    uint64_t missed_frames = 0; // Frames where GPU work didn't complete in budget
    float avg_frame_time_ms = 0.0f;
    float gpu_time_ms = 0.0f; // Last frame's GPU-side render time
    uint32_t stale_layers = 0; // Layers whose content missed stale_timeout this frame
};

} // namespace viz
