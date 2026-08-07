// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

namespace viz
{

// Which OpenXR reference space a kXr session's world is expressed in -- i.e.
// where the origin of every pose the app sends and receives sits. A viz-level
// enum rather than XrReferenceSpaceType so the public header and the Python
// binding stay free of OpenXR types, matching DisplayMode.
//
// The choice is about the origin's HEIGHT, and it is not cosmetic: an app
// drawing world-locked geometry above the floor gets that height wrong by a
// whole person if it guesses.
enum class XrReferenceSpace
{
    // Origin at the headset's start pose, gravity-aligned. y=0 is HEAD HEIGHT
    // and the floor cannot be recovered from it. The default, because it is
    // the one space every runtime has.
    kLocal,
    // Origin on the floor below the headset's start position; core in
    // OpenXR 1.1. Keeps kLocal's position and facing and moves y=0 to the
    // floor, which is what anything world-locked wants.
    kLocalFloor,
    // Origin at the runtime's stage centre, on the floor. Floor-referenced but
    // does NOT follow the operator: position and facing come from the guardian
    // setup.
    kStage,
};

} // namespace viz
