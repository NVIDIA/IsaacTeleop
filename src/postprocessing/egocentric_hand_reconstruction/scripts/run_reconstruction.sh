#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

# Check arguments
if [ $# -lt 1 ]; then
    echo "Usage: $0 <video_path>"
    echo "Example: $0 my-local-path/my-video.mp4"
    echo "Example: $0 s3://my-remote-path/my-video.mp4"
    echo ""
    echo "For bucket URLs (s3://), set credentials in environment variables:"
    echo "  ACCESS_KEY_ID"
    echo "  SECRET_ACCESS_KEY"
    echo "Optional:"
    echo "  BUCKET_REGION (default: us-east-1)"
    echo "  BUCKET_ENDPOINT_URL"
    exit 1
fi

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUTS_DIR="${OUTPUTS_DIR:-${PROJECT_ROOT}/outputs}"
VIDEO_PATH="$1"
VIDEO_FULL_PATH=""
VIDEO_FILE=""
BUCKET_DOWNLOADER="${PROJECT_ROOT}/scripts/download_video_from_bucket.py"

mkdir -p "${OUTPUTS_DIR}"

is_bucket_url() {
    [[ "$1" == swift://* || "$1" == s3://* ]]
}

if is_bucket_url "${VIDEO_PATH}"; then
    VIDEO_FILE="$(basename "${VIDEO_PATH}")"
    VIDEO_FULL_PATH="${OUTPUTS_DIR}/${VIDEO_FILE}"
else
    if [ -f "${VIDEO_PATH}" ]; then
        VIDEO_FULL_PATH="${VIDEO_PATH}"
    else
        VIDEO_FULL_PATH="${PROJECT_ROOT}/${VIDEO_PATH}"
    fi
    if [ ! -f "${VIDEO_FULL_PATH}" ]; then
        echo "Error: Video file not found at ${VIDEO_FULL_PATH}"
        exit 1
    fi
    VIDEO_FILE="$(basename "${VIDEO_FULL_PATH}")"
fi

# Extract video name (without extension)
VIDEO_NAME="${VIDEO_FILE%.*}"

# Check for required licensed data (needed by Dyn-HaMR in Step 3)
missing=0
if [ ! -f "${OUTPUTS_DIR}/MANO_RIGHT.pkl" ]; then
    echo "Error: MANO_RIGHT.pkl not found in ${OUTPUTS_DIR}/"
    missing=1
fi
if [ ! -d "${OUTPUTS_DIR}/BMC" ] || [ -z "$(ls -A "${OUTPUTS_DIR}/BMC/" 2>/dev/null)" ]; then
    echo "Error: BMC data not found in ${OUTPUTS_DIR}/BMC/"
    missing=1
fi
if [ "$missing" -eq 1 ]; then
    exit 1
fi

echo "Processing video: ${VIDEO_PATH}"
echo "Video name: ${VIDEO_NAME}"

echo ""
echo "=========================================="
echo "Step 1: Preparing video for processing"
echo "=========================================="

if is_bucket_url "${VIDEO_PATH}"; then
    if [ ! -f "${VIDEO_FULL_PATH}" ]; then
        if ! command -v python3 >/dev/null 2>&1; then
            echo "Error: python3 is required to download bucket URLs."
            exit 1
        fi
        if [ ! -f "${BUCKET_DOWNLOADER}" ]; then
            echo "Error: Bucket downloader script not found at ${BUCKET_DOWNLOADER}"
            exit 1
        fi
        python3 "${BUCKET_DOWNLOADER}" "${VIDEO_PATH}" "${VIDEO_FULL_PATH}"
        echo "✓ Video downloaded to outputs directory"
    else
        echo "✓ Video already downloaded in outputs directory"
    fi
else
    # Copy local video to outputs if not already there
    if [ ! -f "${OUTPUTS_DIR}/${VIDEO_FILE}" ]; then
        cp "${VIDEO_FULL_PATH}" "${OUTPUTS_DIR}/${VIDEO_FILE}"
        echo "✓ Video copied to outputs directory"
    else
        echo "✓ Video already in outputs directory"
    fi
fi

echo ""
echo "=========================================="
echo "Step 2: Running ViPE for camera estimation"
echo "=========================================="
"${PROJECT_ROOT}/docker/vipe.sh" run vipe infer "vipe_results/${VIDEO_FILE}"

echo ""
echo "=========================================="
echo "Step 3: Running Dyn-HaMR (setup + reconstruction)"
echo "=========================================="
"${PROJECT_ROOT}/docker/dynhamr.sh" run bash -c "
    # Run setup script (configs, dependencies, HMP disable)
    bash /home/appuser/setup_dynhamr.sh

    # Create symlink to video inside container
    ln -sf /home/appuser/outputs/${VIDEO_FILE} /home/appuser/Dyn-HaMR/test/videos/${VIDEO_FILE}
    echo '✓ Video linked inside container'

    # Run reconstruction
    cd /home/appuser/Dyn-HaMR/dyn-hamr
    python run_opt.py \
        data=video_vipe \
        run_opt=True \
        run_vis=True \
        data.seq=${VIDEO_NAME} \
        is_static=False
"

echo ""
echo "=========================================="
echo "Pipeline Complete!"
echo "=========================================="
echo "Results saved to: ${OUTPUTS_DIR}/logs/"
