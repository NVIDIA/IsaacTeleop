<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Isaac Teleop

<div align="center">

**The unified framework for high-fidelity ego-centric and robotics data collection.**

[![Python](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![Isaac Lab](https://img.shields.io/badge/Isaac%20Lab-2.3.0-orange.svg)](https://isaac-sim.github.io/IsaacLab/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)


</div>

---

## Overview


### Key Features

- **Simulation based teleop**: Based on Isaac Lab
- **Real robot teleop**: Coming soon in early 2026

## Hardware requirements

### Minimum (for robot teleop & data collection)

- **CPU**: X86 (ARM support coming soon)
- **GPU**: NVIDIA GPU required

### Running simulation with Isaac Sim and Isaac Lab

- **CPU**: AMD Ryzen Threadripper 7960x (Recommended)
- **GPU**: 1x RTX 6000 Pro (Blackwell) or 2x RTX 6000 (Ada)

## Prerequisites

- **OS**: Ubuntu 22.04 or 24.04
- **Python**: 3.11 or newer (version configured in root `CMakeLists.txt`)
- **CUDA**: 12.8 (Recommended)
- **NVIDIA Driver**: 580.95.05 (Recommended)

### One time setup

1. Request [CloudXR SDK Early Access](https://developer.nvidia.com/cloudxr-sdk-early-access-program/join)

2. Install Docker by following the [public guide](https://docs.docker.com/engine/install/ubuntu)

3. Install [NGC CLI tool](https://org.ngc.nvidia.com/setup/installers/cli)

4. Configure your [NGC API key](https://org.ngc.nvidia.com/setup/api-keys)

5. Verify you have access to all the artifacts
```
ngc registry resource list "nvidia/cloudxr-js-early-access"
ngc registry image list "nvidia/cloudxr-runtime-early-access"
```

## Quick Start

### Installation

1. **Install uv** (if not already installed):

We strongly recommend using `uv` for dependency management and Python virtual
environment.  Other solution should also work, but your mileage may vary.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. **Create UV virtual environment**

```bash
uv venv --python 3.11 venv_isaac
source venv_isaac/bin/activate
```

3. **Clone the repository**
```bash
git clone git@github.com:NVIDIA/TeleopCore.git
cd TeleopCore
```

> **Note**: Dependencies (OpenXR SDK, pybind11, yaml-cpp) are automatically downloaded
> during CMake configuration using FetchContent. No manual dependency installation or
> git submodule initialization is required.

4. **Download CloudXR**

Download CloudXR PID (Product Information Delivery) from NVOnline (https://partners.nvidia.com/).
In the package, you should found a `tar.gz` file:

Place `cloudxr-runtime-6.1.0-pid3.tar.gz` under the `deps/cloudxr` folder:
```
deps/
├── cloudxr
│   ├── CLOUDXR_LICENSE
│   ├── docker-compose.yaml
│   └── cloudxr-runtime-6.1.0-pid3.tar.gz
```

5. **Build and load CloudXR containers**
```bash
./examples/cxrjs/build_containers.sh
./scripts/cloudxr_image_ops.sh --load 6.1.0-pid3
```

> **Important:** Make sure you place the `.gz` and `.tgz` files from the previous steps at the
> designated location. Otherwise, you will see an error like this:
> ```
> Error: File not found: ./deps/cloudxr/cloudxr-runtime-6.1.0-pid3.tar.gz
> ```

6. **Run CloudXR**
```bash
./scripts/run_cloudxr.sh
```

7. **White list ports for Firewall**

```bash
# CloudXR streaming ports.
sudo ufw allow 47998:48000,48005,48008,48012/udp
sudo ufw allow 49100/tcp
sudo ufw allow 48322/tcp

# The web server for HTTP and HTTPS.
sudo ufw allow 8080
sudo ufw allow 8443
```

8. **WebXR Client Setup**

The last step will run a couple docker containers and one of them is the WebXR server. It can be
accessed via the browser on your HMD support (Quest 3 or Pico 4 Ultra).

- Local: `https://localhost:8443` or `http://localhost:8080`
- Network: `https://<server-ip>:8443` or `http://<server-ip>:8080`

> **Tips:**
> - For rapid development and debugging, we recommend testing your CloudXR.js application on a
>   desktop browser before deploying to XR headsets.
> - For Pico 4 Ultra, Pico OS 15.4.4U or later is required.
> - HTTP mode is easier to use, but currently is not supported by

### CloudXR Configurations (Optional)

You can override CloudXR configurations by creating a `.env` and place it next
to `deps/cloudxr/.env.default`. The folder structure should look like:

```bash
$ tree -a deps/cloudxr/
deps/cloudxr/
├── CLOUDXR_LICENSE
├── .env
├── .env.default
└── .gitignore
```

### Install & Run Isaac Lab

Isaac Tepeop Core is design to work side by side with [NVIDIA Isaac Lab](https://github.com/isaac-sim/IsaacLab). We recommend the [Installation using Isaac Sim Pip Package](https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/pip_installation.html) method for Isaac Lab.  Please refer to Isaac Lab's [Installation](https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/index.html) guide for other advanced methods. Here are the quick steps to do so.

1. **Install dependencies**

```bash
source venv_isaac/bin/activate
uv pip install "isaacsim[all,extscache]==5.1.0" --extra-index-url https://pypi.nvidia.com
uv pip install -U torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128
```

2. **Clone & install Isaac Lab**

Run this out side of the `TeleopCore` code base.

```bash
# In a separate folder outside of Teleop Core:
git clone git@github.com:isaac-sim/IsaacLab.git

# Run the install command
cd IsaacLab
./isaaclab.sh --install

# Set ISAACLAB_PATH, which will be used later in `run_isaac_lab.sh`.
export ISAACLAB_PATH=$(pwd)
```

### Build Teleop Core and Run Isaac Lab Sample

1. Build & install Teleop Python packages

Build with default settings. See [BUILD.md](BUILD.md) for advanced instructions
for advanced build steps.
```bash
cmake -B build
cmake --build build --parallel
cmake --install build
```

Install the Python package
```bash
uv pip install --find-links=install/wheels teleopcore
```

Validate the Python package has been successfully built and installed.
```bash
python -c "import teleopcore.deviceio"
```

Run a quick test:
```bash
source scripts/setup_cloudxr_env.sh

python ./examples/oxr/python/test_extensions.py
```

2. **Run Teleop with Isaac Lab**

```bash
# In the Teleop Core repo:
./scripts/run_isaac_lab.sh
```