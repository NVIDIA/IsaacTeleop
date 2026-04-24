<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Egocentric Hand Reconstruction

Automated pipeline for 4D hand and camera pose reconstruction from egocentric videos. Integrates ViPE and Dyn-HaMR in containerized environments.

## Setup

### System Requirement

- OS: Ubuntu 24.04
- GPU: NVIDIA RTX 6000 Ada or L40
- Memory: 100GB (for a reference 30s video, more for longer)
- Storage: 100GB

### Prepare data files

Place required files in `outputs/` directory.

```
...
├── doc/
├── docker/
├── scripts/
├── ...
└── outputs/
    ├── MANO_RIGHT.pkl
    └── BMC/
        └── *.npy
```


**MANO model** (required):
- Download from: https://mano.is.tue.mpg.de/
- Place: `outputs/MANO_RIGHT.pkl`

**BMC data** (required):
- Follow the README in https://github.com/MengHao666/Hand-BMC-pytorch to generate (until the step `python calculate_bmc.py`)
- Place all `.npy` files in: `outputs/BMC/`

> **Note:** The Hand-BMC-pytorch repository is no longer actively maintained, so parts of its setup may not work out-of-the-box on newer systems. At the time of writing, the `environment.yml` pins PyTorch to a specific build (`py3.7_cuda10.0.130_cudnn7.6.2_0`) that may no longer be available on Conda channels or compatible with current hardware. If Conda fails to resolve the environment, one workaround is to relax the pins in `environment.yml`:
> ```yaml
> # Before
> - pytorch==1.2.0=py3.7_cuda10.0.130_cudnn7.6.2_0
> - torchvision==0.4.0=py37_cu100
>
> # After
> - pytorch=1.2.0
> - torchvision=0.4.0
> ```
> This fix reflects the state of the upstream repo at the time of writing and may need to be adjusted as the ecosystem evolves.

### Build Docker images

```bash
./docker/vipe.sh build
./docker/dynhamr.sh build
```

> **Note:** Building these Docker images pulls third-party source code, libraries, and pre-trained model weights from external repositories. These components are subject to their own respective licenses, which may include restrictions on use, modification, or redistribution. It is the user's responsibility to review and comply with all applicable third-party licenses before building, using, or distributing these images. Refer to each Dockerfile for the specific sources pulled during the build.

## Hand Reconstruction

Run complete reconstruction (ViPE + Dyn-HaMR) with a single command:

```bash
# Using a local video file
./scripts/run_reconstruction.sh path/to/your_video.mp4

# Using a remote video file
./scripts/run_reconstruction.sh s3://path/to/your_video.mp4
```

The script accepts either a **local file path** or a **`s3://` URL** pointing to a video on a S3-compatible cloud storage. When a URL is provided, the video is automatically downloaded to the `outputs/` directory before processing begins.

To use a remote video, set the following environment variables for credentials:

| Variable | Required | Description |
|---|---|---|
| `ACCESS_KEY_ID` | Yes | Your S3 access key ID |
| `SECRET_ACCESS_KEY` | Yes | Your S3 access key |
| `BUCKET_REGION` | No | Region (default: `us-east-1`) |
| `BUCKET_ENDPOINT_URL` | No | Custom endpoint for S3-compatible storage |

By default, the pipeline reads data files from and writes results to the `outputs/` directory. Set `OUTPUTS_DIR` to use a different location:

```bash
OUTPUTS_DIR=/path/to/outputs ./scripts/run_reconstruction.sh path/to/your_video.mp4
```

The pipeline will:
1. Copy or download the video to `outputs/`.
2. Run ViPE to estimate camera poses.
3. Run Dyn-HaMR for hand reconstruction.
4. Save all results to `outputs/logs/`.

### View results

```bash
# List results
ls outputs/logs/video-custom/<DATE>/<VIDEO_NAME>*/

# View visualization
vlc outputs/logs/video-custom/<DATE>/<VIDEO_NAME>*/*_grid.mp4
```
