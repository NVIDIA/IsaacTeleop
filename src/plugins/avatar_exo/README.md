<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Avatar Exoskeleton Gloves plugin (`avatar_exo`)

Streams data from the **Avatar exoskeleton gloves** into Isaac Teleop. The plugin reads the
vendored Avatar SDK (`sdk/`, a copy of `Avatar/SDK`) and can publish up to **three independent
data sets**, any subset of which is selected at start time:

| Data set | Avatar source (`fetch_data`)        | Transport into Isaac Teleop                     | Host consumer            |
|----------|-------------------------------------|-------------------------------------------------|--------------------------|
| `raw`    | `RAW` — raw joint angles            | `JointStateOutput` via `SchemaPusher`           | `JointStateSource`       |
| `robot`  | `ROBOT` — retargeted 22-DOF frame   | `JointStateOutput` via `SchemaPusher`           | `JointStateSource`       |
| `human`  | `HUMAN` — hand-skeleton landmarks   | 26 OpenXR hand joints via `HandInjector`        | `HandsSource` / hand tracker |

The design follows the established split: **`raw`/`robot` go the generic joint-space way** (the same
path as `so101_leader`), while **`human` is injected as OpenXR hand tracking** (the same path as
`haptikos` / `controller_synthetic_hands`).

## Design

- **One process, one OpenXR session.** The plugin opens a single `core::OpenXRSession` with the
  union of required extensions (tensor-push for `raw`/`robot`, device-interface for `human`) and the
  Avatar SDK singleton. A single worker thread polls each connected glove at `--rate-hz` and
  forwards the enabled data sets.
- **`raw` / `robot`** → each `(data set, side)` is serialized as a `core::JointStateOutput`
  FlatBuffer and pushed on collection id **`<prefix>_<dataset>_<side>`** (e.g. `avatar_raw_left`).
  Joints default to positional keys `j0..jN-1`, which the server also declares on its
  `JointStateSource`s. This avoids any runtime dependency on sharing an Avatar config file with the
  host.
- **`human`** → `HandSkeleton.landmark` poses are remapped to the 26 OpenXR hand joints and pushed
  through a per-hand `plugin_utils::HandInjector`. The landmark→OpenXR table in
  `avatar_exo_plugin.cpp` (`kHumanLandmarkForJoint`) matches the 25-entry `human_joint_names`
  layout in the Avatar `sdk_config.json`; adjust that one table for a different glove layout.
  Positions pass through in meters and the quaternion is reordered (`w,x,y,z` → `x,y,z,w`).

The Avatar SDK is **copy-included** under `sdk/` (`sdk/include` + `sdk/lib`). Only
`libavatar_sdk.so` is linked; its solver dependencies (casadi / ipopt / …) resolve at runtime from
the same lib dir via rpath. The libs are installed next to the other Isaac Teleop libraries.

## Build with IsaacTeleop

```bash
cd /path/to/IsaacTeleop
cmake -B build \
    -DISAAC_TELEOP_PYTHON_VERSION=3.10 \
    -DBUILD_EXAMPLES=OFF -DBUILD_TESTING=OFF -DENABLE_CLANG_FORMAT_CHECK=OFF
cmake --build build --parallel
# Optional: install as wheel
# cmake --install build
# uv pip install "isaacteleop[cloudxr]" --find-links=./install/wheels/ --reinstall
```

After a build the binary, `plugin.yaml`, and a copy of `sdk/` live at
`build/src/plugins/avatar_exo/`, so the plugin is discoverable from the build tree without
installing (Option B) and can default to `./sdk/sdk_config.json`. `cmake --install` additionally
stages the same layout at `install/plugins/avatar_exo/`.

## Run standalone

```bash
# Both gloves, all three data sets, using the vendored ./sdk/sdk_config.json:
./build/src/plugins/avatar_exo/avatar_exo_plugin \
    --datasets=raw,robot,human --sides=both

# RAW only, right hand:
./avatar_exo_plugin --datasets=raw --sides=right
```

Arguments (all optional except `--datasets`):

| Flag                      | Default   | Meaning                                                        |
|---------------------------|-----------|---------------------------------------------------------------|
| `--datasets=`             | *(none)*  | Comma list of `raw,robot,human` (at least one).               |
| `--sides=`                | `both`    | `both`, or comma list of `left,right`.                        |
| `--collection-prefix=`    | `avatar`  | Prefix for the joint-space collection ids.                    |
| `--config=`               | `./sdk/sdk_config.json` | Optional override for the Avatar SDK init json. |
| `--rate-hz=`              | `90`      | Worker poll/publish rate.                                     |
| `--plugin-root-id=`       | —         | Injected by the PluginManager; ignored.                       |

> The vendored config is relocatable. The plugin replaces `@AVATAR_EXO_SDK_DIR@` with its runtime
> `sdk/` path and resolves `wave_sdk_root`, `fingertip_offset_config`, and `surjection_config`
> relative to that same directory. `robot` still requires `retarget_update_rate_hz >= 1`.

## Behavior & troubleshooting

- **Resilient startup.** Only the OpenXR session is a hard requirement. Avatar SDK init and glove
  discovery happen in the worker and are **retried** — a glove that is unplugged, or an
  avatar-backend that is not up yet, does **not** crash the plugin (and therefore does not crash
  the host `TeleopSession`, which treats any plugin exit as a fatal crash). Gloves are picked up
  as soon as they appear.
- **Where the logs go.** The plugin is launched as a child of the **server** process, so its
  forwarded messages appear in the *standalone server's* console (not the client). The plugin
  filters its child-process stdout/stderr so Avatar SDK/OpenXR startup chatter stays hidden while
  these useful Avatar lines remain visible:
  `AvatarExoPlugin running; waiting ...`, `connected <side> glove [raw=off robot=on human=on]`,
  one-time stream-start messages like `AvatarExoPlugin: left robot stream started`, and SDK
  firmware identity lines containing `SerialHand::fetch_firmware_identity`.
- **Independent outputs.** Each of RAW/ROBOT/HUMAN is created independently. If the HUMAN hand
  injector cannot be created (see below) the glove still registers with RAW/ROBOT active — one
  failed output never blocks the others.
- **HUMAN needs runtime push-device support.** `xrCreatePushDeviceNV: Push devices not supported
  by this system` means the CloudXR runtime was started without push devices (the same mechanism
  manus / haptikos use). Set `NV_CXR_ENABLE_PUSH_DEVICES=1` (true) in `~/cloudxr.env` and restart
  the runtime / standalone server. Until then RAW/ROBOT work but HUMAN hands stay empty. (RAW/ROBOT
  instead need `NV_CXR_ENABLE_TENSOR_DATA=1`, the default.)
- If `raw` joints stay `None`, the glove isn't streaming (wrong transport/IP in the vendored config,
  avatar-backend down, or glove unplugged). Verify the gloves stream with the SDK's own
  `avatar_example`.
- **`robot` needs retargeting enabled.** ROBOT frames are only produced when the SDK config sets
  `retarget_update_rate_hz >= 1` (the default when no config loads is `0` → ROBOT stays empty, so no
  robot stream-start message appears). The vendored `./sdk/sdk_config.json` enables retargeting and
  resolves `hand_fk` / Wave paths relative to the vendored `sdk/`. If the plugin logs `cannot open
  config '…'`, rebuild so CMake copies `sdk/` beside the binary.
  
