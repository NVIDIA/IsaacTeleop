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
- **Python**: 3.11 (version configured in root `CMakeLists.txt`)
- **CUDA**: 12.8 (Recommended)
- **NVIDIA Driver**: 580.95.05 (Recommended)

### Installation

1. **Create Conda Environment**
```bash
conda create -n teleop python=3.11 -y
conda activate teleop
```

2. **Update pip**
```bash
pip install --upgrade pip
```

2. **Quick Install**
```bash
git clone --recursive git@github.com:nvidia-isaac/TeleopCore.git
cd TeleopCore
```

Note: The `--recursive` flag ensures git submodules (like pybind11) are initialized automatically. If you've already cloned without it, run:
```bash
git submodule update --init --recursive
```

3. **Run CloudXR**
```bash
./scripts/run_cloudxr.sh
```

### Install & Run Isaac Lab

Isaac Tepeop Core is design to work side by side with [NVIDIA Isaac Lab](https://github.com/isaac-sim/IsaacLab). We recommend the [Installation using Isaac Sim Pip Package](https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/pip_installation.html) method for Isaac Lab.  Please refer to Isaac Lab's [Installation](https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/index.html) guide for other advanced methods. Here are the quick steps to do so.

1. **Install dependencies**

```bash
conda activate teleop
pip install "isaacsim[all,extscache]==5.1.0" --extra-index-url https://pypi.nvidia.com
pip install -U torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128
```

2. **Clone & install Isaac Lab**

```bash
# In a separate folder outside of Teleop Core:
git clone git@github.com:isaac-sim/IsaacLab.git

# Run the install command
cd IsaacLab
./isaaclab.sh --install

# Set ISAACLAB_PATH, which will be later in `run_isaac_lab.sh`.
export ISAACLAB_PATH=$(pwd)
```

3. **Run Teleop with Isaac Lab**

```bash
# In the Teleop Core repo:
./scripts/run_isaac_lab.sh
```