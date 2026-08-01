<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# MuJoCo XR

A MuJoCo scene rendered stereoscopically into an Isaac Teleop Televiz XR
session, with the operator's controllers drawn as markers.

## Status — read this before the diagram

| | |
|---|---|
| **Covered by tests** | [`ctest -L mujoco_xr`](#tests), no headset needed: the whole Vulkan→CUDA→`ProjectionLayer.submit()` path against a real `kOffscreen` session, plus the frame conventions, the projection convention and the clock as unit tests. |
| **Run, but not asserted by any test** | The app's own **frame loop** — the code that sequences clock → `mj_step` → render → projection assertion → submit — via `--mode offscreen`. Each of those pieces has a unit test; the loop that calls them is executed by hand, not in CI. |
| **Never executed anywhere** | `--mode xr` — the whole XR frame loop, OpenXR session sharing via `oxr_handles`, controllers on a shared session, and whether the runtime accepts the depth layer. All need a headset plus a CloudXR runtime. |
| **Known-failing here** | `--mode window` on a Tegra/Xvfb host (see [Run](#run)). |
| **Wrong by construction until calibrated** | The workspace translation — see [Frames](#frames-cppframeshpp). |

Details in [Not verified anywhere in CI or on a developer desktop](#not-verified-anywhere-in-ci-or-on-a-developer-desktop).

Single process, single thread, **one** OpenXR session:

```
VizSession(kXr)  ──get_oxr_handles()──▶  TeleopSession
     │                                        │
     │ vk_device / vk_physical_device         │ controller grip poses
     ▼                                        ▼
_mujoco_xr.Renderer  ──__cuda_array_interface__──▶  ProjectionLayer.submit()
```

The five names, since none of them are standard:

| name | what it is |
|---|---|
| `VizSession` | Isaac Teleop's rendering/display session (`isaacteleop.viz`). It owns the OpenXR instance and session, the Vulkan device, and the compositor layers. |
| `TeleopSession` | Isaac Teleop's *input* session (`isaacteleop.teleop_session_manager`) — trackers and the retargeting pipeline. Here it is handed the OpenXR handles `VizSession` already created, rather than making its own. |
| `get_oxr_handles()` | The accessor that makes the sharing possible: it hands out `VizSession`'s live `XrInstance`/`XrSession` so both halves run on **one** session. |
| `_mujoco_xr.Renderer` | This example's own pybind11 module (`cpp/`) — draws the MuJoCo scene with Vulkan into images it owns. |
| `ProjectionLayer.submit()` | The `VizSession` layer that takes those images (by CUDA pointer, no copy through host memory) and gives them to the compositor. |

## Scope

Renderer + MuJoCo + rig. **Controller poses are drawn as markers only — there
is no control authority.** No IK, no clutch, no rate limiting, no jaw mapping.
That is deliberate: a frame-convention bug and a control bug produce the
identical symptom ("the arm jumped"), and separating them is what makes the
first one debuggable.

## Build

**This example is its own wheel, and the wheel is the only way to run it.**

```bash
uv pip install ./examples/mujoco_xr     # from the repository root
python -m mujoco_xr --mode offscreen
```

That is the whole run path. Nothing is installed into `install/examples/mujoco_xr/`
any more, and there is no `uv run --directory ...` invocation. `uv pip install`
compiles the extension itself, through scikit-build-core, and does not read the
CMake build tree at all.

**Why a separate wheel rather than part of `isaacteleop`.** `uv pip install .`
at the repository root does not deliver this example — the root
`pyproject.toml`'s `install.components = ["isaacteleop_wheel",
"isaacteleop_binaries"]` filters out everything else. Folding it in was rejected:
`_mujoco_xr` links `libmujoco`, so the `isaacteleop` wheel's *contents* would
depend on whether the build host happened to have `mujoco` installed, and a
MuJoCo-linked `.so` would ship to every user. A separate wheel declares
`mujoco` as a real dependency instead of a build-host accident. This is only
possible because the module links **no viz target** — just `Vulkan::Vulkan`,
`CUDA::cudart_static` and `libmujoco`.

**The `isaacteleop` wheel must be installed first, into the same environment.**
It is a declared dependency but is not on any public index, so install it from
your local build before installing this example:

```bash
uv pip install "isaacteleop[cloudxr]" --find-links=./install/wheels/
uv pip install ./examples/mujoco_xr
```

Both must land in **one** environment; that same environment is what
[`rigs/mujoco_xr.yaml`](../../rigs/mujoco_xr.yaml) runs from.

**`pip install -e` is not supported here — use a plain install.** An editable
install redirects `mujoco_xr` back to `python/mujoco_xr/` in the source tree,
which is exactly where the in-tree CMake build drops *its* `_mujoco_xr*.so`; you
would silently import the root build's extension instead of the one the editable
install compiled. The redirect is what makes it silent: the wrong `.so` imports
fine right up until `mjModel*` crosses the boundary — a different interpreter,
potentially a different ABI, potentially a different `libmujoco`. Adding a
`[tool.scikit-build.editable]` block does not help; `mode = "redirect"` is the
default and the redirect *is* the problem. To iterate, re-run `uv pip install
--reinstall-package mujoco-xr-example ./examples/mujoco_xr` — it stays
incremental (~8 s) because the build directory persists.

### Prerequisites

| | |
|---|---|
| **`uv`** | Load-bearing. Install: <https://docs.astral.sh/uv/getting-started/installation/> |
| **CMake ≥ 3.21** | Not 3.20: the project floor is `3.20...3.25` (root `CMakeLists.txt`), but every command on this page goes through `--preset`, and `CMakePresets.json` declares `cmakeMinimumRequired 3.21.0`. Measured on this host with 3.28.3. |
| **A C++ compiler, the Vulkan SDK/loader, CUDA** | The same toolchain the rest of this repository needs; see `docs/source/getting_started/build_from_source/`. |
| **`glslangValidator`** (`apt install glslang-tools`) | The scene shaders are compiled to SPIR-V at build time. In the root build this was implied by `BUILD_VIZ`, which auto-disables when it is missing; on the wheel path it is a hard `FATAL_ERROR` from `cpp/CMakeLists.txt`, so an otherwise-fine host fails the install. |
| **A GPU with Vulkan + CUDA** | Needed to *run* anything, including `--mode offscreen`. Without one, `test_offscreen_render.py` skips with a reason and the app fails at `VizSession.create`. |
| **A headset + CloudXR runtime** | Only for `--mode xr`. Everything else on this page runs without one. |

**Build isolation does not save you from the toolchain rows above.**
`pyproject.toml`'s `build-system.requires` can declare a *Python* build
dependency — that is how `mujoco` gets into an isolated PEP-517 build — but
there is no way to declare CUDA, the Vulkan loader, or `glslangValidator` there.
On a host missing any of them, `uv pip install ./examples/mujoco_xr` fails
*inside* the isolated build, where the CMake error is wrapped in build-backend
output rather than reported as a missing dependency.

### The in-tree CMake build, which is a separate thing

The example is **also** wired into the root build, and that path still exists —
it is what the [tests](#tests) run against. It builds `_mujoco_xr*.so` in place
beside `python/mujoco_xr/__init__.py` and installs nothing.

**So the extension gets compiled twice, and that is a consequence of the design
rather than a bug**: once by the root CMake build for `ctest` (in place, by the
preset's `teleop_build_venv` interpreter), and once by scikit-build-core for the
wheel (by whichever interpreter is installing, whose ABI tag the wheel gets).
Collapsing them today would mean either shipping the root build's tree as a wheel
with no ABI tag, or dropping the in-tree ctest path. Keeping both is the
deliberate trade. The two never collide: `sdist.exclude` in `pyproject.toml`
keeps the in-place `.so` out of the wheel's package copy — see the comment there,
it is a sharper edge than it looks.

**What would collapse it:** the day `ctest` runs against the *installed wheel*
instead of the in-place `.so`. That removes the only reason the source tree needs
a compiled extension in it, and with it the whole `_mujoco_xr_standalone`
discriminator — `CMakeLists.txt` would have exactly one configuration. That is
blocked on packaging, not on this example: `isaacteleop` is a declared dependency
and is on no index, so the test environment cannot resolve it without a
`--find-links` pointing at a local build that may not exist yet.

You only need this path to run the tests. The order is not decorative, and steps
1 and 3 are the same command: on a fresh clone the interpreter in step 2 *does
not exist yet* — configure is what creates `teleop_build_venv`
(`cmake/SetupPython.cmake:152-200`) and then points `Python3_EXECUTABLE` at it —
and the mujoco probe runs **at configure time**, so it has to run again after
the wheel exists.

```bash
# 1. Configure once to create the build venv. This first pass necessarily
#    reports `-- mujoco_xr: skipped ...` — that is expected, not a failure.
cmake --preset py3.12 -DBUILD_VIZ=ON

# 2. Install the wheel into the interpreter that configure just created.
#    `python -m pip` does not work: that venv has no pip.
uv pip install --python build/cmake-cpython-312/teleop_build_venv/bin/python "mujoco==3.11.0"

# 3. Re-configure. NOW the probe finds mujoco and the example is added.
cmake --preset py3.12 -DBUILD_VIZ=ON

# 4. Build. There is no `cmake --install` step for this example any more.
cmake --build --preset py3.12 --parallel
```

`py3.12` is the preset name; its binary directory is `build/cmake-cpython-312`,
which is why steps 2 and 4 spell it out.

The first build of a fresh clone builds **the whole of Isaac Teleop**, not just
this example, so expect it to take a while — it has not been timed here, so no
number is quoted. What *was* measured on this host is the incremental case that
matters when you are iterating: **7.6 s** to rebuild after touching
`cpp/frames.hpp`.

This path is gated on `BUILD_VIZ`. There is no `BUILD_EXAMPLE_MUJOCO_XR` flag —
the only gate is whether the `mujoco` **wheel is installed in the interpreter
CMake resolves** (`Python3_EXECUTABLE`), because the C++ module compiles against
that wheel's headers and links its `libmujoco`.

`examples/mujoco_xr/CMakeLists.txt` is configured **two ways** and branches on
which: `add_subdirectory`'d from the root (the above), or as the top-level
project under scikit-build-core (the wheel). Standalone it sets up for itself the
three things root scope used to provide — `Python3_EXECUTABLE`, pybind11, and
where the `.so` goes. (`glslangValidator` is not among them: `cpp/CMakeLists.txt`
probes for it itself in both configures.) One difference is worth
knowing: a missing `mujoco` is a **skip** in the root build (nobody who did not
ask for this example should have their configure fail) and a **hard error**
standalone (a `return()` there would hand you a wheel with no extension in it).

### Confirming the in-tree example was actually built

A green build does **not** mean this example compiled. Step 3 prints one of:

```
-- mujoco_xr: ON (mujoco=3.11.0 lib=/.../site-packages/mujoco/libmujoco.so.3.11.0)
```

```
-- mujoco_xr: skipped -- '<python>' cannot import mujoco. Install it and re-run
   cmake --preset with: uv pip install --python <python> "mujoco==3.11.0"
```

Configure output is usually piped away, so the reliable check is:

```bash
cmake --preset py3.12 -DBUILD_VIZ=ON 2>&1 | grep '^-- mujoco_xr:'
```

The `ON` line also names the exact `libmujoco.so.*` that was linked, which is
the diagnostic for the failure mode below.

### The MuJoCo version is pinned in two files, and cross-checked against the build interpreter

| file | pin | decides |
|---|---|---|
| `pyproject.toml` | `build-system.requires` | what an isolated wheel build compiles and links against |
| `pyproject.toml` | `project.dependencies` | what the app imports at run time |
| `tests/pyproject.toml` | `dev` extra | what `ctest` resolves |

Becoming a wheel added a *third pin*, but not a third pin **file**: the new
top-level `pyproject.toml` replaced the deleted `python/pyproject.toml` rather
than joining it. The build-time pin is not optional — without `mujoco` in
`build-system.requires`, a PEP-517 isolated build would find none and emit a
wheel with no extension in it.

`CMakeLists.txt` deliberately hardcodes **no** version. It *reads* both files and
fails the configure if any pin disagrees with the version actually installed in
the build interpreter:

```
CMake Error: mujoco_xr: pyproject.toml pins mujoco==3.11.0, but
'<python>' has 3.12.0. ...
```

It matches **every** occurrence in each file (`REGEX MATCHALL`, not `MATCH`), so
the two pins inside `pyproject.toml` are checked against each other as well as
against the interpreter. One consequence: never restate the version number in
prose in those files — a `mujoco==` in a *comment* would be matched too, and a
harmless comment edit would become a configure failure. Write "the pin below".

Note the limit of the check: it compares against **the build interpreter only**.
It cannot see what `uv` will later resolve on the machine that runs the app, so
it is a drift detector, not a guarantee.

The reason any of this matters is that `mjModel*` and `mjData*` pointers cross
the pybind boundary: **exactly one `libmujoco` may be loaded in the process.**
`python/mujoco_xr/__init__.py` imports `mujoco` *before* the extension so that
the wheel's already-loaded library satisfies the extension's `NEEDED` entry, and
the extension is deliberately built with **no RPATH** so a mismatch is a clean
`ImportError` rather than a second copy loaded silently. `__init__.py` also
asserts `mj_versionString()` equality on both sides. Do not add an RPATH to "fix"
an import error — fix the version.

## Run

Every command in this section runs from the environment the two wheels were
installed into (see [Build](#build)). `--help` lists every flag, including the
ones `CloudXRLauncher` adds:

```bash
python -m mujoco_xr --help
```

`--mode` takes `xr` (default), `window` or `offscreen`. `--scene` overrides the
scene XML, which defaults to **package data inside the installed package** —
`<site-packages>/mujoco_xr/assets/tabletop.xml`. It lives at
`python/mujoco_xr/assets/tabletop.xml` in the source tree, which is one
directory deeper than you might expect precisely so that the same one-`.parent`
lookup in `app.py` resolves both in the wheel and in the source tree that the
tests import.

### With a headset

Through the rig, which starts the CloudXR runtime alongside the app. Run it
from the repository root:

```bash
python -m isaacteleop.rig rigs/mujoco_xr.yaml
```

That `python` is the repo-wide convention (`docs/source/references/rig.rst`),
and it means **the environment you installed both wheels into** — not the build
venv (which has no `isaacteleop`) and not the system interpreter. The rig's
command is `{python} -m mujoco_xr --no-launch-cloudxr-runtime`, and `{python}`
expands to the interpreter you launch the rig with, so `mujoco_xr` has to be
installed *there*. If you have not made such an environment:

```bash
uv pip install "isaacteleop[cloudxr]" --find-links=./install/wheels/ --reinstall
uv pip install ./examples/mujoco_xr
```

Since this README warns that picking up the wrong venv is silent, here is how
to check before you start rather than after:

```bash
python -c "import sys, isaacteleop, mujoco_xr; print(sys.executable); print(isaacteleop.__file__); print(mujoco_xr.__file__)"
```

Both packages must come from the same `site-packages`. The app's own startup log
prints the `isaacteleop:` line for the same reason.

Directly, against a runtime you started yourself:

```bash
# In one terminal — the runtime is a host singleton on WSS port 48322.
python -m isaacteleop.cloudxr --accept-eula

# In another.
python -m mujoco_xr --no-launch-cloudxr-runtime
```

`--no-launch-cloudxr-runtime` is not cosmetic: **omitting it makes the app start
its own CloudXR runtime**, which is the right thing when nothing else has, and
fatal when something has (the second runtime takes the port and kills the first).

**If no runtime is running and you pass `--no-launch-cloudxr-runtime` anyway**,
the failure comes out of `VizSession.create(kXr)` as an OpenXR instance/runtime
error before any of this example's own code runs — you will not see the startup
log block at all. Getting *no* `[mujoco_xr]` lines is the tell that it failed
here rather than anywhere downstream. (Not reproduced on this host: nobody has
run `--mode xr` — see the [Status](#status--read-this-before-the-diagram) table.)

### Without a headset

`--mode offscreen` runs the app's own frame loop — clock, `mj_step`, render,
per-frame projection assertion, `ProjectionLayer.submit()` — with no window
system, no runtime and no headset. It renders into memory and nothing is
displayed, so it is a smoke test rather than a way to look at the scene. It runs
until interrupted.

```bash
python -m mujoco_xr --mode offscreen --no-launch-cloudxr-runtime
```

**Know when it has succeeded**, because success is quiet: it prints the startup
block below, then the single `projection convention verified...` line, and then
**nothing further, ever**. There is no per-frame output and no progress
indicator — a silent terminal *is* the passing state. `Ctrl-C` exits **0**
(`main` catches `KeyboardInterrupt`). Anything else — a traceback, a `RuntimeError`
about `mjvScene is full`, or a `clock stalled:` line — is a real failure.

`--mode window` is meant to be the "look at the scene on a desktop" path, and it
is **known-failing on this Tegra/Xvfb host**:

```
Swapchain::create: chosen queue family does not support present on this surface
```

That is pre-existing and unrelated to this example — the same defect fails four
`[window]`-labelled tests in `src/viz` on a clean checkout, before any code here
is reached. On a normal desktop with a present-capable surface it should work,
but nobody has run it there.

**The primary verification path on a machine with no headset is
[`ctest -L mujoco_xr`](#tests)**, not either of the two modes above.

## A real startup log

Verbatim, from `--mode offscreen` on this host. Every assumption that is
otherwise invisible is printed exactly once, before the first frame:

```
[mujoco_xr] scene:      /tmp/mjxr_venv/lib/python3.12/site-packages/mujoco_xr/assets/tabletop.xml
[mujoco_xr] isaacteleop: /tmp/mjxr_venv/lib/python3.12/site-packages/isaacteleop/viz (version 1.5+local)
[mujoco_xr] mujoco:     3.11.0 (extension links 3.11.0)
[mujoco_xr] mode:       DisplayMode.kOffscreen   view resolution: 1024x1024
[mujoco_xr] clip:       near=0.0500 far=50.00 (one pair -> VizSessionConfig, projection, submitted depth)
[mujoco_xr] reference space: LOCAL. VizSession exposes no reference-space option and its backend never sets one, so the origin is wherever the headset was at session start -- NOT the floor.
[mujoco_xr] frames:     mj_from_xr translation = (-1.000, 0.000, -0.730) m. x is operator standoff; z is a FLOOR datum and is only correct if the reference-space origin is on the floor (see above). Neither term may be zeroed.
[mujoco_xr] clock:      time.monotonic() (predicted_display_time is 0 outside kXr)
[mujoco_xr] depth submission: requested (ProjectionLayer depth_format=D32F). Whether the runtime ACCEPTED it is not queryable -- XrBackend::depth_layer_enabled_ is private with no accessor or binding. The absence of errors is NOT confirmation.
[mujoco_xr] control disengaged: DisplayMode.kOffscreen has no OpenXR session, so no controllers and no markers.
[mujoco_xr] projection convention verified on the first rendered frame (P[1][1] < 0, near->0, far->1)
```

**Which of those must match on your machine, and which will not:**

| line | on your run |
|---|---|
| `scene:` / `isaacteleop:` | **Paths differ** — they are absolute and rooted in the `site-packages` you installed into. What matters is that both name the venv you expected, and **the same one**. |
| `mujoco:` | **Both numbers must be identical** to each other (`3.11.0 (extension links 3.11.0)`). Two different versions means two `libmujoco`s in one process; `__init__.py` asserts this, so you would have seen an error instead. |
| `mode:` | Matches your `--mode`. The resolution is whatever the backend recommends and **varies by runtime/host**. |
| `clip:` / `frames:` | **Must match exactly** — they are compiled-in constants. If `frames:` reads anything but `(-1.000, 0.000, -0.730)` on an unmodified tree, something has been edited. |
| `reference space:` / `depth submission:` | Fixed text. Always identical. |
| `version 1.5+local` | **Varies** with the build. |

In `--mode xr` the `clock:` line instead reads
`FrameInfo.predicted_display_time (XR); frames with no prediction are skipped, not sampled as 0`,
`control disengaged` is replaced by a `controller markers: N validly tracked`
line that reprints whenever N changes, and `isaacteleop:` is the single most
useful line on the block — if it points at a `site-packages` you did not expect,
stop there.

## Conventions you can break

### Frames (`cpp/frames.hpp`)

`R_mj_from_xr = Rz(-90) * Rx(+90)`. XR `-Z` → MuJoCo `+x`, XR `+Y` → MuJoCo
`+z`, XR `+X` → MuJoCo `-y`. Testable definition: a point 1 m in front of the
operator at eye height `h` lands at MuJoCo `(+1, 0, h)` before the workspace
translation. `tests/test_frames.py` checks exactly that.

This is a **convention** and cannot be wrong at runtime. Note it deliberately
differs from `examples/retargeting/python/visualize_poses_mujoco_example.py`,
which applies `Rx(+90)` only (XR-forward → MuJoCo `+y`, not REP-103).

**`kTransMjFromXr` (`cpp/frames.hpp:44`) is the lever, and it is a calibration
that is routinely wrong.** It is `(-1.0, 0.0, -0.73)`, two independent terms:
`x` is operator standoff (the robot base sits ~1 m in front of the operator),
`z` is a floor datum that assumes the reference-space origin is on the floor.
Since the space is `LOCAL`, that assumption currently encodes "where the
operator's headset was at session start". Neither term may be zeroed.

There is **no recentre keypress and no runtime override** — changing the datum
means editing that constant and rebuilding. The recentring procedure is
therefore: stand where you intend to work, start the app, read the `frames:`
line in the startup log, compare the virtual table against the real one, and
adjust `z` by the observed error.

The rebuild that costs is **~8 seconds**, not a from-scratch build — measured on
this host, and worth knowing before you decide the loop is too slow to iterate
in:

```bash
# edit cpp/frames.hpp, then reinstall; this recompiles the extension.
uv pip install --reinstall-package mujoco-xr-example ./examples/mujoco_xr   # 8.2 s
```

`--reinstall-package` rather than a bare reinstall: the project version is fixed
at `0.0.0`, so without it `uv` sees the same version already installed and skips
the rebuild. It stays incremental because `pyproject.toml` sets
`build-dir = "build/wheel-{cache_tag}"` — the CMake cache persists between
installs instead of landing in a temp directory.

If you are iterating on the tests instead, `cmake --build --preset py3.12
--parallel` (7.6 s touching `frames.hpp`) rebuilds the in-place `.so` that
`ctest` uses; the two builds are independent and neither refreshes the other.

There is deliberately no `--workspace-offset` flag; see
[Deliberately not a flag](#deliberately-not-a-flag) below. Filed as a follow-up: a
`VizSession::Config::reference_space` option with a LOCAL_FLOOR → STAGE → LOCAL
ladder would remove the guesswork entirely.

#### Deliberately not a flag

A `--workspace-offset x y z` was considered and rejected. It cannot be a
pass-through argument: `Renderer` bakes `xr_from_mj_` **at construction** from
the compile-time constant (`cpp/scene_renderer.cpp:197`), while markers convert
per call through `mj_from_xr_pos`. A Python-side offset would therefore move the
markers and leave the scene where it was — and a marker displaced from the
operator's hand is exactly the symptom this example exists to make
*un*ambiguous. Doing it correctly means threading a runtime translation through
`frames.hpp`, `scene_renderer.cpp`, the bindings and `app.py`, turning one
compile-time source of truth into a value held in two places that can disagree.
That is a real feature, not a flag, and it is worth doing only once somebody has
actually run the calibration loop above — which requires a headset, and has
never been done (see the [Status](#status--read-this-before-the-diagram) table).

### Scene assets

The renderer draws `mjGEOM_BOX` and `mjGEOM_MESH` only, and skips
`mjGEOM_PLANE` outright (this is an AR scene; passthrough is the background). A
sphere or a capsule in the XML renders as nothing. The table **top** must sit
at `z = 0` or the `-0.73` floor datum is invalid for that scene. Lighting
declared in the XML is inert — `cpp/shaders/scene.frag` has one hardcoded
directional light and `mjvGLCamera` is bypassed.

### Culling

`cullMode` is `VK_CULL_MODE_NONE` during bring-up, and that is a decision, not
an omission. The projection flips Y (`P[1][1] < 0`), which inverts the
effective winding; get that wrong with culling on and the scene renders **black**,
which is routinely misdiagnosed as a depth or submit bug. Turn it on only after
a headset has confirmed the scene is visible.

## Tests

```bash
ctest --test-dir build/cmake-cpython-312 -L mujoco_xr --output-on-failure
```

| file | needs | covers |
|---|---|---|
| `test_frames.py` | nothing | the XR→MuJoCo axis map and quaternion order |
| `test_projection.py` | nothing | the clip-space convention (Y flip, standard Z, degenerate-fov rejection) |
| `test_app_helpers.py` | nothing | the NaN-safe `dt` clamp, the zeroed-`predicted_display_time` guard, the stalled-clock watchdog (including that it stays **silent** through a normal startup burst), the debug frustum, and that the per-frame projection assertion actually fires |
| `test_offscreen_render.py` | Vulkan + CUDA | **the whole Vulkan→CUDA→`ProjectionLayer.submit()` path**, in `kOffscreen` — no headset needed |

`test_offscreen_render.py` skips (with a reason naming what was missing) on a
machine with no usable Vulkan/CUDA device. Nothing here is gated on a headset,
because a permanently-skipping test reports green while covering nothing.

## Not verified anywhere in CI or on a developer desktop

The XR frame loop, OpenXR session sharing via `oxr_handles`, whether the
runtime accepts the depth layer, and **controllers on a shared session** all
require a headset plus a CloudXR runtime. (The Vulkan→CUDA interop underneath
them *is* covered — see `tests/test_offscreen_render.py` — and so is the frame
loop itself, in `--mode offscreen`, minus everything XR-specific.) The last one
has no precedent elsewhere in this repository: `xrAttachSessionActionSets` is
legal once per `XrSession`, Teleop sidesteps it with `XR_NVX1_action_context`,
and the one existing shared-session example (`examples/oglo_tactile`) exercises
only Hand and Head trackers, which use no actions. Treat that as the likeliest
first-run blocker.
