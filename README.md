<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Teleop Core

<div align="center">

**The unified framework for sim & real robot teleoperation**

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

### Sim-based teleop

- **CPU**: AMD Ryzen Threadripper 7960x (Recommended)
- **GPU**: 1x RTX 6000 Pro (Blackwell) or 2x RTX 6000 (Ada)

### Real robot teleop

- **CPU**: X86, and ARM support coming soon
- **GPU**: NVIDIA GPU required

## Quick Start

### Prerequisites

- **OS**: Ubuntu 22.04 or 24.04
- **Python**: 3.11 or newer (version configured in root `CMakeLists.txt`)
- **CUDA**: 12.8 (Recommended)
- **NVIDIA Driver**: 580.95.05 (Recommended)

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
git clone --recursive git@github.com:nvidia-isaac/TeleopCore.git
cd TeleopCore
```

> **Note**: The `--recursive` flag ensures git submodules (like pybind11) are
> initialized automatically. If you've already cloned without it, run:
> ```bash
> git submodule update --init --recursive
> ```

4. **Download CloudXR**

Download CloudXR PID (Product Information Delivery) from NVOnline (https://partners.nvidia.com/).
In the package, you should found two `tar.gz` files:

Place `cloudxr-runtime-server-webrtc-6.1.0-beta-rc1.tar.gz` under the `deps/cloudxr` folder:
```
deps/
├── cloudxr
│   ├── CLOUDXR_LICENSE
│   ├── docker-compose.yaml
│   └── cloudxr-runtime-server-webrtc-6.1.0-beta-rc1.tar.gz
```

Place `cloudxr-js-client-6.0.0-beta.tar.gz` under the `examples/cxrjs/pid` folder:
```
examples/cxrjs/
├── build_containers.sh
├── pid
│   └── cloudxr-js-client-6.0.0-beta.tar.gz
```

5. **Build and load CloudXR containers**
```bash
./examples/cxrjs/build_containers.sh
./scripts/load_cloudxr_images.sh
```

> **Important:** Make sure you place the `.gz` and `.tgz` files from the previous steps at the
> designated location. Otherwise, you will see an error like this:
> ```
> Error: File not found: ./deps/cloudxr/cloudxr-runtime-server-webrtc-6.1.0-beta-rc1.tar.gz
> ```

6. **Run CloudXR**
```bash
./scripts/run_cloudxr.sh
```

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
cmake --build build
cmake --install build
```

Install the Python package
```bash
uv pip install build/wheels/teleopcore-*.whl
```

Validate the Python package has been successfully built and installed.
```bash
python -c "import teleopcore.xrio"
```

2. **Run Teleop with Isaac Lab**

```bash
# In the Teleop Core repo:
./scripts/run_isaac_lab.sh
```