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
- **Python**: 3.11
- **CUDA**: 12.8 (Recommended)
- **NVIDIA Driver**: 580.95.05 (Recommended)

### Installation

1. **Create Conda Environment**
```bash
conda create -n teleop python=3.11 -y
conda activate teleop
```

2. **Quick Install**
```bash
git clone git@github.com:nvidia-isaac/TeleopCore.git
cd TeleopCore
```

3. **Running CloudXR**
```
./scripts/run_cloudxr.sh
```