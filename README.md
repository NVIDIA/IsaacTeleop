<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Isaac Teleop

<div align="center">

**The unified framework for high-fidelity ego-centric and robotics data collection.**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Isaac Lab](https://img.shields.io/badge/Isaac%20Lab-2.3.0-orange.svg)](https://isaac-sim.github.io/IsaacLab/)
[![numpy](https://img.shields.io/badge/numpy-1.22%2B-lightgrey.svg)](https://numpy.org/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)


</div>

---

## Overview

**Isaac Teleop**: The unified standard for high-fidelity egocentric and robot data collection.
It is designed to address the data bottleneck in robot learning by streamlining device integration;
standardizing high-fidelity human demo data collection; and foster device & data interoperability.

## Key Features

### Unified Stack for Sim & Real Teleoperation

- A single framework that works seamlessly across simulated and real-world robots, ensuring
streamlined device workflow and consistent data schemas.
- Currently supported robotics stacks:
  - **ROS2**: Widely adopted middleware for robot software integration and communication
  - **Isaac Sim**: Simulation platform to develop, test, and train AI-powered robots
  - **Isaac Lab**: Unified framework for robot learning designed to help train robot policies
- Upcoming robotics stacks:
  - **Isaac OS**: Enterprise-ready robotics operating system (in early access)
  - **Isaac Arena**: Isaac Lab extension for large-scale evaluation and resource orchestration

### Standardized Device Interface

- Provides a **standardized interface** for teleoperation devices, removing the need for custom
device integrations and ongoing maintenance.
  - Currently supported device categories:
    - **XR Headsets** (with spatial controllers): Vision Pro, Pico, Quest
    - **Gloves**: Manus
    - **Foot Pedals** (hands-free lower body control): Logitech Rudder Pedal
    - **Body Trackers**: Pico Motion Tracker
  - Upcoming device categories:
    - **Master Manipulators**: TBA
    - **Exoskeletons**: TBA
- Easily extend support for additional devices through a **plugin system**, enabling quick
integration of new hardware.

### Flexible Retargeting Framework

- Retarget the standardized device outputs to different embodiments.
- [Reference retargeter implementations](src/core/retargeting_engine/python/retargeters/),
including popular embodiments such as Unitree G1.
- [Retargeter tuning UI](src/core/retargeting_engine_ui/python) to facilitate
live retargeter tuning.

### Teleoperation Use Cases

- Currently supported use cases
  - Use XR headsets for gripper / tri-finger hand manipulation
  - Use XR headsets with gloves for dex-hand manipulation
  - Seated full body loco-manipulation (Homie)
  - Tracking based full body loco-manipulation (Sonic)
- Upcoming use cases
  - Egocentric data collection (aka “no-robot”)
  - Teleoperate cloud based robotics simulations
  - Remote teleoperation with immersive camera streaming to XR headsets

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
uv venv --python 3.11 venv_isaacteleop
source venv_isaacteleop/bin/activate
```

3. **Clone the repository**
```bash
git clone git@github.com:NVIDIA/IsaacTeleop.git
cd IsaacTeleop
```

> **Note**: Dependencies (OpenXR SDK, pybind11, yaml-cpp) are automatically downloaded
> during CMake configuration using FetchContent. No manual dependency installation or
> git submodule initialization is required.

4. **Download CloudXR**

Download CloudXR PID (Product Information Delivery) from NVOnline (https://partners.nvidia.com/).
In the package, you should found a `tar.gz` file:

Place `cloudxr-runtime-6.1.0-pid4.tar.gz` under the `deps/cloudxr` folder:
```
deps/
├── cloudxr
│   ├── CLOUDXR_LICENSE
│   ├── docker-compose.yaml
│   └── cloudxr-runtime-6.1.0-pid4.tar.gz
```

5. **Load CloudXR runtime image**
```bash
./scripts/cloudxr_image_ops.sh --load 6.1.0-pid4
```

> **Important:** Make sure you place the `.gz` file from the previous steps at the
> designated location. Otherwise, you will see an error like this:
> ```
> Error: File not found: ./deps/cloudxr/cloudxr-runtime-6.1.0-pid4.tar.gz
> ```

6. **Run CloudXR**
```bash
./scripts/run_cloudxr.sh
```

This script will automatically:
- Download the CloudXR Web SDK from NGC (if not already present)
- Build the necessary Docker containers (wss-proxy, web-app)
- Start all CloudXR services

> **Note:** The first run may take a few minutes to download the SDK and build containers.
> Subsequent runs will be faster as these are cached.

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
source venv_isaacteleop/bin/activate
uv pip install "isaacsim[all,extscache]==5.1.0" --extra-index-url https://pypi.nvidia.com
uv pip install -U torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128
```

2. **Clone & install Isaac Lab**

Run this outside of the `IsaacTeleop` code base.

```bash
# In a separate folder outside of Isaac Teleop:
git clone git@github.com:isaac-sim/IsaacLab.git

# Run the install command
cd IsaacLab
./isaaclab.sh --install

# Set ISAACLAB_PATH, which will be used later in `run_isaac_lab.sh`.
export ISAACLAB_PATH=$(pwd)
```

### Build Isaac Teleop and Run Isaac Lab Sample

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
uv pip install --find-links=install/wheels isaacteleop
```

Validate the Python package has been successfully built and installed.
```bash
python -c "import isaacteleop.deviceio"
```

Run a quick test:
```bash
source scripts/setup_cloudxr_env.sh

python ./examples/oxr/python/test_extensions.py
```

2. **Run teleoperation with Isaac Lab**

```bash
# In the IsaacTeleop repo:
./scripts/run_isaac_lab.sh
```

## Documentation

### Getting Started
- [Build Instructions](BUILD.md) - CMake build options, troubleshooting
- [Contributing Guide](CONTRIBUTING.md) - Code style, PR process, DCO

### Architecture
- [Core Modules](src/core/README.md) - OXR, DeviceIO, Python bindings
- [Retargeting Engine](src/core/retargeting_engine/python/retargeters/README.md) - Hand retargeters
- [Teleop Session Manager](src/core/teleop_session_manager/README.md) - Session API

### Plugins
- [Manus Gloves](src/plugins/manus/README.md) - Manus SDK integration
- [OAK-D Camera](src/plugins/oakd/README.md) - DepthAI camera plugin
- [Synthetic Hands](src/plugins/controller_synthetic_hands/README.md) - Controller-based hand simulation

### Examples
- [OpenXR Examples](examples/oxr/README.md) - C++ and Python OpenXR tracking
- [LeRobot Integration](examples/lerobot/README.md) - Dataset recording/visualization
- [Camera Streaming](examples/cam_streamer/README.md) - GStreamer OAK-D pipeline
- [Teleop Session](examples/teleop_session_manager/python/README.md) - Session API usage

### Dependencies
- [Dependencies Overview](deps/README.md) - Dependency management
