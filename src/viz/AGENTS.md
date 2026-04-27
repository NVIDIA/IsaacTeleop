<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Agent notes — `src/viz` (Televiz)

**CRITICAL (non-optional):** Before editing under `src/viz/`, complete the
mandatory **`AGENTS.md` preflight** in [`../../AGENTS.md`](../../AGENTS.md)
(read every applicable `AGENTS.md` on your paths, not just this file).

## Package shape

`src/viz/` mirrors **`src/core/`**: a peer container of sub-modules, not a
single sub-module. Each sub-module is its own static library with its own
sibling `<sub-module>_tests/` directory:

- **`viz/core/`** — foundational types + Vulkan/CUDA infrastructure.
  Library: `viz_core`. Today: `VkContext`, `VizBuffer`, `Pose3D`, `Fov`,
  `Resolution`, `PixelFormat`. Future: `cuda_texture`, `render_target`,
  `frame_sync`.
- **`viz/layers/`** — `LayerBase` and concrete layers (`QuadLayer`, etc.).
  Library: `viz_layers`. Depends on `viz_core`.
- **`viz/session/`** — `VizSession`, `VizCompositor`, `FrameInfo`, display
  backends (offscreen, GLFW window). Library: `viz_session`. Depends on
  `viz_core`, `viz_layers`.
- **`viz/xr/`** — OpenXR backend (instance/session, swapchain wrapping,
  frame loop, type conversion). Library: `viz_xr`. **Optional** behind
  `BUILD_VIZ_XR`. Depends on `viz_core` + OpenXR.
- **`viz/python/`** — pybind11 module `_viz`, exposed as `isaacteleop.viz`.
- **`viz/shaders/`** — GLSL → SPIR-V at build time.

Test directories follow the same per-module pattern:
`viz/core_tests/`, `viz/layers_tests/`, `viz/session_tests/`,
`viz/xr_tests/`.

`src/viz/CMakeLists.txt` is an **orchestrator only** — it adds the
sub-module sub-directories. Sub-module `CMakeLists.txt` files build the
actual libraries.

## Code conventions

- **C++ namespace:** all Televiz symbols in `core::viz`. Internal helpers
  in `core::viz::detail`. Test infrastructure in `core::viz::testing`.
  This is shared across all sub-modules — no per-module nested namespace.
- **Naming:** types `PascalCase`, methods/functions/variables
  `snake_case` (matches `src/core/`). Private members use trailing
  underscore (`instance_`). Enum values use `kPascalCase` (`kRGBA8`).
- **Include paths:** mirror the on-disk nesting since sub-modules are
  *children* of `viz/`, not peers of each other:
  `<viz/core/vk_context.hpp>`, `<viz/layers/quad_layer.hpp>`,
  `<viz/session/viz_session.hpp>`, `<viz/xr/xr_backend.hpp>`. Each
  sub-module's `inc/viz/<sub-module>/` lives under that sub-module's
  `cpp/`, so per-library isolation is preserved (linking only `viz::core`
  exposes only `viz/core/...` headers, not other sub-modules).
- **Library aliases:** drop the redundant `viz_` prefix in the alias —
  `viz::core`, `viz::layers`, `viz::session`, `viz::xr`. Real CMake
  target names use underscores (`viz_core`, `viz_layers`, ...) since
  `::` is reserved for ALIAS targets. Consumers always say
  `target_link_libraries(... PRIVATE viz::core)`, never the underscore
  form.
- **Format:** clang-format clean (Allman, 120 cols, 4-space indent, left
  pointer alignment). Enforced in CI. Run `clang-format-14 -i` locally
  on any file you modify.

## Tests

- C++ tests: **Catch2 v3**, `TEST_CASE("name", "[tag][tag]")`, linked
  against `Catch2::Catch2WithMain`.
- Tag conventions: **`[unit]`** (no GPU), **`[gpu]`** (Vulkan/CUDA
  required, must skip cleanly via `core::viz::testing::is_gpu_available`
  when no GPU), **`[xr]`** (OpenXR runtime required, manual-only).
- `catch_discover_tests(<target> ADD_TAGS_AS_LABELS)` — exposes Catch2
  tags as CTest labels. CI uses `ctest -L unit` and `ctest -L gpu` for
  selection.
- GPU tests **must** use `GpuFixture` or call `is_gpu_available()` and
  `SKIP()` if false. Never assume a GPU is present.
- Test files live alongside the code they test, in
  `<sub-module>_tests/cpp/`. One executable per sub-module
  (`viz_core_tests`, `viz_layers_tests`, ...). Do **not** dump tests
  into a top-level `viz_tests/` directory.

## CI coverage

- **`build-ubuntu`** (GitHub-hosted, GPU-less): builds `viz_*_tests`,
  runs `ctest --parallel` — `[unit]` tests pass, `[gpu]` tests SKIP
  cleanly. The job also packages all `viz_*_tests` binaries as the
  `viz-tests-${arch}` artifact.
- **`test-viz-gpu`** (self-hosted GPU runner, x64 + arm64): downloads
  the `viz-tests-${arch}` artifact and runs each binary with the
  `[gpu]` filter. This is where the GPU paths actually execute.
- **`publish-wheel`** depends on `test-viz-gpu` succeeding — wheels are
  not published if any `[gpu]` test fails.

When you add a new `viz_<sub>_tests` executable, no CI changes needed:
the package step globs `viz_*_tests` and the runner loops over them.

## OpenXR boundary

- **Public API surface (in `viz_core`, `viz_layers`, `viz_session`)
  must not expose OpenXR types.** Convert `XrPosef`/`XrFovf` to
  `core::viz::Pose3D`/`Fov` at the boundary. The conversion lives in
  `core::viz::detail` inside `viz_xr` (where OpenXR headers are
  available). This keeps `BUILD_VIZ_XR=OFF` viable for window/offscreen
  builds without requiring OpenXR headers.
- **Vulkan types are exposed** in the public API where functionally
  necessary (`VkCommandBuffer`, `VkRenderPass`, `VkImage` for custom
  layer authoring). This is intentional — Vulkan is the contract for
  the extension mechanism.

## Coordinate system

OpenXR stage space conventions throughout: **right-handed, Y-up,
meters, radians**. Robotics/ROS users converting from TF frames or
other coordinate systems must do so at the application boundary —
Televiz does not bridge to TF.
