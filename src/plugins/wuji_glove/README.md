<!--
SPDX-FileCopyrightText: Copyright (c) 2026 Wuji Technology. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Wuji Glove → Isaac Teleop

Drive a **Wuji dexterous hand** from a **Wuji data glove** through the NVIDIA Isaac
Teleop / CloudXR (OpenXR) stack. The plugin injects the glove's wrist-relative hand
shape through the standard `XR_EXT_hand_tracking` interface, via NVIDIA's push-device
extension and the same machinery as `controller_synthetic_hands`.

The glove stream does not contain an absolute 6DoF wrist pose. Its joints therefore
remain wrist-relative at the OpenXR stage origin, which is suitable for retargeters
that re-center on the wrist (including `WujiHandRetargeter`). Consumers that need a
spatially placed hand must combine the glove skeleton with a wrist-pose source, as the
input device itself does not provide one.

```
 Wuji glove ──► wuji_glove plugin ──► CloudXR OpenXR runtime ──► retargeter ──► Wuji hand
 (21 joints)    (C++, this dir)       (wrist-relative shape)     (Python)       (WujiHand2)
```

These are **separate processes** — the Isaac Teleop device model, where the runtime
decouples the producer (plugin) from the consumer (retargeting app):

| Piece | Where |
|---|---|
| `wuji_glove` plugin | `src/plugins/wuji_glove/` (C++, this dir) |
| `WujiHandRetargeter` | `src/retargeters/wuji_hand_retargeter.py` |
| demo | `examples/retargeting/python/wuji_hand_retargeter_demo.py` |

## Build

Needs the wuji_sdk **C SDK v2026.7.14** — the
`wuji-sdk-c-2026.7.14-<arch>-linux-gnu.tar.gz` release, which extracts to
`include/wuji_sdk.h` plus `lib/libwuji_sdk_c.so` and its companion
`lib/libwujihandcpp.so` (the C FFI, *not* the `wuji-sdk` pip package). `install.sh`
downloads that pinned release and builds the plugin; or point the CMake vars at an
extracted copy yourself:

```bash
cmake -B build -DBUILD_PLUGIN_WUJI_GLOVE=ON \
    -DWUJI_SDK_INCLUDE_DIR=/path/to/wuji-sdk-c/include \
    -DWUJI_SDK_LIB=/path/to/wuji-sdk-c/lib/libwuji_sdk_c.so
cmake --build build --target wuji_glove_plugin
```

The downstream `WujiHandRetargeter` is a **separate** package — it installs as the
isaacteleop `wuji` extra (`pip install 'isaacteleop[wuji]'`) and needs neither this
plugin nor the CloudXR runtime.

## Run

With the **CloudXR runtime** already up, pass `--plugin-path` and `TeleopSession`
launches and tears down the plugin for you:

```bash
python examples/retargeting/python/wuji_hand_retargeter_demo.py \
    --mode drive --hand right \
    --plugin-path <build>/src/plugins    # dir with wuji_glove/{plugin.yaml, wuji_glove_plugin}
```

Device-free (no hardware): drop `--mode drive` for a synthetic hand, or add
`--mode replay --replay data.pkl` to replay recorded keypoints.
