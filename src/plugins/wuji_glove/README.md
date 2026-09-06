<!--
SPDX-FileCopyrightText: Copyright (c) 2026 Wuji Technology. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Wuji Glove → Isaac Teleop

Drive a **Wuji dexterous hand** from a **Wuji data glove** through an Isaac
Teleop plugin session. The executable currently selects the local OpenXR
adapter, while the plugin implementation uses transport-neutral pull and hand
tracking channels.

Full documentation — components, prerequisites, installation, running, and
troubleshooting — lives in the docs tree:
[Isaac Teleop documentation](https://nvidia.github.io/IsaacTeleop/main/device/wuji_glove.html)
(rendered under **Device → Wuji Glove**).

Quick start:

```bash
./install.sh   # fetches the pinned wuji_sdk C SDK, then builds and installs the plugin
```
