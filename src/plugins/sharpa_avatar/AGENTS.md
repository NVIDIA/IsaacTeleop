<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 Avatar SDK contributors. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Sharpa Avatar plugin — agent notes

**CRITICAL:** Before editing this tree, read this file and the repo root
[`AGENTS.md`](../../../AGENTS.md).

- **Keep the Avatar SDK external.** `install_avatar_sdk.sh` installs the
  official package under `/opt/avatar-sdk`; CMake consumes that fixed host
  layout directly. Do not copy, patch, or package SDK files, and do not
  advertise extracted SDK trees as supported.
- Install the latest candidate of the production `avatar-sdk` package; pin the
  channel, not a release number, and never substitute `-dev` or `-beta`.
- Keep installer responsibilities separate: SDK/APT in
  `install_avatar_sdk.sh`, host device permissions in
  `install_udev_rules.sh`, and plugin build/install orchestration in
  `install.sh`.
- Do not mutate loader environment variables or SDK configuration at runtime.
  Runtime paths come from the selected SDK root and its `sdk_config.json`.
- **Sample lives in `tools/`, not `examples/`.** Path is
  `src/plugins/sharpa_avatar/tools/sharpa_avatar_sample.py` (ticket #9). Do not
  put it back under `examples/sharpa_avatar`.
- **Public headers pull their dependencies into the interface.**
  `core/inc/avatar/device_side.hpp` is included by
  `avatar_hand_tracking_plugin.hpp`, so every consumer of
  `avatar_plugin_core` parses `AvatarSDK.h` and `openxr.h`. Keep those two link
  entries `PUBLIC` in `core/CMakeLists.txt`; demoting either to `PRIVATE`
  compiles the library but breaks `app/` and `tools/` with "fatal error: no such
  file or directory".
- **Bilateral behavior is table-driven, keyed by the enums, not by `if
  (left) / else`.** `DeviceSide {LEFT, RIGHT}` and `DeviceDataCategory {RAW,
  ROBOT, HUMAN}` in `core/inc/avatar/device_side.hpp` are the single source of
  truth for mapping to SDK enums, XR handles, collection ids, log labels, and
  per-side arrays. Add a case by extending a table (`kDeviceSides`,
  `kJointDataCategories`, `JointStreamRegistry`) — not by copy-pasting a second
  code path for the other hand. A literal `"left"`/`"right"` comparison
  outside that header means the enum round-trip was skipped.
- **Do not re-implement the wrist pose source.** Wrist placement
  (controller aim pose plus per-hand calibration, `XR_MNDX_xdev_space` optical
  hand tracking, and the runtime-specific xdev serial match) lives in
  `plugin_utils::WristPoseSource`. This plugin owns only `kHandOffsets` (its
  calibration) and the `DeviceSide` -> `plugin_utils::WristSide` conversion;
  any local `m_pfn_*`/`m_xdev_*` members or a second `is_openxr_extension_supported`
  mean the shared component was bypassed.
- **`sdk_config.json` defines three different joint lists, not one.**
  `raw_joint_names` and `robot_joint_names` have 22 entries each but order the
  joints *differently within each finger* (e.g. `index_MCP_AA`/`index_MCP_FE`
  are swapped, and the whole pinky run differs), while `human_joint_names` has
  25. Never name a tensor from a hand-written table: RAW and ROBOT frames
  arrive with `Joint::name` already populated by the SDK, so
  `push_joint_frame` passes those names through verbatim. A local joint-name
  array is the bug this bullet exists to prevent.
- **Map OpenXR hand slots by name, never by a literal index array.**
  `HandSkeleton` (HUMAN) carries bare poses with *no* names, so the landmark
  order exists only in `sdk_config.json`. `kOpenXrSlotSources` therefore holds
  the exact `human_joint_names` spelling per `XrHandJointEXT` slot, resolved
  through `m_landmark_index` at runtime. A slot with no Avatar counterpart
  (palm; the pinky `PIP`/`DIP`, which OpenXR has but the Avatar skeleton does
  not) is spelled `nullptr` and published with every location flag clear —
  never given a neighbour's pose and never marked `VALID`.
- **The plugin's entry-point arguments come from `plugin.yaml`.** The
  `sdk_config.json` path is passed as a positional `args` entry and is
  required, with no compiled-in default: a wrong path must fail at startup
  rather than silently degrade to an empty OpenXR mapping.
