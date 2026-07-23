<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# G1-Wuji AVP/VR + MANUS Setup

This runbook assumes an Isaac Lab Python environment and an IsaacTeleop build
using the same Python version.

Replace `/path/to/IsaacTeleop` and `/path/to/wuji-retargeting` with local paths.

## 1. Build and Install IsaacTeleop

```bash
cd /path/to/IsaacTeleop
conda activate isaacteleop

cmake -S . -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DISAAC_TELEOP_PYTHON_VERSION=3.12 \
    -DBUILD_VIZ=OFF \
    -DBUILD_PLUGIN_OAK_CAMERA=OFF \
    -DENABLE_CLANG_FORMAT_CHECK=OFF \
    -DENABLE_CLOUDXR_BUNDLE_CHECK=ON

cmake --build build --parallel "$(nproc)"
cmake --install build

python -m pip install -r src/core/python/requirements-retargeters.txt
python -m pip install -r src/core/python/requirements-cloudxr.txt
python -m pip install --force-reinstall install/wheels/isaacteleop-*.whl
```

## 2. Install Wuji Retargeting

Keep Wuji's repository outside IsaacTeleop. Install it into the same Python
environment used to run this example.

```bash
cd /path/to
git clone --recurse-submodules https://github.com/wuji-technology/wuji-retargeting.git

cd /path/to/wuji-retargeting
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pip install -e .

python -c "from wuji_retargeting.retarget import Retargeter; print(Retargeter)"
```

## 3. Install MANUS Support

Run the udev step on the host.

```bash
cd /path/to/IsaacTeleop/src/plugins/manus
./install_udev_rules.sh
./install_manus.sh
```

Unplug and replug the MANUS dongle. The example configs expect the plugin under
`install/plugins`; edit `manus_plugin.search_paths` if your install prefix is
different.

## 4. Start CloudXR Runtime

Keep this terminal running.

```bash
cd /path/to/IsaacTeleop
conda activate isaacteleop

echo 'NV_DEVICE_PROFILE=auto-webrtc' > custom.env
python -m isaacteleop.cloudxr --cloudxr-env-config=./custom.env --accept-eula
```

On the headset, open the Isaac XR Teleop Sample Client and connect to the Ubuntu
host LAN IP.

## 5. Verify MANUS Input

Run this in a second terminal after CloudXR creates `~/.cloudxr/run/cloudxr.env`.

```bash
cd /path/to/IsaacTeleop
source ~/.cloudxr/run/cloudxr.env

./install/bin/manus_hand_tracker_printer
```

Close the printer before starting teleop because the MANUS SDK is single-owner.

## 6. Run G1-Wuji Teleop

AVP hand-wrist arm control:

```bash
cd /path/to/IsaacTeleop
source ~/.cloudxr/run/cloudxr.env
conda activate isaacteleop

# export LD_LIBRARY_PATH="$CONDA_PREFIX/lib/python3.12/site-packages/nvidia/cu13/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
PYTHONPATH=examples/g1_wuji_teleop/python python -m g1_wuji_teleop \
    --config examples/g1_wuji_teleop/config/avp_manus.yaml \
    --device cuda:0 \
    --viz kit
```

VR/PICO controller arm control:

```bash
cd /path/to/IsaacTeleop
source ~/.cloudxr/run/cloudxr.env
conda activate isaacteleop

export LD_LIBRARY_PATH="$CONDA_PREFIX/lib/python3.12/site-packages/nvidia/cu13/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
PYTHONPATH=examples/g1_wuji_teleop/python python -m g1_wuji_teleop \
    --config examples/g1_wuji_teleop/config/vr_manus.yaml \
    --device cuda:0 \
    --viz kit
```

Press `B` in the Isaac Sim window to start calibration and arm teleop. Press `R`
to reset the robot and recalibrate.
