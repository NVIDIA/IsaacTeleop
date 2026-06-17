<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# G1-Wuji Teleop Example

Workspace-local example for the G1-Wuji AVP + MANUS teleoperation demo.

## Layout

- `config/`: app-owned YAML configuration.
- `assets/`: app-owned robot and retargeting assets copied out of legacy examples.
- `python/g1_wuji_teleop/`: implementation package.
- `scripts/`: thin launchers for operators and developers.

`config/` is organized by retargeting route first, then by robot:

- `config/local/g1_wuji/`: local native-Dex config for `g1_wuji`
- `config/official/g1_wuji/`: official `wuji-retargeting` config for `g1_wuji`

The `scripts/` launchers resolve config/assets from this example first and do
not rely on `examples/teleop/python/` for their default runtime path.

For the `g1_wuji` official retargeting path, the local configs point
`optimizer.urdf_path` at this app's `assets/wuji_hand/urdf/` files, so the
vendored `wuji-retargeting` checkout does not need its nested
`wuji-description` submodule for this demo.

## Entry Points

- Session / Isaac Sim example:

  ```bash
  python examples/g1_wuji_teleop/scripts/g1_wuji_teleop_main.py \
      --config examples/g1_wuji_teleop/config/avp_manus.yml
  ```

- Visualizer:

  ```bash
  python examples/g1_wuji_teleop/scripts/g1_wuji_teleop_visualizer.py \
      --config examples/g1_wuji_teleop/config/avp_manus.yml
  ```
