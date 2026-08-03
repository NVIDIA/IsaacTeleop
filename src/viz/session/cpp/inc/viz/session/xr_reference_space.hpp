// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

namespace viz
{

// Which OpenXR reference space a kXr session's world is expressed in — i.e.
// where the origin of every pose the app sends and receives actually sits.
// A viz-level enum rather than XrReferenceSpaceType so the public header
// (and the Python binding) stays free of OpenXR types, matching DisplayMode.
//
// THE CHOICE IS ABOUT THE ORIGIN'S HEIGHT, and it is not cosmetic: an app
// that draws world-locked geometry at a known height above the floor gets
// that height wrong by a whole person if it guesses this. Picking one is a
// statement about what the app's y=0 means.
enum class XrReferenceSpace
{
    // Origin at the headset's pose at session start, gravity-aligned.
    // y=0 is HEAD HEIGHT, not the floor, and there is no way to recover the
    // floor from it. The default because it is the one space every runtime
    // has, and it suits view-locked dashboards that never claim a floor.
    kLocal,
    // Origin on the floor below the headset's start position. Core in
    // OpenXR 1.1 (XR_EXT_local_floor before that). The right choice for
    // anything world-locked: it keeps LOCAL's position and facing and moves
    // y=0 down to the floor.
    kLocalFloor,
    // Origin at the runtime's room-scale stage centre, on the floor.
    // Floor-referenced like kLocalFloor but it does NOT follow the operator:
    // position and facing come from the guardian setup, so an app that
    // assumes the operator starts at the origin looking forward will be
    // wrong about both.
    kStage,
};

} // namespace viz
