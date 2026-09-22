<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# isaacteleop

The `isaacteleop` import package and distribution were renamed to `isaaccapture`
in Isaac Teleop 1.6. This distribution installs `isaaccapture` and makes
`import isaacteleop` resolve to it.

It will be removed in 1.9 — inside the 1.x series, so pin `isaacteleop<1.9`,
not `isaacteleop<2`, if you need time. See the
[migration guide](https://nvidia.github.io/IsaacTeleop/main/references/migration.html).
