<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# G1-Wuji Teleop Example

This example runs a G1-Wuji Isaac Lab scene from an OpenXR headset and MANUS
gloves. Arm end-effector poses come from either AVP hand tracking or VR/PICO
controllers; finger targets come from MANUS skeletons retargeted with the
official `wuji-retargeting` package.

## Layout

- `assets/`: G1-Wuji robot USD and Wuji hand assets used by the example.
- `config/avp_manus.yaml`: AVP hand-wrist arm control with MANUS fingers.
- `config/vr_manus.yaml`: VR/PICO controller arm control with MANUS fingers.
- `config/wuji_retargeting/`: Wuji retargeting YAML files for both hands.
- `docs/setup.md`: host setup and launch runbook.
- `python/g1_wuji_teleop/`: Python implementation package.

## Run

Install IsaacTeleop, install `wuji-retargeting` into the same Python
environment, start the CloudXR runtime, and source
`~/.cloudxr/run/cloudxr.env`. See [docs/setup.md](docs/setup.md) for the full
runbook.

AVP + MANUS:

```bash
PYTHONPATH=examples/g1_wuji_teleop/python python -m g1_wuji_teleop \
    --config examples/g1_wuji_teleop/config/avp_manus.yaml \
    --device cuda:0 \
    --viz kit
```

VR/PICO + MANUS:

```bash
PYTHONPATH=examples/g1_wuji_teleop/python python -m g1_wuji_teleop \
    --config examples/g1_wuji_teleop/config/vr_manus.yaml \
    --device cuda:0 \
    --viz kit
```
