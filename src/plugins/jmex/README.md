<!--
SPDX-FileCopyrightText: Copyright (c) 2026 j-mex. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# j-mex AgileMaster plugin

Streams a [j-mex AgileMaster](https://jmex.com.tw/agilemaster/) motion capture channel into Isaac
Teleop as `JointStateOutput` on the [generic joint-space device path](../../../docs/source/device/joint_space.rst).

AgileMaster is the whole system: the **j-mex Mocap Suit**, **MOXI Player**, and the
**MOXI Receiver SDK** this plugin links against.

This file is the short version of building and running the binaries, beside the installed plugin.
The [device page](../../../docs/source/device/jmex.rst) is the full guide: the Quick Start, what the
plugin publishes, how to consume the data, and what to check when it does not work.

## Prerequisites

1. **MOXI Receiver SDK** 1.1 or newer — Apache-2.0, but not a public download. Request it through
   the [AgileMaster product page](https://jmex.com.tw/agilemaster/).
2. **MOXI Player**, on this machine or another on the same subnet, started in either order — the
   device page covers the host layout.
3. **CloudXR runtime** — the tensor transport is an OpenXR runtime feature, so it is required even
   though no headset is. It needs a concrete device profile; the default, `Quest3`, already is one.

   ```bash
   python -m isaacteleop.cloudxr.service run
   ```

   Then source the environment it writes in **every** terminal you start these binaries from — they
   are native OpenXR applications and do not embed `CloudXRLauncher`:

   ```bash
   source ~/.cloudxr/run/cloudxr.env
   ```

## Building

Unpack the SDK into this directory as `MOXIReceiverSDK/`, so that
`src/plugins/jmex/MOXIReceiverSDK/sdk/linux-x64/lib/cmake/MOXIReceiverSDK/` exists. Nothing else is
needed:

```bash
cmake -B build
cmake --build build --parallel
cmake --install build
```

`.gitignore` keeps that directory out of the repository — the SDK is yours to place rather than
something the build fetches, the same arrangement manus and wuji_glove use.

To keep the SDK elsewhere, point either `CMAKE_PREFIX_PATH` or `JMEX_SDK_ROOT` (a CMake variable or
an environment variable) at the SDK's platform directory — the one containing
`lib/cmake/MOXIReceiverSDK`. `JMEX_SDK_ROOT` is searched first, and warns instead of falling back
silently if it holds no SDK the plugin can use:

```bash
cmake -B build -DJMEX_SDK_ROOT=/path/to/MOXIReceiverSDK-1.1.0/sdk/linux-x64
```

Without an SDK the plugin is skipped and the rest of the tree still builds — look for
`Skipping jmex plugin build:` in the configure output.

## Running

```bash
# Defaults: channel 1, collection id "jmex"
./install/plugins/jmex/jmex_plugin

# Player's file replay is fixed on channel 255
./install/plugins/jmex/jmex_plugin --channel=255
```

`TeleopSession` can start it instead, through a `PluginConfig` pointing at `install/plugins` — see
the device page. Arguments are named rather than positional because the PluginManager injects
`--plugin-root-id=<id>` ahead of them.

`jmex_joint_state_printer` reads back what the plugin publishes with no Python and no retargeting
graph in the way, so it separates "the device path works" from "my pipeline is misconfigured". It
consumes what the plugin publishes, so the plugin has to stay running:

```bash
# Terminal 1
source ~/.cloudxr/run/cloudxr.env
./install/plugins/jmex/jmex_plugin
# Terminal 2
source ~/.cloudxr/run/cloudxr.env
./install/plugins/jmex/jmex_joint_state_printer jmex
```
